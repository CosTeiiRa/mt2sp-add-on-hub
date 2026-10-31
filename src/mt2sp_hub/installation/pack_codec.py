"""Bounded EterPack v2/type 0-2 codec; keys come from the user's installed config.

Adapted from the original MIT implementation by Metin2 Studio contributors.
The host supplies verified pack bytes and locally installed key configuration. No game
files or keys are distributed with this project. lzokay provides LZO 1X.
"""
from __future__ import annotations

import hashlib
import re
import struct
import zlib
from pathlib import PurePosixPath

try:
    import lzokay
except ImportError:
    lzokay = None

HEADER = struct.Struct('<4sIII')
RECORD = struct.Struct('<I161s3xIIIIIB3x')
MAX_OBJECT = 64 * 1024 * 1024
MAX_PACK = 256 * 1024 * 1024
MASK = 0xffffffff


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _lzo():
    if lzokay is None:
        raise ValueError('Client packs require the Hub game dependencies (lzokay 2.1.0).')
    return lzokay


def xtea(data: bytes, key, decrypt=False):
    if len(key) != 4 or any(type(k) is not int or not 0 <= k <= MASK for k in key):
        raise ValueError('Invalid pack key configuration.')
    if len(data) % 8:
        raise ValueError('Encrypted pack object is not block aligned.')
    result = bytearray(len(data))
    for off in range(0, len(data), 8):
        a, b = struct.unpack_from('<II', data, off)
        if decrypt:
            total = 0xc6ef3720
            for _ in range(32):
                b = (b - ((((a << 4) ^ (a >> 5)) + a) ^ (total + key[(total >> 11) & 3]))) & MASK
                total = (total - 0x9e3779b9) & MASK
                a = (a - ((((b << 4) ^ (b >> 5)) + b) ^ (total + key[total & 3]))) & MASK
        else:
            total = 0
            for _ in range(32):
                a = (a + ((((b << 4) ^ (b >> 5)) + b) ^ (total + key[total & 3]))) & MASK
                total = (total + 0x9e3779b9) & MASK
                b = (b + ((((a << 4) ^ (a >> 5)) + a) ^ (total + key[(total >> 11) & 3]))) & MASK
        struct.pack_into('<II', result, off, a, b)
    return bytes(result)


def decode_object(data: bytes, key):
    if len(data) < 20:
        raise ValueError('Truncated MCOZ object.')
    magic, encrypted, compressed, raw_size = HEADER.unpack_from(data)
    if magic != b'MCOZ':
        raise ValueError('Only the documented MCOZ/LZO pack format is supported.')
    if not 0 <= raw_size <= MAX_OBJECT or compressed > MAX_OBJECT or encrypted > MAX_OBJECT:
        raise ValueError('Pack object exceeds size limits.')
    size = encrypted or compressed + 4
    if size > len(data) - HEADER.size or size < compressed + 4:
        raise ValueError('Truncated pack object payload.')
    payload = data[HEADER.size:HEADER.size + size]
    if encrypted:
        payload = xtea(payload, key, decrypt=True)
    if payload[:4] != magic:
        raise ValueError('Pack key does not match the installed pack.')
    try:
        raw = _lzo().decompress(payload[4:4 + compressed], raw_size)
    except Exception as exc:
        raise ValueError('Pack decompression or size validation failed.') from exc
    if len(raw) != raw_size:
        raise ValueError('Pack object decompressed size mismatch.')
    return raw


def encode_object(data: bytes, key, encrypt=True):
    if not isinstance(data, bytes) or len(data) > MAX_OBJECT:
        raise ValueError('Logical file is too large.')
    # lzokay 2.1.0 emits a redundant marker for empty input; canonical LZO EOF
    # is 0x11 0x00 0x00 and works with both the native client and the decoder.
    compressed = _lzo().compress(data) if data else b'\x11\x00\x00'
    payload = b'MCOZ' + compressed
    if encrypt:
        payload += b'\x00' * (-len(payload) % 8)
        payload = xtea(payload, key)
    return HEADER.pack(b'MCOZ', len(payload) if encrypt else 0, len(compressed), len(data)) + payload


def logical_name(name):
    name = name.replace('\\', '/').lower()
    p = PurePosixPath(name)
    # Existing packs contain virtual d:/ymir work/... assets. These names are
    # never materialized on disk; creator payloads have stricter confinement.
    checked = name[3:] if re.match(r'^[a-z]:/', name) else name
    if not name or name.startswith('/') or ':' in checked or any(x in ('', '.', '..') for x in checked.split('/')):
        raise ValueError('Unsafe logical pack filename.')
    if str(p) != name or '\x00' in name:
        raise ValueError('Malformed logical pack filename.')
    return name


