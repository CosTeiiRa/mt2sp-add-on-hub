import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mt2sp_hub.cli import main
from mt2sp_hub.core.validation import digest
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.baseline import check_build, fingerprint_file, fingerprint_tree, tree_digest
from mt2sp_hub.installation.probe import Binding, probe


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hub-baseline-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binding = Binding(self.root / 'Serwer', self.root / 'Klient')
        self.binding.world.mkdir()
        self.binding.client.mkdir()
        self.tree = self.binding.world / 'linux-port/docker/game'
        self.tree.mkdir(parents=True)
        (self.binding.client / 'client.version').write_bytes(b'2.0.3\r\n')
        (self.binding.world / 'VERSION').write_bytes(b'\xef\xbb\xbf2.2.3\n')
        (self.binding.client / 'metin2client.exe').write_bytes(b'invented native input')
        (self.tree / 'Dockerfile').write_bytes(b'FROM scratch\n')
        (self.tree / 'quest_functions').write_bytes(b'chat\n')
        self.profile = {'id': 'invented-2.2.3', 'client_version': '2.0.3', 'server_version': '2.2.3',
                        'files': {'client': {'metin2client.exe': fingerprint_file(self.binding.client / 'metin2client.exe')},
                                  'server': {'linux-port/docker/game/Dockerfile': fingerprint_file(self.tree / 'Dockerfile')}},
                        'server_trees': {'linux-port/docker/game': fingerprint_tree(self.tree)}}
        self.profile_patch = patch('mt2sp_hub.installation.baseline.PROFILE', self.profile)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)

    def check(self):
        return check_build(self.binding, '2.0.3', '2.2.3')

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_matching_bytes_are_read_only_and_do_not_authorize_activation(self):
        before = self.snapshot()
        with patch('subprocess.Popen', side_effect=AssertionError('No command execution')):
            report = probe(self.root, build=True)
        self.assertEqual(report['build']['status'], 'reference_match')
        self.assertFalse(report['build']['activation_supported'])
        self.assertFalse(report['can_install'])
        self.assertTrue(report['build']['snapshot_only'])
        self.assertEqual(self.snapshot(), before)

    def test_unknown_versions_never_self_register_or_hash_untrusted_files(self):
        with patch('mt2sp_hub.installation.baseline.fingerprint_file', side_effect=AssertionError('Unknown input')):
            report = check_build(self.binding, '8.8.8', '2.2.3')
        self.assertEqual(report['status'], 'unknown_build')
        self.assertIsNone(report['profile'])

    def test_matching_labels_do_not_hide_same_length_binary_changes(self):
        path = self.binding.client / 'metin2client.exe'
        raw = path.read_bytes()
        path.write_bytes(b'X' * len(raw))
        report = self.check()
        self.assertEqual(report['status'], 'reference_mismatch')
        self.assertEqual(report['client']['metin2client.exe'], 'different')

    def test_extra_missing_or_changed_build_inputs_are_detected_without_listing_local_names(self):
        for action in ('extra', 'missing', 'changed'):
            with self.subTest(action=action):
                path = self.tree / ('private-note-sentinel' if action == 'extra' else 'quest_functions')
                original = path.read_bytes() if path.exists() else None
                if action == 'missing':
                    path.unlink()
                else:
                    path.write_bytes(b'private-content-sentinel')
                report = self.check()
                self.assertEqual(report['server']['linux-port/docker/game/'], 'different')
                self.assertNotIn('sentinel', json.dumps(report))
                self.assertNotIn(str(self.root), json.dumps(report))
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_missing_and_nonregular_individual_inputs_are_distinguished(self):
        path = self.binding.client / 'metin2client.exe'
        path.unlink()
        self.assertEqual(self.check()['client']['metin2client.exe'], 'missing')
        path.mkdir()
        self.assertEqual(self.check()['client']['metin2client.exe'], 'invalid')

    def test_tree_is_deterministic_and_does_not_depend_on_creation_order(self):
        first = fingerprint_tree(self.tree)
        original = (self.tree / 'Dockerfile').read_bytes()
        (self.tree / 'Dockerfile').unlink()
        (self.tree / 'Dockerfile').write_bytes(original)
        (self.tree / 'empty').mkdir()
        self.assertEqual(fingerprint_tree(self.tree), first)
        files = {p.name: {'bytes': len(p.read_bytes()), 'sha256': digest(p.read_bytes())}
                 for p in self.tree.iterdir() if p.is_file()}
        self.assertEqual(first, tree_digest(files))

    def test_tree_count_total_bytes_and_depth_limits_fail_closed(self):
        for constant, value in (('MAX_TREE_FILES', 1), ('MAX_TREE_BYTES', 2), ('MAX_TREE_ENTRIES', 1)):
            with self.subTest(constant=constant), patch('mt2sp_hub.installation.baseline.' + constant, value):
                self.assertEqual(self.check()['server']['linux-port/docker/game/'], 'limit_exceeded')
        deep = self.tree.joinpath(*(['d'] * 34))
        deep.mkdir(parents=True)
        self.assertEqual(self.check()['server']['linux-port/docker/game/'], 'limit_exceeded')

    def test_oversized_file_is_refused_before_opening_it(self):
        path = self.tree / 'quest_functions'
        with patch.object(Path, 'open', side_effect=AssertionError('Must not read oversized input')):
            with self.assertRaises(HubError) as caught:
                fingerprint_file(path, 2)
        self.assertEqual(caught.exception.code, 'file_limit')

    def test_file_replacement_during_read_and_tree_changes_are_rejected(self):
        real_fstat = os.fstat
        calls = []

        def changed_fstat(fd):
            info = real_fstat(fd)
            calls.append(info)
            if len(calls) == 2:
                (self.tree / 'quest_functions').write_bytes(b'changed bytes')
                return real_fstat(fd)
            return info

        with patch('os.fstat', side_effect=changed_fstat), self.assertRaises(HubError) as caught:
            fingerprint_file(self.tree / 'quest_functions')
        self.assertEqual(caught.exception.code, 'baseline_changed')
        import mt2sp_hub.installation.baseline as baseline
        original = baseline._inventory
        calls = []

        def changed_inventory(root):
            calls.append(root)
            if len(calls) == 2:
                (root / 'extra').write_bytes(b'new build input')
            return original(root)

        with patch.object(baseline, '_inventory', side_effect=changed_inventory):
            self.assertEqual(self.check()['server']['linux-port/docker/game/'], 'changed_during_check')

    def test_links_are_not_followed(self):
        link = self.tree / 'linked'
        try:
            link.symlink_to(self.binding.client, target_is_directory=True)
        except OSError:
            self.skipTest('Host does not permit creating symbolic links')
        self.assertEqual(self.check()['server']['linux-port/docker/game/'], 'unsafe_path')

    def test_case_collisions_are_not_portable(self):
        with self.assertRaises(HubError):
            tree_digest({'A/file': {'bytes': 1, 'sha256': 'a' * 64},
                         'a/other': {'bytes': 2, 'sha256': 'b' * 64}})

    def test_cli_outputs_sanitized_build_snapshot(self):
        for suffix in ([], ['--json']):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['probe', str(self.root), '--build', *suffix]), 0)
            self.assertNotIn(str(self.root), output.getvalue())
            if suffix:
                self.assertEqual(json.loads(output.getvalue())['build']['status'], 'reference_match')
            else:
                self.assertIn('Official build reference: reference match', output.getvalue())

    def test_maintainer_tool_rejects_changed_archive_before_reading_its_inventory(self):
        tool = Path(__file__).resolve().parents[1] / 'tools/review_game_baseline.py'
        spec = importlib.util.spec_from_file_location('baseline_review', tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        archive = self.root / 'official-fixture.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('invented.txt', b'original fixture')
        pin = fingerprint_file(archive)
        z, stream = module.open_archive(archive, pin)
        z.close()
        stream.close()
        raw = bytearray(archive.read_bytes())
        raw[-1] ^= 1
        archive.write_bytes(raw)
        with self.assertRaises(HubError) as caught:
            module.open_archive(archive, pin)
        self.assertEqual(caught.exception.code, 'archive_hash')
