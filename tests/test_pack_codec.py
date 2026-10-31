import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from mt2sp_hub.authoring import create
from mt2sp_hub.core.packages import build
from mt2sp_hub.core.validation import digest
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation import pack_codec as codec
from mt2sp_hub.installation.client_pack import STARTUP, compose
from mt2sp_hub.installation.client_files import PATHS

CONFIG = {'eter_pack_index_key': [1, 2, 3, 4], 'eter_pack_data_key': [5, 6, 7, 8]}


@unittest.skipIf(codec.lzokay is None, 'Optional game codec dependency is not installed')
class PackTests(unittest.TestCase):
    def setUp(self):
        self.empty = codec.EterPack(struct.pack('<4sII', b'EPKD', 2, 0), b'', CONFIG)
        self.files = {'game.py': b'class GameWindow(object):\n    pass\n',
                      'unchanged.txt': b'original invented content', 'empty.txt': b''}
        self.pair = dict(zip(PATHS, self.empty.build(self.files)))
        self.config = json.dumps(CONFIG).encode()
        self.expected = {p: digest(raw) for p, raw in {**self.pair, 'pack/root.json': self.config}.items()}

    def package(self, ident):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name) / 'source'
        create(folder, ident, 'client', profile='game')
        return build(folder)

    def test_roundtrip_empty_compressed_encrypted_and_unencrypted_objects(self):
        for raw in (b'', b'original fixture' * 100):
            for encrypted in (False, True):
                with self.subTest(encrypted=encrypted, size=len(raw)):
                    encoded = codec.encode_object(raw, CONFIG['eter_pack_data_key'], encrypted)
                    self.assertEqual(codec.decode_object(encoded, CONFIG['eter_pack_data_key']), raw)
        self.assertEqual(codec.EterPack(*self.pair.values(), CONFIG).files(), self.files)

    def test_xtea_roundtrip_preserves_little_endian_blocks_and_rejects_invalid_keys(self):
        raw = bytes(range(256)) * 2
        encrypted = codec.xtea(raw, (1, 2, 3, 4))
        self.assertNotEqual(encrypted, raw)
        self.assertEqual(codec.xtea(raw, (1, 2, 3, 4)), encrypted)
        self.assertEqual(codec.xtea(encrypted, (1, 2, 3, 4), True), raw)
        with self.assertRaises(ValueError):
            codec.xtea(raw, (True, 2, 3, 4))

    def test_two_modules_compose_once_and_removal_restores_exact_original_pair(self):
        packages = [self.package('example.one'), self.package('example.two')]
        outputs = compose(self.pair, self.config, packages, self.expected)
        logical = codec.EterPack(*outputs.values(), CONFIG).files()
        self.assertEqual(logical['game.py'], self.files['game.py'] + STARTUP)
        self.assertEqual(logical['unchanged.txt'], self.files['unchanged.txt'])
        self.assertEqual(len(logical), len(self.files) + 4)
        self.assertIn(b'example.one', logical['mt2sp_hub_payload.py'])
        self.assertIn(b'example.two', logical['mt2sp_hub_payload.py'])
        self.assertEqual(compose(self.pair, self.config, [], self.expected), self.pair)
        self.assertEqual(compose(self.pair, self.config, packages, self.expected), outputs)

    def test_unmodified_encoded_members_are_preserved(self):
        before = codec.EterPack(*self.pair.values(), CONFIG)
        desired = {**self.files, 'new.py': b'pass\n'}
        after = codec.EterPack(*before.build(desired), CONFIG)
        for name in self.files:
            old, new = before.entries[name], after.entries[name]
            self.assertEqual(before.data_bytes[old['position']:old['position'] + old['size']],
                             after.data_bytes[new['position']:new['position'] + new['size']])

    def test_bad_baseline_wrong_keys_crc_and_truncated_objects_fail(self):
        with self.assertRaises(HubError):
            compose({**self.pair, PATHS[1]: b'changed'}, self.config, [], self.expected)
        wrong = {**CONFIG, 'eter_pack_index_key': [11, 12, 13, 14]}
        with self.assertRaises(ValueError):
            codec.EterPack(*self.pair.values(), wrong)
        pack = codec.EterPack(*self.pair.values(), CONFIG)
        changed = bytearray(pack.data_bytes)
        changed[pack.entries['game.py']['position']] ^= 1
        with self.assertRaises(ValueError):
            codec.EterPack(pack.index_bytes, bytes(changed), CONFIG).files()
        with self.assertRaises(ValueError):
            codec.decode_object(b'MCOZ', [1, 2, 3, 4])

    def test_oversized_objects_builds_and_normalized_duplicates_are_refused(self):
        with patch.object(codec, 'MAX_OBJECT', 2), self.assertRaises(ValueError):
            codec.encode_object(b'large', [1, 2, 3, 4])
        with patch.object(codec, 'MAX_PACK', 2), self.assertRaises(ValueError):
            self.empty.build({'a': b'large'})
        with self.assertRaises(ValueError):
            self.empty.build({'Name': b'a', 'name': b'b'})
        with self.assertRaises(ValueError):
            self.empty.build({'../escape': b'a'})

    def test_pack_limits_and_configuration_errors_are_sanitized(self):
        with patch('mt2sp_hub.installation.client_pack.MAX_PAIR', 1), self.assertRaises(HubError):
            compose(self.pair, self.config, [], self.expected)
        raw = b'private-sentinel-not-json'
        expected = {**self.expected, 'pack/root.json': digest(raw)}
        with self.assertRaises(HubError) as caught:
            compose(self.pair, raw, [], expected)
        self.assertNotIn('private-sentinel', str(caught.exception))

    def test_reserved_host_module_in_baseline_is_never_overwritten(self):
        pair = dict(zip(PATHS, self.empty.build({**self.files, 'mt2sp_hub_runtime.py': b'existing module'})))
        expected = {p: digest(raw) for p, raw in {**pair, 'pack/root.json': self.config}.items()}
        with self.assertRaises(HubError) as caught:
            compose(pair, self.config, [self.package('example.one')], expected)
        self.assertEqual(caught.exception.code, 'client_collision')