class EterPack:
    def __init__(self, index: bytes, data: bytes, config: dict):
        if len(index) > MAX_PACK or len(data) > MAX_PACK:
            raise ValueError('Pack exceeds the supported size limit.')
        self.index_bytes, self.data_bytes = index, data
        self.config = config
        self.index_key = config['eter_pack_index_key']
        if any(not isinstance(config.get(name), (list, tuple)) or len(config[name]) != 4
               or any(type(k) is not int or not 0 <= k <= MASK for k in config[name])
               for name in ('eter_pack_index_key', 'eter_pack_data_key')):
            raise ValueError('Invalid local pack configuration.')
        self.data_key = config['eter_pack_data_key']
        raw_index = decode_object(index, self.index_key) if index[:4] == b'MCOZ' else index
        if len(raw_index) < 12:
            raise ValueError('Truncated pack index.')
        magic, version, count = struct.unpack_from('<4sII', raw_index)
        if magic != b'EPKD' or version != 2 or count > 100000 or len(raw_index) != 12 + count * RECORD.size:
            raise ValueError('Unsupported pack index version or record layout.')
        self.entries = {}
        self._decoded = {}
        for i in range(count):
            ident, name_raw, name_crc, allocation, data_size, crc, position, kind = RECORD.unpack_from(raw_index, 12 + i * RECORD.size)
            if name_crc == 0:
                continue
            name = logical_name(name_raw.split(b'\x00', 1)[0].decode('utf-8', errors='strict'))
            if name in self.entries:
                raise ValueError('Duplicate logical filename in pack.')
            if kind not in (0, 1, 2):
                raise ValueError('Unsupported pack entry type %s; no files have been changed.' % kind)
            if position > len(data) or data_size > len(data) - position:
                raise ValueError('Pack entry points outside the content file.')
            self.entries[name] = {'id': ident, 'name_crc': name_crc, 'allocation': allocation,
                                  'size': data_size, 'crc': crc, 'position': position, 'kind': kind}

    def read(self, name):
        name = logical_name(name)
        if name in self._decoded:
            return self._decoded[name]
        entry = self.entries[name]
        encoded = self.data_bytes[entry['position']:entry['position'] + entry['size']]
        # The client checks the stored/encrypted bytes, not the decompressed source.
        if entry['crc'] and zlib.crc32(encoded) & MASK != entry['crc']:
            raise ValueError('Stored file CRC mismatch: ' + name)
        try:
            result = encoded if entry['kind'] == 0 else decode_object(encoded, self.data_key)
        except ValueError as exc:
            raise ValueError(name + ': ' + str(exc)) from exc
        if len(result) > MAX_OBJECT:
            raise ValueError('Logical pack member exceeds its size limit.')
        self._decoded[name] = result
        return result

    def files(self):
        result, total = {}, 0
        for name in self.entries:
            raw = self.read(name)
            total += len(raw)
            if total > MAX_PACK:
                raise ValueError('Expanded pack exceeds the total size limit.')
            result[name] = raw
        return result

    def build(self, files):
        if (not isinstance(files, dict) or len(files) > 100000
                or any(not isinstance(raw, bytes) or len(raw) > MAX_OBJECT for raw in files.values())
                or sum(map(len, files.values())) > MAX_PACK):
            raise ValueError('Too many pack entries.')
        names = [logical_name(name) for name in files]
        if len(set(names)) != len(names):
            raise ValueError('Duplicate logical pack names after normalization.')
        index = bytearray(struct.pack('<4sII', b'EPKD', 2, len(files)))
        content = bytearray()
        for ident, (name, raw) in enumerate(sorted(files.items())):
            name = logical_name(name)
            name_bytes = name.encode('utf-8')
            if len(name_bytes) > 160:
                raise ValueError('Pack filename is longer than 160 bytes.')
            original = self.entries.get(name)
            if original and raw == self.read(name):
                encoded = self.data_bytes[original['position']:original['position'] + original['size']]
                kind = original['kind']
            else:
                kind, encoded = 2, encode_object(raw, self.data_key)
            if len(content) + (len(encoded) + 255) // 256 * 256 > MAX_PACK:
                raise ValueError('Encoded pack exceeds its size limit.')
            position = len(content)
            content.extend(encoded)
            allocation = (len(encoded) + 255) // 256 * 256
            content.extend(b'\x00' * (allocation - len(encoded)))
            index.extend(RECORD.pack(ident, name_bytes, zlib.crc32(name_bytes) & MASK,
                                     allocation, len(encoded), zlib.crc32(encoded) & MASK, position, kind))
        return encode_object(bytes(index), self.index_key), bytes(content)
