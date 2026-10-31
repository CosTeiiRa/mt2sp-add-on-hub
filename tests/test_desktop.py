"""Desktop decisions tested against the real engines and invented game data."""
from pathlib import Path
from threading import Event
import tempfile
import time
import unittest
from unittest.mock import patch

from helpers import package
from game_fixture import addon, environment
from mt2sp_hub.cli import main
from mt2sp_hub.desktop import Workflow, Worker, command, failure
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.game_manager import GameManager, attach
from mt2sp_hub.installation.manager import Manager, initialize


HEALTHY = {'folder_binding': 'matched', 'server': 'running', 'health': 'healthy'}


class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sandbox = self.root / 'practice'
        initialize(self.sandbox)
        self.archive = self.root / 'example.zip'
        self.archive.write_bytes(package().raw)
        self.flow = Workflow()
        self.flow.select(self.sandbox)

    def assert_code(self, code, operation):
        with self.assertRaises(HubError) as found:
            operation()
        self.assertEqual(found.exception.code, code)

    def test_review_is_noninstalling_and_confirmation_uses_exact_cached_bytes(self):
        text = self.flow.prepare('add', self.archive)
        self.assertIn('example.one: not installed -> 1.0.0 (enabled)', text)
        self.assertNotIn(str(self.root), text)
        self.assertEqual(Manager(self.sandbox).status()['packages'], [])
        self.assertFalse((self.sandbox / 'client/message.txt').exists())
        self.archive.write_bytes(b'replaced after review')
        self.assertIn('Changes applied.', self.flow.confirm())
        self.assertEqual((self.sandbox / 'client/message.txt').read_bytes(), b'invented client data')
        self.assertIsNone(self.flow.review)
        self.assert_code('review_required', self.flow.confirm)

    def test_switch_refresh_and_cancel_discard_the_previous_review(self):
        other = self.root / 'other'
        initialize(other)
        for cancel in (lambda: self.flow.select(other), self.flow.refresh, lambda: setattr(self.flow, 'review', None)):
            self.flow.select(self.sandbox)
            self.flow.prepare('add', self.archive)
            cancel()
            self.assert_code('review_required', self.flow.confirm)
        self.assertEqual(Manager(self.sandbox).status()['packages'], [])
        self.assertEqual(Manager(other).status()['packages'], [])

    def test_update_disable_enable_remove_preview_matches_installed_state(self):
        self.flow.prepare('add', self.archive)
        self.flow.confirm()
        self.flow.prepare('disable', 'example.one')
        self.flow.confirm()
        self.archive.write_bytes(package(version='1.1.0').raw)
        self.assertIn('1.0.0 (disabled) -> 1.1.0 (disabled)', self.flow.prepare('add', self.archive))
        self.flow.confirm()
        self.assertFalse(self.flow.status['packages'][0]['enabled'])
        self.flow.prepare('enable', 'example.one')
        self.flow.confirm()
        self.assertTrue(self.flow.status['packages'][0]['enabled'])
        self.assertIn('1.1.0 (enabled) -> not installed', self.flow.prepare('remove', 'example.one'))
        self.flow.confirm()
        self.assertEqual(self.flow.status['packages'], [])
        self.assertFalse((self.sandbox / 'server/quest.txt').exists())

    def test_external_operation_invalidates_review_at_the_engine_boundary(self):
        self.flow.prepare('add', self.archive)
        manager = Manager(self.sandbox)
        manager.apply(manager.plan([package()])['plan'])
        self.assert_code('plan_stale', self.flow.confirm)
        self.assertIsNone(self.flow.review)
        self.assertIsNone(self.flow.status)
        self.flow.refresh()
        self.assertEqual(self.flow.status['generation'], 1)

    def test_failed_refresh_cannot_keep_old_inventory_or_review_actionable(self):
        self.flow.prepare('add', self.archive)
        with patch.object(self.flow, 'invoke', side_effect=OSError('invented-private-detail')):
            with self.assertRaises(OSError):
                self.flow.refresh()
        self.assertIsNone(self.flow.status)
        self.assertIsNone(self.flow.review)
        self.assert_code('check_required', lambda: self.flow.prepare('add', self.archive))

    def test_successful_apply_is_not_reported_as_failed_when_followup_check_fails(self):
        self.flow.prepare('add', self.archive)
        def invoke(*args):
            if args[0] == 'status':
                raise OSError('invented-private-detail')
            return command(*args)
        self.flow.invoke = invoke
        text = self.flow.confirm()
        self.assertIn('Changes applied.', text)
        self.assertIn('follow-up check did not finish', text)
        self.assertNotIn('invented-private-detail', text)
        self.assertIsNone(self.flow.status)

    def test_real_game_flow_uses_shared_attach_plan_and_combined_apply(self):
        root = self.root / 'invented-game'
        with environment(root, fresh=True), patch('mt2sp_hub.installation.probe.inspect_runtime', return_value=HEALTHY):
            (root / 'Serwer/files').mkdir()
            (root / 'Serwer/files/items.json').write_bytes(b'{}')
            flow = Workflow()
            flow.select(root)
            self.assertTrue(flow.setup_ready)
            self.assertFalse((root / 'Serwer/.mt2sp-hub').exists())
            flow.prepare('attach')
            self.assertFalse((root / 'Serwer/.mt2sp-hub').exists())
            self.assertIn('Hub setup completed.', flow.confirm())
            archive = self.root / 'combined.zip'
            archive.write_bytes(addon(root).raw)
            text = flow.prepare('add', archive)
            self.assertIn('Server restart: required', text)
            self.assertIn('example.lifecycle: not installed -> 0.1.0 (enabled)', text)
            self.assertEqual(GameManager(root).status()['generation'], 0)
            flow.confirm()
            self.assertTrue(flow.status['deployment_files_verified'])
            self.assertFalse(flow.status['gameplay_verified'])
            self.assertEqual((root / 'fixture-player-progress.json').read_bytes(), b'{"visits":7}')

    def test_unknown_build_and_unready_server_do_not_offer_setup(self):
        root = self.root / 'invented-game'
        with environment(root, fresh=True), patch('mt2sp_hub.installation.probe.inspect_runtime', return_value={}):
            (root / 'Serwer/files').mkdir()
            (root / 'Serwer/files/items.json').write_bytes(b'{}')
            flow = Workflow()
            self.assert_code('server_not_ready', lambda: flow.select(root))
            self.assertFalse(flow.setup_ready)
            self.assert_code('setup_checks', lambda: flow.prepare('attach'))
            (root / 'Klient/metin2client.exe').write_bytes(b'unsupported')
            self.assert_code('game_build', flow.refresh)
            self.assertFalse((root / 'Serwer/.mt2sp-hub').exists())

    def test_pending_attachment_and_interrupted_apply_have_the_same_recovery_entry(self):
        def fail(step):
            if step in ('attachment_journal', 'files_written'):
                raise OSError('invented interruption')
        root = self.root / 'invented-game'
        with environment(root, fresh=True):
            with self.assertRaises(OSError):
                attach(root, checkpoint=fail)
            flow = Workflow()
            flow.select(root)
            self.assertTrue(flow.status['recovery_required'])
            self.assert_code('check_required', lambda: flow.prepare('add', self.archive))
            flow.prepare('recover')
            self.assertIn('Hub setup completed.', flow.confirm())
            manager = GameManager(root, checkpoint=fail)
            with self.assertRaises(OSError):
                manager.apply(manager.plan([addon(root)])['plan'])
            flow.refresh()
            self.assertTrue(flow.status['recovery_required'])
            flow.prepare('recover')
            self.assertIn('Previous deployment restored.', flow.confirm())
            self.assertEqual(flow.status['packages'], [])
            self.assertFalse(flow.status['recovery_required'])

    def test_recovery_conflict_is_retained_and_never_silently_applied(self):
        def fail(step):
            if step == 'file:client/message.txt':
                raise OSError('invented interruption')
        manager = Manager(self.sandbox, checkpoint=fail)
        with self.assertRaises(OSError):
            manager.apply(manager.plan([package()])['plan'])
        target = self.sandbox / 'client/message.txt'
        target.write_bytes(b'external edit')
        self.flow.refresh()
        self.flow.prepare('recover')
        self.assert_code('recovery_conflict', self.flow.confirm)
        self.assertEqual(target.read_bytes(), b'external edit')
        self.assertTrue(Manager(self.sandbox).status()['recovery_required'])
        self.assertIsNone(self.flow.review)

    def test_cli_gui_dispatch_does_not_require_tk_in_the_other_commands(self):
        with patch('mt2sp_hub.desktop.launch', return_value=0) as launch:
            self.assertEqual(main(['gui', '--root', str(self.sandbox)]), 0)
        launch.assert_called_once_with(self.sandbox)

    def test_worker_serializes_operations_and_redacts_unexpected_failures(self):
        worker = Worker()
        gate = Event()
        self.addCleanup(gate.set)
        worker.start(lambda: gate.wait(5) or 'done')
        self.assertTrue(worker.busy)
        self.assert_code('desktop_busy', lambda: worker.start(lambda: None))
        gate.set()
        deadline = time.monotonic() + 5
        while worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(worker.busy)
        worker.start(lambda: (_ for _ in ()).throw(OSError('invented-private-detail')))
        result = None
        deadline = time.monotonic() + 5
        while result is None and time.monotonic() < deadline:
            result = worker.poll()
            time.sleep(0.01)
        self.assertTrue(result[1])
        self.assertNotIn('invented-private-detail', result[0])
        self.assertNotIn('invented-private-detail', failure(ValueError('invented-private-detail')))


if __name__ == '__main__':
    unittest.main()
