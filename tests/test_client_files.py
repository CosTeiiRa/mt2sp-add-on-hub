import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mt2sp_hub.core.validation import digest
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation import client_files
from mt2sp_hub.installation.client_files import PATHS, prepare, verify, write
from mt2sp_hub.installation.probe import Binding
from mt2sp_hub.installation.storage import Store
from storage_faults import write_fault


class ClientFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hub-client-files-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.binding = Binding(root / 'Serwer', root / 'Klient')
        self.binding.world.mkdir()
        (self.binding.client / 'pack').mkdir(parents=True)
        self.store = Store(self.binding.world / '.mt2sp-hub')
        self.originals = {PATHS[0]: b'invented old index', PATHS[1]: b'invented old content'}
        self.outputs = {PATHS[0]: b'invented new index', PATHS[1]: b'invented new content'}
        for p, raw in self.originals.items():
            (self.binding.client / p).write_bytes(raw)
        self.expected = {p: digest(raw) for p, raw in self.originals.items()}

    def plan(self):
        record = prepare(self.binding, self.store, self.outputs, self.expected)
        # The parent coordinator owns this journal. These steps never create,
        # commit or erase it, nor infer activation permission from its presence.
        self.store.envelope('active.json', {'client': record})
        return record

    def current(self):
        return {p: (self.binding.client / p).read_bytes() for p in PATHS}

    def test_preparation_caches_both_revisions_without_changing_the_pack(self):
        record = self.plan()
        self.assertEqual(self.current(), self.originals)
        self.assertEqual(record, json.loads(json.dumps(record)))
        for p in PATHS:
            self.assertEqual(self.store.get(record['files'][p]['before']), self.originals[p])
            self.assertEqual(self.store.get(record['files'][p]['after']), self.outputs[p])

    def test_apply_verify_and_restore_are_repeatable_and_leave_coordinator_state_alone(self):
        record = self.plan()
        journal = self.store.path('active.json').read_bytes()
        for _ in range(2):
            write(self.binding, self.store, record)
            verify(self.binding, self.store, record)
            self.assertEqual(self.current(), self.outputs)
        for _ in range(2):
            write(self.binding, self.store, record, 'before')
            self.assertEqual(self.current(), self.originals)
        self.assertEqual(self.store.path('active.json').read_bytes(), journal)

    def test_interruption_between_pair_writes_recovers_from_serialized_record(self):
        record = self.plan()

        def interrupt(_):
            raise SystemExit('invented interruption')

        with self.assertRaises(SystemExit):
            write(self.binding, self.store, record, checkpoint=interrupt)
        self.assertEqual(self.current(), {PATHS[0]: self.outputs[PATHS[0]], PATHS[1]: self.originals[PATHS[1]]})
        store = Store(self.binding.world / '.mt2sp-hub')
        write(self.binding, store, store.verified('active.json')['client'], 'before')
        self.assertEqual(self.current(), self.originals)

    def test_atomic_write_failures_restore_both_original_files(self):
        for fault in ('partial', 'short', 'flush', 'fsync', 'directory-sync'):
            with self.subTest(fault=fault):
                record = self.plan()
                with write_fault(self.binding.client / PATHS[1], fault), self.assertRaises(OSError):
                    write(self.binding, self.store, record)
                write(self.binding, self.store, record, 'before')
                self.assertEqual(self.current(), self.originals)

    def test_interrupted_restoration_can_be_retried(self):
        record = self.plan()
        write(self.binding, self.store, record)

        def interrupt(_):
            raise SystemExit()

        with self.assertRaises(SystemExit):
            write(self.binding, self.store, record, 'before', checkpoint=interrupt)
        write(self.binding, self.store, record, 'before')
        self.assertEqual(self.current(), self.originals)

    def test_external_edit_blocks_whole_pair_before_restoration(self):
        record = self.plan()
        write(self.binding, self.store, record)
        (self.binding.client / PATHS[0]).write_bytes(b'official update or external edit')
        before = self.current()
        with self.assertRaises(HubError) as caught:
            write(self.binding, self.store, record, 'before')
        self.assertEqual(caught.exception.code, 'client_pack_drift')
        self.assertEqual(self.current(), before)

    def test_corrupt_backup_blocks_all_changes(self):
        record = self.plan()
        write(self.binding, self.store, record)
        self.store.path('objects/' + record['files'][PATHS[0]]['before']).write_bytes(b'damaged backup')
        with self.assertRaises(HubError):
            write(self.binding, self.store, record, 'before')
        self.assertEqual(self.current(), self.outputs)

    def test_stale_preparation_and_new_drift_at_each_write_boundary_are_refused(self):
        bad = dict(self.expected)
        bad[PATHS[1]] = 'a' * 64
        with self.assertRaises(HubError):
            prepare(self.binding, self.store, self.outputs, bad)
        self.assertFalse(self.store.root.exists())
        record = self.plan()

        def change_other(_):
            (self.binding.client / PATHS[1]).write_bytes(b'external change after first write')

        with self.assertRaises(HubError):
            write(self.binding, self.store, record, checkpoint=change_other)
        self.assertEqual((self.binding.client / PATHS[1]).read_bytes(), b'external change after first write')

    def test_pair_limits_fixed_paths_and_target_binding_are_enforced(self):
        with patch.object(client_files, 'MAX_PAIR', 5), self.assertRaises(HubError):
            prepare(self.binding, self.store, self.outputs, self.expected)
        record = self.plan()
        for field, value in (('client_root', 'invented-other-target'), ('schema', True), ('kind', 'other')):
            bad = copy.deepcopy(record)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(HubError):
                write(self.binding, self.store, bad)
        bad = copy.deepcopy(record)
        bad['files']['../other'] = bad['files'].pop(PATHS[0])
        with self.assertRaises(HubError):
            write(self.binding, self.store, bad)
        with self.assertRaises(HubError):
            write(self.binding, Store(self.binding.world / 'other-store'), record)
        self.assertEqual(self.current(), self.originals)

    def test_committed_revision_verification_never_repairs_external_edits(self):
        record = self.plan()
        write(self.binding, self.store, record)
        (self.binding.client / PATHS[1]).write_bytes(b'external content')
        before = self.current()
        with self.assertRaises(HubError):
            verify(self.binding, self.store, record)
        self.assertEqual(self.current(), before)
