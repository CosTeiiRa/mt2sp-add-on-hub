"""Content-addressed objects and replace-based, flushed local records."""
from __future__ import annotations

import errno
import os
import uuid
from pathlib import Path

from ..errors import require
from ..core.validation import SHA, confined, digest, encode, parse_json, read_bounded

MAX_RECORD = 8 * 1024 * 1024


def sync_directory(directory):
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def atomic_write(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".hub-" + uuid.uuid4().hex + ".tmp")
    created = False
    try:
        with temporary.open("xb") as stream:
            created = True
            if stream.write(raw) != len(raw):
                raise OSError(errno.EIO, "Incomplete temporary-file write")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def unlink(path):
    path.unlink(missing_ok=True)
    sync_directory(path.parent)


class Store:
    def __init__(self, root):
        self.root = root

    def path(self, relative):
        return confined(self.root, relative)

    def write(self, relative, value):
        raw = encode(value)
        require(len(raw) <= MAX_RECORD, "state_limit", "State record exceeds its limit.")
        atomic_write(self.path(relative), raw)

    def read(self, relative):
        return parse_json(read_bounded(self.path(relative), MAX_RECORD), MAX_RECORD)

    def envelope(self, relative, value):
        self.write(relative, {"sha256": digest(encode(value)), "data": value})

    def verified(self, relative):
        envelope = self.read(relative)
        require(isinstance(envelope, dict) and set(envelope) == {"sha256", "data"}
                and envelope["sha256"] == digest(encode(envelope["data"])),
                "state_corrupt", "State record checksum does not match.")
        return envelope["data"]

    def put(self, raw):
        key = digest(raw)
        path = self.path("objects/" + key)
        if path.exists():
            require(self.get(key) == raw, "object_corrupt", "Stored object is damaged.")
        else:
            atomic_write(path, raw)
        return key

    def get(self, key):
        require(isinstance(key, str) and SHA.fullmatch(key), "object_id", "Invalid object digest.")
        raw = read_bounded(self.path("objects/" + key), 66 * 1024 * 1024)
        require(digest(raw) == key, "object_corrupt", "Stored object is damaged.")
        return raw
