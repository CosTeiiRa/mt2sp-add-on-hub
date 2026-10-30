"""Storage faults used only by synthetic tests and their subprocess workers."""
import errno
import os
from contextlib import contextmanager, ExitStack
from pathlib import Path
from unittest.mock import patch

from mt2sp_hub.installation import storage


def disk_error():
    raise OSError(errno.ENOSPC, 'Synthetic storage failure')


class FaultyStream:
    def __init__(self, stream, stage):
        self.stream, self.stage = stream, stage

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, raw):
        if self.stage in ('partial', 'short', 'crash-partial'):
            written = self.stream.write(raw[:len(raw) // 2])
            if self.stage == 'crash-partial':
                self.stream.flush()
                os._exit(73)
            if self.stage == 'partial':
                disk_error()
            return written
        return self.stream.write(raw)

    def flush(self):
        if self.stage == 'flush':
            disk_error()
        return self.stream.flush()

    def fileno(self):
        return self.stream.fileno()


@contextmanager
def write_fault(target, stage):
    """Interrupt one destination's real temporary-file write or replacement."""
    original_write = storage.atomic_write
    original_open = Path.open
    original_fsync = os.fsync
    original_replace = os.replace

    def open_stream(path, mode='r', *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return FaultyStream(stream, stage) if mode == 'xb' else stream

    def fsync(descriptor):
        if stage == 'fsync':
            disk_error()
        original_fsync(descriptor)
        if stage == 'crash-flushed':
            os._exit(73)

    def replace(source, destination):
        original_replace(source, destination)
        if stage == 'crash-replaced':
            os._exit(73)

    def write(path, raw):
        if path != target:
            return original_write(path, raw)
        with ExitStack() as patches:
            patches.enter_context(patch.object(Path, 'open', open_stream))
            patches.enter_context(patch.object(storage.os, 'fsync', fsync))
            patches.enter_context(patch.object(storage.os, 'replace', replace))
            if stage == 'directory-sync':
                patches.enter_context(patch.object(storage, 'sync_directory', lambda _: disk_error()))
            return original_write(path, raw)

    with patch('mt2sp_hub.installation.storage.atomic_write', write), \
            patch('mt2sp_hub.installation.manager.atomic_write', write):
        yield
