"""Offline checks against reviewed official inputs, not installation permission."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from ..core.validation import confined, digest, encode, path_set
from ..errors import HubError, require
from .official_build import PROFILE

MAX_INPUT = 64 * 1024 * 1024
MAX_TREE_BYTES = 128 * 1024 * 1024
MAX_TREE_FILES = 32768
MAX_TREE_ENTRIES = 65536


def _stamp(info):
    # Windows ctime semantics differ between Python versions and stat APIs.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def fingerprint_file(path, limit=MAX_INPUT):
    """Stream bounded inputs and detect replacement/modification during the read."""
    before = path.lstat()
    require(not stat.S_ISLNK(before.st_mode)
            and not getattr(before, 'st_file_attributes', 0) & 0x400,
            'path_link', 'Links and reparse points are unsupported.')
    require(stat.S_ISREG(before.st_mode), 'file_type', 'A regular file is required.')
    require(before.st_size <= limit, 'file_limit', 'Build input exceeds its limit.')
    result, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        require(_stamp(before) == _stamp(os.fstat(stream.fileno())),
                'baseline_changed', 'Build inputs changed during inspection; retry while the launcher is idle.')
        while chunk := stream.read(min(1024 * 1024, limit - size + 1)):
            size += len(chunk)
            require(size <= limit, 'file_limit', 'Build input exceeds its limit.')
            result.update(chunk)
        require(_stamp(before) == _stamp(os.fstat(stream.fileno())),
                'baseline_changed', 'Build inputs changed during inspection; retry while the launcher is idle.')
    require(_stamp(before) == _stamp(path.lstat()) and size == before.st_size,
            'baseline_changed', 'Build inputs changed during inspection; retry while the launcher is idle.')
    return {'bytes': size, 'sha256': result.hexdigest()}


def tree_digest(files):
    """Canonical path/length/digest inventory shared with the maintainer review tool."""
    path_set(files)
    return {'files': len(files), 'bytes': sum(row['bytes'] for row in files.values()),
            'sha256': digest(encode(files))}


def _inventory(root):
    pending, files, entries = [(root, 0)], {}, 0
    while pending:
        folder, depth = pending.pop()
        require(depth <= 32, 'baseline_limit', 'Build tree exceeds its depth limit.')
        with os.scandir(folder) as children:
            for child in children:
                entries += 1
                require(entries <= MAX_TREE_ENTRIES, 'baseline_limit', 'Build tree has too many entries.')
                path = Path(child.path)
                # DirEntry.stat on Windows may return zero device/inode values.
                info = path.lstat()
                require(not stat.S_ISLNK(info.st_mode)
                        and not getattr(info, 'st_file_attributes', 0) & 0x400,
                        'path_link', 'Links and reparse points are unsupported.')
                if stat.S_ISDIR(info.st_mode):
                    pending.append((path, depth + 1))
                else:
                    require(stat.S_ISREG(info.st_mode), 'file_type', 'A regular file is required.')
                    files[path.relative_to(root).as_posix()] = _stamp(info)
                    require(len(files) <= MAX_TREE_FILES, 'baseline_limit', 'Build tree has too many files.')
    path_set(files)
    return files


def fingerprint_tree(root, *, excluded=frozenset()):
    # Callers first confine the tree root. Empty directories are not build inputs.
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
            'path_link', 'Build tree must be an ordinary directory.')
    before = _inventory(root)
    total, files = 0, {}
    for relative in sorted(before):
        if relative in excluded:
            continue  # Only coordinator-owned, separately verified outputs may be excluded.
        path = confined(root, relative)
        require(_stamp(path.lstat()) == before[relative], 'baseline_changed',
                'Build inputs changed during inspection; retry while the launcher is idle.')
        row = fingerprint_file(path, min(MAX_INPUT, MAX_TREE_BYTES - total))
        total += row['bytes']
        files[relative] = row
    require(before == _inventory(root), 'baseline_changed',
            'Build inputs changed during inspection; retry while the launcher is idle.')
    return tree_digest(files)


def _check(root, relative, expected, tree=False):
    try:
        path = confined(root, relative)
        actual = fingerprint_tree(path) if tree else fingerprint_file(path)
        return 'match' if actual == expected else 'different'
    except FileNotFoundError:
        return 'missing'
    except HubError as exc:
        return {'path_link': 'unsafe_path', 'baseline_changed': 'changed_during_check',
                'file_limit': 'limit_exceeded', 'baseline_limit': 'limit_exceeded'}.get(exc.code, 'invalid')
    except OSError:
        return 'unreadable'


def check_build(binding, client_version, server_version):
    """Sanitized snapshot. Unknown labels never register a new trusted baseline."""
    report = {'profile': None, 'status': 'unknown_build', 'client': {}, 'server': {},
              'activation_supported': False, 'snapshot_only': True}
    if (client_version, server_version) != (PROFILE['client_version'], PROFILE['server_version']):
        return report
    report['profile'] = PROFILE['id']
    for side in ('client', 'server'):
        root = binding.client if side == 'client' else binding.world
        for relative, expected in PROFILE['files'][side].items():
            report[side][relative] = _check(root, relative, expected)
    for relative, expected in PROFILE['server_trees'].items():
        report['server'][relative + '/'] = _check(binding.world, relative, expected, tree=True)
    report['status'] = ('reference_match' if all(value == 'match' for side in ('client', 'server')
                                               for value in report[side].values()) else 'reference_mismatch')
    return report
