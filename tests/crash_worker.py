"""Subprocess helper: real process exit while the OS lock is held."""
import os
import sys

from mt2sp_hub.installation.manager import Manager
from storage_faults import write_fault

root, operation, token, stage = sys.argv[1:]


def checkpoint(current):
    if current == stage:
        os._exit(73)


manager = Manager(root, checkpoint=checkpoint)
if operation == 'apply':
    manager.apply(token)
elif operation == 'recover':
    manager.recover()
elif operation in ('apply-write', 'recover-write'):
    fault, relative = stage.split(':', 1)
    with write_fault(manager.root / relative, fault):
        if operation == 'apply-write':
            manager.apply(token)
        else:
            manager.recover()
elif operation == 'lock':
    with manager.locked():
        print('locked', flush=True)
        sys.stdin.readline()
