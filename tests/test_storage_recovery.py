import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mt2sp_hub.installation import storage
from mt2sp_hub.installation.manager import Manager, initialize
from helpers import package
from storage_faults import write_fault

WORKER = Path(__file__).with_name('crash_worker.py')
BASELINE = {'client/message.txt': b'Original client bytes', 'server/quest.txt': b'Original server bytes'}
FAULTS = ('partial', 'short', 'flush', 'fsync', 'directory-sync')
CRASHES = ('crash-partial', 'crash-flushed', 'crash-replaced')


class StorageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hub-storage-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def case(self, label):
        root = self.base / label
        initialize(root)
        manager = Manager(root)
        for relative, raw in BASELINE.items():
            target = manager.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        plan = manager.plan([package()])['plan']
        return manager, plan

    def crash(self, manager, plan, stage, operation='apply-write'):
        result = subprocess.run([sys.executable, str(WORKER), str(manager.root), operation,
                                 plan, stage], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 73, 'Storage crash boundary was not reached')

    def check_recovery(self, manager, *, committed, pending=True):
        # Reopening is essential: recovery must use disk records, not old memory.
        manager = Manager(manager.root)
        self.assertEqual(manager.status()['recovery_required'], pending)
        self.assertEqual(manager.status()['generation'], int(committed))
        after = package().unpack()[1]
        for relative, before in BASELINE.items():
            self.assertIn((manager.root / relative).read_bytes(), (before, after[relative]))
        expected = ('applied' if committed else 'rolled_back') if pending else 'nothing_pending'
        self.assertEqual(manager.recover()['outcome'], expected)
        for relative, raw in (after if committed else BASELINE).items():
            self.assertEqual((manager.root / relative).read_bytes(), raw)
        self.assertEqual(len(manager.status()['packages']), int(committed))
        self.assertFalse(manager.status()['recovery_required'])
        self.assertEqual(manager.recover()['outcome'], 'nothing_pending')

    def test_apply_recovers_from_each_storage_failure(self):
        for fault in FAULTS:
            for phase in ('journal', 'client', 'server', 'state', 'receipt'):
                with self.subTest(fault=fault, phase=phase):
                    manager, plan = self.case(fault + '-' + phase)
                    destinations = {'journal': '.mt2sp-hub/active.json', 'client': 'client/message.txt',
                                    'server': 'server/quest.txt', 'state': '.mt2sp-hub/state.json',
                                    'receipt': '.mt2sp-hub/receipts/' + plan + '.json'}
                    with write_fault(manager.root / destinations[phase], fault), self.assertRaises(OSError):
                        manager.apply(plan)
                    published = fault == 'directory-sync'
                    committed = phase == 'receipt' or (phase == 'state' and published)
                    pending = phase != 'journal' or published
                    self.check_recovery(manager, committed=committed, pending=pending)
                    self.assertEqual(list(manager.root.rglob('.hub-*.tmp')), [])
                    if not pending:
                        self.assertEqual(manager.apply(plan)['outcome'], 'applied')

    def test_process_death_during_temporary_writes_and_replacement(self):
        for fault in CRASHES:
            for phase in ('journal', 'client', 'server', 'state', 'receipt'):
                with self.subTest(fault=fault, phase=phase):
                    manager, plan = self.case(fault + '-' + phase)
                    destinations = {'journal': '.mt2sp-hub/active.json', 'client': 'client/message.txt',
                                    'server': 'server/quest.txt', 'state': '.mt2sp-hub/state.json',
                                    'receipt': '.mt2sp-hub/receipts/' + plan + '.json'}
                    self.crash(manager, plan, fault + ':' + destinations[phase])
                    leftovers = {path: path.read_bytes() for path in manager.root.rglob('.hub-*.tmp')}
                    self.assertEqual(len(leftovers), 0 if fault == 'crash-replaced' else 1)
                    published = fault == 'crash-replaced'
                    committed = phase == 'receipt' or (phase == 'state' and published)
                    pending = phase != 'journal' or published
                    self.check_recovery(manager, committed=committed, pending=pending)
                    # Abandoned scratch bytes are never promoted or swept by name.
                    self.assertEqual({path: path.read_bytes() for path in manager.root.rglob('.hub-*.tmp')}, leftovers)

    def test_rollback_can_restart_after_a_failed_or_interrupted_write(self):
        for fault in FAULTS + CRASHES:
            with self.subTest(fault=fault):
                manager, plan = self.case('rollback-' + fault)
                self.crash(manager, plan, 'file:server/quest.txt', operation='apply')
                if fault in CRASHES:
                    self.crash(manager, '-', fault + ':server/quest.txt', operation='recover-write')
                else:
                    with write_fault(manager.root / 'server/quest.txt', fault), self.assertRaises(OSError):
                        manager.recover()
                self.check_recovery(manager, committed=False)

    def test_failed_cache_import_leaves_installation_unchanged_and_can_retry(self):
        for fault in FAULTS:
            with self.subTest(fault=fault):
                root = self.base / ('cache-' + fault)
                initialize(root)
                manager = Manager(root)
                addon = package()
                with write_fault(manager.store.path('objects/' + addon.sha256), fault), self.assertRaises(OSError):
                    manager.plan([addon])
                self.assertFalse(manager.status()['recovery_required'])
                self.assertEqual(manager.status()['generation'], 0)
                self.assertFalse((root / 'client').exists())
                self.assertFalse((root / 'server').exists())
                self.assertEqual(list(root.rglob('.hub-*.tmp')), [])
                plan = manager.plan([addon])
                self.assertEqual(manager.apply(plan['plan'])['outcome'], 'applied')

    def test_failed_removal_before_or_after_unlink_restores_installed_bytes(self):
        original_unlink = storage.unlink
        for after_unlink in (False, True):
            with self.subTest(after_unlink=after_unlink):
                root = self.base / ('remove-' + str(after_unlink))
                initialize(root)
                manager = Manager(root)
                manager.apply(manager.plan([package()])['plan'])
                plan = manager.plan(remove=['example.one'])

                def fail_unlink(path):
                    if path == manager.root / 'client/message.txt':
                        if after_unlink:
                            original_unlink(path)
                        raise OSError('Synthetic removal failure')
                    return original_unlink(path)

                with patch('mt2sp_hub.installation.manager.unlink', fail_unlink), self.assertRaises(OSError):
                    manager.apply(plan['plan'])
                manager = Manager(root)
                self.assertEqual(manager.recover()['outcome'], 'rolled_back')
                self.assertEqual(manager.status()['generation'], 1)
                for relative, raw in package().unpack()[1].items():
                    self.assertEqual((root / relative).read_bytes(), raw)
                self.assertEqual(manager.apply(manager.plan(remove=['example.one'])['plan'])['outcome'], 'applied')
                self.assertEqual(manager.status()['packages'], [])

    def test_failed_journal_cleanup_preserves_committed_state_and_receipt(self):
        original_unlink = storage.unlink
        for after_unlink in (False, True):
            with self.subTest(after_unlink=after_unlink):
                manager, plan = self.case('finish-' + str(after_unlink))

                def fail_unlink(path):
                    if path == manager.store.path('active.json'):
                        if after_unlink:
                            original_unlink(path)
                        raise OSError('Synthetic journal cleanup failure')
                    return original_unlink(path)

                with patch('mt2sp_hub.installation.manager.unlink', fail_unlink), self.assertRaises(OSError):
                    manager.apply(plan)
                receipt = manager.store.verified('receipts/' + plan + '.json')
                self.assertEqual(receipt['outcome'], 'applied')
                self.check_recovery(manager, committed=True, pending=not after_unlink)
                self.assertEqual(manager.store.verified('receipts/' + plan + '.json'), receipt)
