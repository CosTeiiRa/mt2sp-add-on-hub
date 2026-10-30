import io
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from mt2sp_hub.core.packages import Package, build, pack, unpack, validate_manifest
from mt2sp_hub.core.resolver import resolve
from mt2sp_hub.core.validation import encode, logical_path, parse_json, path_set
from mt2sp_hub.core.versions import Version, satisfies
from mt2sp_hub.errors import HubError
from helpers import archive, example, package


class PackageTests(unittest.TestCase):
    def test_three_component_types_and_no_payload_execution(self):
        for files in ({"client/tool.py": b"raise RuntimeError('must never execute')"},
                      {"server/quest.txt": b"synthetic"},
                      {"client/tool.txt": b"client", "server/quest.txt": b"server"}):
            with self.subTest(components=sorted(files)):
                manifest, outputs = package(files=files).unpack()
                self.assertEqual(outputs, files)
                self.assertEqual(set(manifest["components"]), {p.split('/')[0] for p in files})

    def test_semver_precedence_and_ranges(self):
        versions = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta',
                    '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0']
        self.assertEqual(sorted(versions, key=Version), versions)
        self.assertEqual(Version('1.0.0+one'), Version('1.0.0+two'))
        self.assertTrue(satisfies('1.2.0', '>=1.0.0 <2.0.0'))
        self.assertFalse(satisfies('2.0.0', '>=1.0.0 <2.0.0'))
        for value in ['01.0.0', '1.0', '1.0.0-01']:
            with self.assertRaises(ValueError):
                Version(value)

    def test_rejects_unsafe_portable_paths(self):
        for value in ['../escape', '/absolute', 'a//b', 'a/./b', 'a/../b', 'a\\b', 'C:file',
                      'file:stream', 'CON.txt', 'dir/LPT1', 'a.', 'a ', '\\host\\share', 'caf\u00e9', 'a\x00b']:
            with self.subTest(path=value), self.assertRaises(HubError):
                logical_path(value)

    def test_collision_paths(self):
        for paths in [['a', 'a'], ['a', 'A'], ['a', 'a/b'], ['A/one', 'a/two']]:
            with self.assertRaises(HubError):
                path_set(paths)

    def test_strict_json(self):
        for raw in [b'{"a":1,"a":2}', b'{"n":NaN}', b'{"n":1e999}', b'"\\ud800"',
                    b'[' * 34 + b'0' + b']' * 34, b'\xff', b'{} trailing']:
            with self.subTest(raw=raw[:20]), self.assertRaises(HubError):
                parse_json(raw)

    def test_json_limit(self):
        with self.assertRaises(HubError):
            parse_json(b'{}', limit=1)

    def test_manifest_unknown_and_legacy_fields_rejected(self):
        for key, value in [('format_version', 1), ('format_version', True), ('unknown', 'x'),
                           ('id', 'one'), ('version', '1'), ('requires', []), ('components', {}),
                           ('conflicts', ['example.one'])]:
            manifest, _ = example()
            manifest[key] = value
            with self.subTest(field=key), self.assertRaises(HubError):
                validate_manifest(manifest)

    def test_all_range_tokens_validated(self):
        manifest, _ = example(requires={'example.dep': '>99.0.0 invalid'})
        with self.assertRaises(HubError):
            validate_manifest(manifest)

    def test_payload_integrity_and_members(self):
        manifest, files = example()
        for mutated in [{**files, 'payload/file0.txt': b'changed'},
                        {k: v for k, v in files.items() if k != 'payload/file0.txt'},
                        {**files, 'private.txt': b'not declared'}]:
            with self.assertRaises(HubError):
                archive(manifest, mutated).unpack()

    def test_duplicate_case_and_traversal_zip_members(self):
        manifest, files = example()
        for name in ['payload/file0.txt', 'PAYLOAD/file0.txt', '../outside', 'a\x00b']:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                candidate = archive(manifest, files, [(name, b'x')])
            with self.subTest(name=name), self.assertRaises(HubError):
                candidate.unpack()

    def test_zip_symlink_and_special_file(self):
        manifest, files = example()
        for kind in [stat.S_IFLNK, stat.S_IFIFO]:
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as writer:
                writer.writestr('addon.json', encode(manifest))
                for name, raw in files.items():
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (kind | 0o644) << 16
                    writer.writestr(info, raw)
            with self.assertRaises(HubError):
                unpack(output.getvalue())

    def test_expanded_member_and_archive_limits(self):
        candidate = package()
        for constant, limit in [('MAX_FILE', 2), ('MAX_ARCHIVE', 4), ('MAX_TOTAL', 1), ('MAX_FILES', 0)]:
            # Lower limits exercise the same boundary without large fixtures.
            with patch('mt2sp_hub.core.packages.' + constant, limit), self.assertRaises(HubError):
                candidate.unpack()

    def test_bad_zip(self):
        with self.assertRaises(HubError):
            unpack(b'not a zip')

    def test_deterministic_pack_and_undeclared_source(self):
        manifest, files = example()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'addon.json').write_bytes(encode(manifest))
            for name, raw in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            self.assertEqual(pack(root).raw, pack(root).raw)
            (root / 'extra.txt').write_text('undeclared')
            with self.assertRaises(HubError):
                pack(root)

    def test_source_symlink_rejected(self):
        manifest, files = example(files={'client/demo': b'x'})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'addon.json').write_bytes(encode(manifest))
            (root / 'payload').mkdir()
            outside = root / 'outside'
            outside.write_bytes(b'x')
            try:
                (root / 'payload/file0.txt').symlink_to(outside)
            except OSError:
                self.skipTest('Host does not permit creating symbolic links')
            with self.assertRaises(HubError):
                pack(root)
            with self.assertRaises(HubError):
                build(root)

    def test_build_computes_hashes_without_editing_source_or_weakening_archive_validation(self):
        manifest, files = example()
        del manifest['components']['client']['files'][0]['sha256']
        manifest['components']['server']['files'][0]['sha256'] = '0' * 64
        original = encode(manifest)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'addon.json').write_bytes(original)
            for name, raw in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            result = build(root)
            self.assertEqual(result.raw, build(root).raw)
            self.assertEqual((root / 'addon.json').read_bytes(), original)
            self.assertEqual(result.unpack()[1], package().unpack()[1])
            with self.assertRaises(HubError):
                pack(root)
            with self.assertRaises(HubError):
                archive(manifest, files).unpack()
            (root / 'payload/file0.txt').write_bytes(b'Updated source')
            changed = build(root)
            self.assertNotEqual(changed.sha256, result.sha256)
            self.assertIn(b'Updated source', changed.unpack()[1].values())
            (root / 'private.txt').write_text('undeclared')
            with self.assertRaises(HubError):
                build(root)

    def test_build_keeps_strict_checks_for_declared_hashes_and_unknown_fields(self):
        for key, value in [('sha256', 'bad'), ('extra', True), ('source', '../escape')]:
            manifest, _ = example()
            manifest['components']['client']['files'][0][key] = value
            with self.subTest(field=key), self.assertRaises(HubError):
                validate_manifest(manifest, source=True)

    def test_dependency_order_is_deterministic(self):
        base = package('example.base', files={'server/base': b'b'})
        child = package('example.child', requires={'example.base': '>=1.0.0'}, files={'client/child': b'c'})
        self.assertEqual(resolve([child, base])[0], ['example.base', 'example.child'])
        self.assertEqual(resolve([base, child])[0], resolve([child, base])[0])

    def test_dependency_missing_version_and_cycles(self):
        child = package('example.child', requires={'example.base': '>=2.0.0'}, files={'client/child': b'c'})
        base = package('example.base', files={'server/base': b'b'})
        for selected in [[child], [child, base],
                         [package('example.a', requires={'example.b': '1.0.0'}, files={'client/a': b'a'}),
                          package('example.b', requires={'example.a': '1.0.0'}, files={'client/b': b'b'})]]:
            with self.assertRaises(HubError):
                resolve(selected)

    def test_conflicts_and_ownership(self):
        for selected in [[package(), package('example.two')],
                         [package(), package('example.two', files={'client/MESSAGE.txt': b'x'})],
                         [package(conflicts=['example.two']), package('example.two', files={'client/other': b'x'})],
                         [package(), package()]]:
            with self.assertRaises(HubError):
                resolve(selected)

    def test_api_and_capabilities(self):
        for apis, caps in [({}, {'fixture.files'}),
                           ({'client': '2.0.0', 'server': '1.0.0'}, {'fixture.files'}),
                           ({'client': '1.0.0', 'server': '1.0.0'}, set())]:
            with self.assertRaises(HubError):
                resolve([package()], apis, caps)

    def test_corrupt_deflate_is_a_controlled_validation_error(self):
        manifest, files = example()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as writer:
            writer.writestr('addon.json', encode(manifest))
            for name, raw in files.items():
                writer.writestr(name, raw)
        raw = bytearray(output.getvalue())
        with zipfile.ZipFile(io.BytesIO(raw)) as reader:
            info = reader.getinfo('payload/file0.txt')
            start = info.header_offset + 30 + len(info.filename.encode())
            raw[start:start + info.compress_size] = b'\xff' * info.compress_size
        with self.assertRaises(HubError):
            unpack(bytes(raw))
