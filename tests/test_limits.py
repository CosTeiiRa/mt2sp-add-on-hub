"""Real count limits and exact byte boundaries without large CI fixtures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mt2sp_hub.core import packages, resolver
from mt2sp_hub.core.validation import MAX_FILES, MAX_JSON, MAX_PACKAGES, encode, parse_json
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.manager import Manager, initialize
from helpers import archive, example, package


class LimitTests(unittest.TestCase):
    def check_code(self, code, operation):
        with self.assertRaises(HubError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def test_manifest_byte_limit_accepts_exact_boundary_and_rejects_one_more(self):
        raw = b'{}' + b' ' * (MAX_JSON - 2)
        self.assertEqual(parse_json(raw), {})
        self.check_code('json_limit', lambda: parse_json(raw + b' '))

    def test_single_file_and_package_byte_boundaries(self):
        # Same production comparisons with small byte budgets; real 64 MiB
        # lifecycles are measured separately by tools/measure_foundation.py.
        with patch.object(packages, 'MAX_FILE', 8), patch.object(packages, 'MAX_TOTAL', 16):
            exact = package(files={'client/a': b'a' * 8, 'server/b': b'b' * 8})
            self.assertEqual(sum(map(len, exact.unpack()[1].values())), 16)
            self.check_code('archive_limit', lambda: package(files={'client/a': b'a' * 9}).unpack())
            self.check_code('archive_limit', lambda: package(files={
                'client/a': b'a' * 8, 'server/b': b'b' * 8, 'server/c': b'c'}).unpack())
        with patch.object(packages, 'MAX_ARCHIVE', len(exact.raw)):
            exact.unpack()
            self.check_code('archive_limit', lambda: packages.unpack(exact.raw + b'x'))

    def test_real_single_package_file_limit_and_one_more(self):
        files = {'client/x/f' + str(i): b'x' for i in range(MAX_FILES)}
        manifest, members = example(files=files)
        self.assertLessEqual(len(encode(manifest)), MAX_JSON)
        self.assertEqual(len(archive(manifest, members).unpack()[1]), MAX_FILES)
        files['client/x/extra'] = b'x'
        oversized, _ = example(files=files)
        self.check_code('manifest_files', lambda: packages.validate_manifest(oversized))

    def test_real_file_limit_applies_across_components_and_packages(self):
        left = package('example.left', files={'client/a' + str(i): b'x' for i in range(MAX_FILES // 2)})
        right = package('example.right', files={'server/b' + str(i): b'x' for i in range(MAX_FILES // 2)})
        self.assertEqual(len(resolver.resolve([left, right])[1]), MAX_FILES)
        extra = package('example.extra', files={'server/extra': b'x'})
        self.check_code('selection_limit', lambda: resolver.resolve([left, right, extra]))
        manifest, _ = example(files={'client/a' + str(i): b'x' for i in range(MAX_FILES // 2)})
        other, _ = example(files={'server/b' + str(i): b'x' for i in range(MAX_FILES // 2 + 1)})
        # Source names must also be unique between components.
        for i, row in enumerate(other['components']['server']['files']):
            row['source'] = 'server' + str(i)
        manifest['components'].update(other['components'])
        self.check_code('manifest_files', lambda: packages.validate_manifest(manifest))

    def test_aggregate_output_byte_boundary(self):
        left = package('example.left', files={'client/a': b'a' * 8})
        right = package('example.right', files={'server/b': b'b' * 8})
        extra = package('example.extra', files={'client/c': b'c'})
        with patch.object(resolver, 'MAX_TOTAL', 16):
            self.assertEqual(sum(map(len, resolver.resolve([left, right])[1].values())), 16)
            self.check_code('selection_limit', lambda: resolver.resolve([left, right, extra]))

    def test_real_package_count_and_deep_dependency_chain(self):
        selected = [package('example.p' + str(i), files={'client/p' + str(i): b'x'},
                            requires={'example.p' + str(i - 1): '1.0.0'} if i else {})
                    for i in range(MAX_PACKAGES)]
        order = resolver.resolve(reversed(selected))[0]
        self.assertEqual(order, ['example.p' + str(i) for i in range(MAX_PACKAGES)])
        extra = package('example.extra', files={'server/extra': b'x'})
        self.check_code('package_limit', lambda: resolver.resolve(selected + [extra]))

    def test_real_maximum_package_and_file_count_lifecycle(self):
        selected = [package('example.p' + str(i), files={
            ('client/' if j % 2 == 0 else 'server/') + 'p' + str(i) + '/f' + str(j): b'x'
            for j in range(MAX_FILES // MAX_PACKAGES)}) for i in range(MAX_PACKAGES)]
        extra = package('example.extra', files={'server/extra': b'x'})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'sandbox'
            initialize(root)
            manager = Manager(root)
            manager.apply(manager.plan(selected)['plan'])
            self.assertEqual(len(manager.status()['packages']), MAX_PACKAGES)
            self.assertEqual(manager.status()['managed_files'], MAX_FILES)
            before = manager.store.verified('state.json')
            self.check_code('package_limit', lambda: manager.plan([extra]))
            self.assertEqual(manager.store.verified('state.json'), before)
            self.assertFalse(manager.status()['recovery_required'])
            ids = ['example.p' + str(i) for i in range(MAX_PACKAGES)]
            manager.apply(manager.plan(disable=ids)['plan'])
            self.assertEqual(manager.status()['managed_files'], 0)
            self.check_code('package_limit', lambda: manager.plan([extra]))
            manager.apply(manager.plan(remove=ids)['plan'])
            self.assertEqual(manager.status()['packages'], [])
            self.assertFalse(any(p.is_file() for kind in ('client', 'server') for p in (root / kind).rglob('*')))

    def test_addition_archive_budget_fails_before_cache_write(self):
        addon = package()
        with tempfile.TemporaryDirectory() as temporary:
            initialize(temporary)
            manager = Manager(temporary)
            with patch('mt2sp_hub.installation.manager.MAX_SELECTED_ARCHIVES', len(addon.raw) - 1):
                self.check_code('selection_limit', lambda: manager.plan([addon]))
            self.assertFalse(manager.store.path('objects').exists())
            with patch('mt2sp_hub.installation.manager.MAX_SELECTED_ARCHIVES', len(addon.raw)):
                self.assertIn('plan', manager.plan([addon]))

    def test_cached_budget_includes_disabled_packages_and_allows_offline_removal(self):
        left = package('example.left', files={'client/a': b'a'})
        right = package('example.right', files={'server/b': b'b'})
        total = len(left.raw) + len(right.raw)
        with tempfile.TemporaryDirectory() as temporary:
            initialize(temporary)
            manager = Manager(temporary)
            manager.apply(manager.plan([left])['plan'])
            manager.apply(manager.plan(disable=['example.left'])['plan'])
            before = manager.store.verified('state.json')
            with patch('mt2sp_hub.installation.manager.MAX_SELECTED_ARCHIVES', total - 1):
                self.check_code('selection_limit', lambda: manager.plan([right]))
            self.assertEqual(manager.store.verified('state.json'), before)
            self.assertFalse(manager.status()['recovery_required'])
            with patch('mt2sp_hub.installation.manager.MAX_SELECTED_ARCHIVES', total):
                manager.apply(manager.plan([right])['plan'])
                manager.apply(manager.plan(remove=['example.left', 'example.right'])['plan'])
            self.assertEqual(manager.status()['packages'], [])
