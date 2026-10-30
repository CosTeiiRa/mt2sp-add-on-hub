"""One OS-owned lock per canonical sandbox; no stale-PID lock deletion."""
from contextlib import contextmanager
import os

from ..errors import HubError


@contextmanager
def exclusive(path):
    with path.open("a+b") as stream:
        # Locking one byte beyond EOF is supported on Windows. No initialization
        # write is needed, so simultaneous first opens do not race on a byte.
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise HubError("installation_busy", "Another process owns the installation lock.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
