import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.manager import Manager, initialize
from helpers import package

WORKER = Path(__file__).with_name('crash_worker.py')


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hub-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'sandbox'
        initialize(self.root)
        self.manager = Manager(self.root)

    def apply(self, **kwargs):
        plan = self.manager.plan(**kwargs)
        self.manager.apply(plan['plan'])
        return plan

    def check_code(self, code, operation):
        with self.assertRaises(HubError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def crash(self, stage, plan=None, operation='apply'):
        result = subprocess.run([sys.executable, str(WORKER), str(self.root), operation,
                                 plan or '-', stage], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 73, 'Crash checkpoint was not reached')

    def test_requires_empty_synthetic_target(self):
        other = Path(self.temporary.name) / 'ordinary'
        other.mkdir()
        (other / 'keep.txt').write_text('keep')
        self.check_code('sandbox_not_empty', lambda: initialize(other))
        self.check_code('sandbox_required', lambda: Manager(other))
        self.assertEqual((other / 'keep.txt').read_text(), 'keep')

    def test_plan_is_read_only_for_targets_and_survives_reopen(self):
        plan = self.manager.plan([package()])
        self.assertFalse((self.root / 'client').exists())
        self.assertEqual(self.manager.status()['generation'], 0)
        Manager(self.root).apply(plan['plan'])
        self.assertEqual(self.manager.status()['generation'], 1)

    def test_install_update_disable_enable_and_baseline_restoration(self):
        path = self.root / 'client/message.txt'
        path.parent.mkdir()
        path.write_bytes(b'original base')
        self.apply(additions=[package()])
        self.apply(additions=[package(version='1.1.0', files={'client/message.txt': b'updated', 'client/new.txt': b'new'})])
        self.assertEqual(path.read_bytes(), b'updated')
        self.assertFalse((self.root / 'server/quest.txt').exists())
        self.apply(disable=['example.one'])
        self.assertEqual(path.read_bytes(), b'original base')
        self.assertFalse((self.root / 'client/new.txt').exists())
        self.apply(enable=['example.one'])
        self.assertEqual(path.read_bytes(), b'updated')
        self.apply(remove=['example.one'])
        self.assertEqual(path.read_bytes(), b'original base')
        self.assertEqual(self.manager.status()['packages'], [])

    def test_removal_preserves_other_package_and_unmanaged_files(self):
        other = package('example.two', files={'client/other.txt': b'other'})
        self.apply(additions=[package(), other])
        (self.root / 'client/personal.txt').write_bytes(b'keep local')
        self.apply(remove=['example.one'])
        self.assertEqual((self.root / 'client/other.txt').read_bytes(), b'other')
        self.assertEqual((self.root / 'client/personal.txt').read_bytes(), b'keep local')

    def test_immutable_release_survives_uninstall(self):
        self.apply(additions=[package()])
        self.apply(remove=['example.one'])
        self.check_code('release_changed', lambda: self.manager.plan([package(files={'client/changed': b'new'})]))

    def test_disabled_dependencies_do_not_satisfy_active_packages(self):
        dep = package('example.dep', files={'server/dep': b'x'})
        child = package(requires={'example.dep': '1.0.0'})
        self.apply(additions=[dep, child])
        self.check_code('dependency_missing', lambda: self.manager.plan(disable=['example.dep']))
        self.apply(disable=['example.one', 'example.dep'])
        self.assertEqual(self.manager.status()['managed_files'], 0)

    def test_stale_plan_after_another_apply(self):
        old = self.manager.plan([package()])
        self.apply(additions=[package('example.two', files={'client/other': b'x'})])
        self.check_code('plan_stale', lambda: self.manager.apply(old['plan']))

    def test_stale_target_preserved_before_mutation(self):
        plan = self.manager.plan([package()])
        target = self.root / 'client/message.txt'
        target.parent.mkdir()
        target.write_bytes(b'external')
        self.check_code('plan_stale', lambda: self.manager.apply(plan['plan']))
        self.assertFalse(self.manager.status()['recovery_required'])
        self.assertEqual(target.read_bytes(), b'external')

    def test_managed_external_drift_blocks_new_plan(self):
        self.apply(additions=[package()])
        (self.root / 'client/message.txt').write_bytes(b'external')
        self.check_code('target_drift', lambda: self.manager.plan(remove=['example.one']))

    def test_missing_backup_blocks_before_any_write(self):
        plan = self.manager.plan([package()])
        detail = self.manager.store.verified('plans/' + plan['plan'] + '.json')
        key = detail['changes'][0]['after']
        self.manager.store.path('objects/' + key).write_bytes(b'corrupt')
        self.check_code('object_corrupt', lambda: self.manager.apply(plan['plan']))
        self.assertFalse((self.root / 'client').exists())
        self.assertFalse(self.manager.status()['recovery_required'])

    def test_crash_at_every_activation_boundary(self):
        for stage in ['journal', 'file:client/message.txt', 'file:server/quest.txt', 'state', 'receipt', 'complete']:
            with self.subTest(stage=stage):
                root = Path(self.temporary.name) / ('case-' + stage.replace(':', '-').replace('/', '-'))
                initialize(root)
                manager = Manager(root)
                plan = manager.plan([package()])
                result = subprocess.run([sys.executable, str(WORKER), str(root), 'apply', plan['plan'], stage],
                                        capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 73, 'Crash checkpoint was not reached')
                reopened = Manager(root)
                outcome = reopened.recover()['outcome']
                committed = stage in ['state', 'receipt', 'complete']
                self.assertEqual(reopened.status()['generation'], 1 if committed else 0)
                self.assertEqual((root / 'client/message.txt').exists(), committed)
                self.assertEqual((root / 'server/quest.txt').exists(), committed)
                self.assertEqual(outcome, 'nothing_pending' if stage == 'complete' else 'applied' if committed else 'rolled_back')
                self.assertFalse(reopened.status()['recovery_required'])

    def test_crash_during_rollback_is_recoverable(self):
        plan = self.manager.plan([package()])
        self.crash('file:server/quest.txt', plan['plan'])
        self.crash('restore:server/quest.txt', operation='recover')
        self.assertEqual(Manager(self.root).recover()['outcome'], 'rolled_back')
        self.assertFalse((self.root / 'client/message.txt').exists())
        self.assertEqual(self.manager.status()['generation'], 0)

    def test_pending_recovery_blocks_new_writes_and_plans(self):
        plan = self.manager.plan([package()])
        self.crash('journal', plan['plan'])
        self.check_code('recovery_required', lambda: self.manager.plan([package()]))
        self.check_code('recovery_required', lambda: self.manager.apply(plan['plan']))

    def test_recovery_never_overwrites_external_edits(self):
        plan = self.manager.plan([package()])
        self.crash('file:server/quest.txt', plan['plan'])
        (self.root / 'client/message.txt').write_bytes(b'external')
        server = (self.root / 'server/quest.txt').read_bytes()
        self.check_code('recovery_conflict', self.manager.recover)
        self.assertEqual((self.root / 'client/message.txt').read_bytes(), b'external')
        self.assertEqual((self.root / 'server/quest.txt').read_bytes(), server)
        self.assertTrue(self.manager.status()['recovery_required'])

    def test_recovered_plan_cannot_overwrite_its_receipt(self):
        plan = self.manager.plan([package()])
        self.crash('journal', plan['plan'])
        self.manager.recover()
        self.check_code('plan_used', lambda: self.manager.apply(plan['plan']))

    def test_state_and_plan_checksum_corruption(self):
        plan = self.manager.plan([package()])
        path = self.manager.store.path('plans/' + plan['plan'] + '.json')
        raw = self.manager.store.read('plans/' + plan['plan'] + '.json')
        raw['data']['after']['generation'] = 999
        self.manager.store.write('plans/' + plan['plan'] + '.json', raw)
        self.check_code('state_corrupt', lambda: self.manager.apply(plan['plan']))
        state = self.manager.store.read('state.json')
        state['data']['schema'] = 999
        self.manager.store.write('state.json', state)
        self.check_code('state_corrupt', self.manager.status)

    def test_unknown_state_schema_and_copy_identity(self):
        copied = Path(self.temporary.name) / 'copied'
        shutil.copytree(self.root, copied)
        self.check_code('installation_identity', lambda: Manager(copied))
        state = self.manager.store.verified('state.json')
        state['schema'] = 999
        self.manager.store.envelope('state.json', state)
        self.check_code('state_schema', self.manager.status)

    def test_foreign_plan_refused(self):
        other = Path(self.temporary.name) / 'other'
        initialize(other)
        second = Manager(other)
        plan = self.manager.plan([package()])
        detail = self.manager.store.verified('plans/' + plan['plan'] + '.json')
        second.store.envelope('plans/' + plan['plan'] + '.json', detail)
        self.check_code('plan_invalid', lambda: second.apply(plan['plan']))

    def test_process_lock_and_release_after_exit(self):
        worker = subprocess.Popen([sys.executable, str(WORKER), str(self.root), 'lock', '-', '-'],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(worker.stdout.readline().strip(), 'locked')
            self.check_code('installation_busy', lambda: Manager(self.root / '.').plan([package()]))
        finally:
            worker.kill()
            worker.communicate(timeout=10)
        self.assertEqual(self.manager.status()['generation'], 0)

    def test_plan_path_cannot_escape_control_directory(self):
        self.check_code('plan_id', lambda: self.manager.apply('../identity'))

    def test_target_link_rejected(self):
        outside = Path(self.temporary.name) / 'external'
        outside.mkdir()
        try:
            (self.root / 'client').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Host does not permit creating symbolic links')
        self.check_code('path_link', lambda: self.manager.plan([package()]))
        self.assertEqual(list(outside.iterdir()), [])

    def test_write_error_retains_recovery_journal(self):
        def fail(stage):
            if stage.startswith('file:'):
                raise OSError('synthetic disk failure')
        manager = Manager(self.root, checkpoint=fail)
        plan = manager.plan([package()])
        with self.assertRaises(OSError):
            manager.apply(plan['plan'])
        self.assertTrue(self.manager.status()['recovery_required'])
        self.assertEqual(self.manager.recover()['outcome'], 'rolled_back')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction test')
    def test_windows_junction_rejected(self):
        outside = Path(self.temporary.name) / 'junction-target'
        outside.mkdir()
        link = self.root / 'client'
        created = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                 capture_output=True, timeout=10)
        self.assertEqual(created.returncode, 0, 'Could not create synthetic junction')
        try:
            self.check_code('path_link', lambda: self.manager.plan([package()]))
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            link.rmdir()

    def test_corrupted_restore_object_prevents_partial_recovery(self):
        baseline = self.root / 'client/message.txt'
        baseline.parent.mkdir()
        baseline.write_bytes(b'baseline')
        plan = self.manager.plan([package()])
        detail = self.manager.store.verified('plans/' + plan['plan'] + '.json')
        self.crash('file:server/quest.txt', plan['plan'])
        self.manager.store.path('objects/' + detail['changes'][0]['before']).write_bytes(b'corrupted')
        self.check_code('object_corrupt', self.manager.recover)
        self.assertEqual(baseline.read_bytes(), b'invented client data')
        self.assertTrue((self.root / 'server/quest.txt').exists())

    def test_committed_recovery_blocks_external_drift(self):
        plan = self.manager.plan([package()])
        self.crash('state', plan['plan'])
        (self.root / 'client/message.txt').write_bytes(b'external')
        self.check_code('recovery_conflict', self.manager.recover)
        self.assertEqual(self.manager.status()['generation'], 1)

    def test_replace_failures_preserve_recoverable_generations(self):
        real_replace = os.replace
        for failure in ['client', 'server', 'state', 'receipt']:
            with self.subTest(failure=failure):
                root = Path(self.temporary.name) / ('replace-' + failure)
                initialize(root)
                manager = Manager(root)
                plan = manager.plan([package()])

                def fail_replace(source, destination):
                    destination = Path(destination)
                    relative = destination.relative_to(manager.root).as_posix()
                    if (failure == 'client' and relative.startswith('client/')) or (
                        failure == 'server' and relative.startswith('server/')) or (
                        failure == 'state' and relative.endswith('/state.json')) or (
                        failure == 'receipt' and '/receipts/' in relative):
                        raise OSError('synthetic replace failure')
                    return real_replace(source, destination)

                with patch('mt2sp_hub.installation.storage.os.replace', side_effect=fail_replace), self.assertRaises(OSError):
                    manager.apply(plan['plan'])
                self.assertTrue(manager.status()['recovery_required'])
                expected = 'applied' if failure == 'receipt' else 'rolled_back'
                self.assertEqual(Manager(root).recover()['outcome'], expected)
                self.assertEqual((root / 'client/message.txt').exists(), failure == 'receipt')
                self.assertEqual(list(root.rglob('.hub-*.tmp')), [])
