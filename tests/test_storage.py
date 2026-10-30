import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mt2sp_hub.installation import storage
from storage_faults import write_fault


class StorageTests(unittest.TestCase):
    def test_unfinished_writes_never_replace_existing_bytes(self):
        for stage in ('partial', 'short', 'flush', 'fsync'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / 'record.json'
                target.write_bytes(b'Original complete record')
                with write_fault(target, stage), self.assertRaises(OSError):
                    storage.atomic_write(target, b'Replacement complete record')
                self.assertEqual(target.read_bytes(), b'Original complete record')
                self.assertEqual(list(target.parent.glob('.hub-*.tmp')), [])

    def test_exclusive_temporary_creation_never_deletes_an_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'record.json'
            existing = root / '.hub-fixed.tmp'
            target.write_bytes(b'Original')
            existing.write_bytes(b'Unrelated file')
            with patch.object(storage.uuid, 'uuid4') as token:
                token.return_value.hex = 'fixed'
                with self.assertRaises(FileExistsError):
                    storage.atomic_write(target, b'Replacement')
            self.assertEqual(target.read_bytes(), b'Original')
            self.assertEqual(existing.read_bytes(), b'Unrelated file')

    def test_empty_and_nonempty_writes_replace_complete_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'nested' / 'file.txt'
            for raw in (b'Initial bytes', b'', b'Replacement bytes'):
                storage.atomic_write(target, raw)
                self.assertEqual(target.read_bytes(), raw)
                self.assertEqual(list(target.parent.glob('.hub-*.tmp')), [])
