import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from mt2sp_hub.cli import main
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.manager import Manager
from mt2sp_hub.installation.probe import MAX_METADATA, locate, probe
from mt2sp_hub.installation.storage import Store


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hub-probe-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'Metin2 Singleplayer'
        fixtures = {'Klient/metin2client.exe': b'invented executable fixture',
                    'Klient/pack/root.index': b'invented index fixture',
                    'Klient/pack/root.data': b'invented data fixture',
                    'Klient/client.version': b'1.2.3', 'Serwer/VERSION': b'2.3.4',
                    'Serwer/files/items.json': b'{}',
                    'Serwer/linux-port/docker/game/Dockerfile': b'FROM scratch\n',
                    'Serwer/linux-port/docker/docker-compose.yml': b'services: {}\n',
                    'Serwer/linux-port/docker/.env': b'TEST_SECRET=synthetic-sensitive-value'}
        for relative, raw in fixtures.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.binding = locate(self.root)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): None if p.is_dir() else p.read_bytes()
                for p in self.root.rglob('*')}

    def claims(self, *, attachment='ready', claim=True):
        identity = {'schema': 1, 'kind': 'metin2sp', 'id': '1' * 32,
                    'world_root': os.path.normcase(str(self.binding.world)),
                    'client_root': os.path.normcase(str(self.binding.client)), 'attachment': attachment}
        world_store = Store(self.binding.world / '.mt2sp-hub')
        world_store.envelope('identity.json', identity)
        if claim:
            client_store = Store(self.binding.client / '.mt2sp-hub')
            client_store.envelope('claim.json', {
                'schema': 1, 'kind': 'metin2sp-client', 'installation': identity['id'],
                'world_root': identity['world_root'], 'client_root': identity['client_root']})
        return world_store

    def test_accepts_direct_game_client_server_pack_and_outer_folders(self):
        for selected in (self.root, self.root.parent, self.root / 'Klient',
                         self.root / 'Klient/pack', self.root / 'Serwer'):
            with self.subTest(selection=selected.name):
                self.assertEqual(locate(selected), self.binding)

    def test_probe_is_read_only_and_never_reads_environment_or_executes_commands(self):
        before = self.snapshot()
        original_open = Path.open
        opened = []

        def open_read(path, mode='r', *args, **kwargs):
            self.assertFalse(any(flag in mode for flag in 'wax+'))
            opened.append(path.relative_to(self.root.resolve()).as_posix())
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, 'open', open_read), \
                patch('subprocess.run', side_effect=AssertionError('Must not execute commands')), \
                patch('subprocess.Popen', side_effect=AssertionError('Must not start processes')):
            report = probe(self.root)
        self.assertEqual(set(opened), {'Klient/client.version', 'Serwer/VERSION'})
        self.assertEqual(before, self.snapshot())
        self.assertTrue(report['layout_complete'])
        self.assertFalse(report['can_install'])
        self.assertEqual(report['ownership']['status'], 'no_hub_records')
        self.assertEqual(report['runtime']['server'], 'not_checked')
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertNotIn('synthetic-sensitive-value', json.dumps(report))

    def test_missing_empty_and_nonregular_files_are_reported(self):
        (self.root / 'Klient/pack/root.data').unlink()
        (self.root / 'Klient/pack/root.index').write_bytes(b'')
        executable = self.root / 'Klient/metin2client.exe'
        executable.unlink()
        executable.mkdir()
        report = probe(self.root)
        self.assertEqual(report['client']['files'], {'metin2client.exe': 'not_regular',
                                                   'pack/root.index': 'empty', 'pack/root.data': 'missing'})
        self.assertFalse(report['layout_complete'])

    def test_multiple_compose_files_are_ambiguous_not_implicitly_selected(self):
        (self.root / 'Serwer/linux-port/docker/compose.yaml').write_text('services: {}')
        report = probe(self.root)
        self.assertEqual(report['server']['compose'], 'ambiguous')
        self.assertFalse(report['layout_complete'])

    def test_raw_version_contents_never_escape_into_reports(self):
        for raw in (b'private-note-sentinel', b'1.2.3\nprivate-note-sentinel', b'X' * 257, b'\xff'):
            (self.root / 'Klient/client.version').write_bytes(raw)
            report = probe(self.root)
            self.assertIsNone(report['client']['version_label'])
            self.assertNotIn('private-note-sentinel', json.dumps(report))

    def test_missing_selection_is_not_created(self):
        missing = self.root / 'missing-private-folder'
        with self.assertRaises(HubError) as caught:
            probe(missing)
        self.assertEqual(caught.exception.code, 'installation_not_found')
        self.assertFalse(missing.exists())

    def test_ambiguous_layout_requires_a_more_specific_selection(self):
        nested = self.root / 'Metin2 Singleplayer'
        (nested / 'Klient').mkdir(parents=True)
        (nested / 'Serwer').mkdir()
        with self.assertRaises(HubError) as caught:
            locate(self.root)
        self.assertEqual(caught.exception.code, 'installation_ambiguous')
        self.assertEqual(locate(self.root / 'Serwer'), self.binding)

    def test_path_resolution_errors_do_not_disclose_raw_paths(self):
        output = io.StringIO()
        with patch.object(Path, 'resolve', side_effect=RuntimeError('private-path-sentinel')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(main(['probe', 'invented-selection', '--json']), 2)
        self.assertEqual(json.loads(output.getvalue())['error'], 'installation_unreadable')
        self.assertNotIn('private-path-sentinel', output.getvalue())

    def test_matching_claims_remain_an_unlocked_snapshot_without_write_permission(self):
        self.claims()
        before = self.snapshot()
        report = probe(self.root)
        self.assertEqual(report['ownership'], {'status': 'matching_claims', 'snapshot_only': True})
        self.assertFalse(report['can_install'])
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(HubError):
            Manager(self.binding.world)  # Real ownership cannot unlock the synthetic writer.

    def test_pending_attachment_missing_claim_and_journal_are_distinguished(self):
        store = self.claims(attachment='pending', claim=False)
        self.assertEqual(probe(self.root)['ownership']['status'], 'recovery_required')
        self.claims(claim=False)
        self.assertEqual(probe(self.root)['ownership']['status'], 'incomplete')
        self.claims()
        store.write('active.json', {'synthetic': 'interrupted-operation'})
        self.assertEqual(probe(self.root)['ownership']['status'], 'recovery_required')

    def test_foreign_or_copied_claims_are_conflicts_and_paths_are_never_followed(self):
        store = self.claims()
        copied = Path(self.temporary.name) / 'copy'
        shutil.copytree(self.root, copied)
        self.assertEqual(probe(copied)['ownership']['status'], 'conflict')
        identity = store.verified('identity.json')
        identity['world_root'] = 'untrusted-private-location'
        store.envelope('identity.json', identity)
        report = probe(self.root)
        self.assertEqual(report['ownership']['status'], 'conflict')
        self.assertNotIn('untrusted-private-location', json.dumps(report))

    def test_different_installation_ids_conflict(self):
        self.claims()
        store = Store(self.binding.client / '.mt2sp-hub')
        claim = store.verified('claim.json')
        claim['installation'] = '2' * 32
        store.envelope('claim.json', claim)
        self.assertEqual(probe(self.root)['ownership']['status'], 'conflict')

    def test_invalid_oversized_and_unknown_schema_records_fail_closed(self):
        store = self.claims()
        path = store.path('identity.json')
        for raw in (b'{"sha256":"bad","data":{}}', b'{' * (MAX_METADATA + 1), b'private-note-sentinel'):
            path.write_bytes(raw)
            report = probe(self.root)
            self.assertEqual(report['ownership']['status'], 'invalid')
            self.assertNotIn('private-note-sentinel', json.dumps(report))
        self.claims()
        identity = store.verified('identity.json')
        identity['schema'] = True
        store.envelope('identity.json', identity)
        self.assertEqual(probe(self.root)['ownership']['status'], 'invalid')

    def test_synthetic_and_unrecognized_controls_are_not_treated_as_free(self):
        control = self.binding.world / '.mt2sp-hub'
        control.mkdir()
        self.assertEqual(probe(self.root)['ownership']['status'], 'unrecognized')
        Store(control).envelope('identity.json', {'kind': 'synthetic'})
        self.assertEqual(probe(self.root)['ownership']['status'], 'synthetic')

    def test_linked_file_is_not_followed(self):
        target = self.root / 'Klient/pack/root.data'
        target.unlink()
        outside = Path(self.temporary.name) / 'outside'
        outside.write_bytes(b'private-outside-sentinel')
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest('Host does not permit creating symbolic links')
        report = probe(self.root)
        self.assertEqual(report['client']['files']['pack/root.data'], 'unsafe_path')
        self.assertNotIn('private-outside-sentinel', json.dumps(report))

    def test_cli_reports_are_readable_or_json_without_local_paths(self):
        for suffix in ([], ['--json']):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['probe', str(self.root), *suffix]), 0)
            text = output.getvalue()
            self.assertNotIn(str(self.root), text)
            if suffix:
                self.assertFalse(json.loads(text)['can_install'])
            else:
                self.assertIn('Game installation is disabled', text)
                self.assertIn('Read-only inspection finished', text)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['probe', str(self.root / 'private-path-sentinel')]), 2)
        self.assertNotIn('private-path-sentinel', output.getvalue())
