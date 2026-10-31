import os
from pathlib import Path
import sys
from unittest.mock import patch

from game_fixture import environment
from mt2sp_hub.installation.game_manager import GameManager, attach
from mt2sp_hub.installation import storage
from storage_faults import write_fault

root, operation, token, step = sys.argv[1:]
def checkpoint(observed):
    if observed == step:
        os._exit(73)

with environment(Path(root)):
    if operation == 'attach':
        attach(root, checkpoint)
    else:
        manager = GameManager(root, checkpoint)
        if operation == 'apply-write':
            fault, relative = step.split(':', 1)
            with write_fault(Path(root) / relative, fault):
                with patch('mt2sp_hub.installation.game_manager.atomic_write', storage.atomic_write):
                    manager.apply(token)
        elif operation == 'apply':
            manager.apply(token)
        else:
            manager.recover()
