"""Subprocess helper: real process exit while the OS lock is held."""
import os
import sys

from mt2sp_hub.installation.manager import Manager

root, operation, token, stage = sys.argv[1:]


def checkpoint(current):
    if current == stage:
        os._exit(73)


manager = Manager(root, checkpoint=checkpoint)
if operation == 'apply':
    manager.apply(token)
elif operation == 'recover':
    manager.recover()
elif operation == 'lock':
    with manager.locked():
        print('locked', flush=True)
        sys.stdin.readline()
