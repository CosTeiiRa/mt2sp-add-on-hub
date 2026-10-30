"""Fixed client-pack file steps for the future game coordinator.

These internal steps do not authorize installation. The caller must hold both
target locks, verify the build/ownership and closed client, and durably journal
the returned record before write(). Only the coordinator commits installation
state. A committed operation uses verify(); an uncommitted one restores before.
"""
from __future__ import annotations

import os

from ..core.validation import SHA, confined, digest, read_bounded
from ..errors import require
from .baseline import fingerprint_file
from . import storage

PATHS = ('pack/root.index', 'pack/root.data')
MAX_PAIR = 64 * 1024 * 1024


def _store(binding, store):
    require(store.root == binding.world / '.mt2sp-hub', 'client_store',
            'Client pack objects must use the selected world coordinator store.')
    confined(binding.world, '.mt2sp-hub')


def prepare(binding, store, outputs, expected):
    """Cache both before/after files, refusing stale inputs and oversized output.

    Outputs must already have passed the pack composer's logical-file checks.
    This layer handles bytes, not pack decoding or module/gameplay validation.
    """
    _store(binding, store)
    require(isinstance(outputs, dict) and set(outputs) == set(PATHS)
            and all(isinstance(raw, bytes) and raw for raw in outputs.values())
            and sum(map(len, outputs.values())) <= MAX_PAIR,
            'client_pack_limit', 'A complete bounded client pack pair is required.')
    require(isinstance(expected, dict) and set(expected) == set(PATHS)
            and all(isinstance(key, str) and SHA.fullmatch(key) for key in expected.values()),
            'client_pack_record', 'Expected client pack fingerprints are required.')
    originals = {}
    total = 0
    for relative in PATHS:
        raw = read_bounded(confined(binding.client, relative), MAX_PAIR - total)
        total += len(raw)
        require(raw and digest(raw) == expected[relative], 'plan_stale',
                'Client pack changed; review a new operation.')
        originals[relative] = raw
    require(all(fingerprint_file(confined(binding.client, p))['sha256'] == expected[p] for p in PATHS),
            'plan_stale', 'Client pack changed while preparing the operation.')
    return {'schema': 1, 'kind': 'client-pack-files',
            'client_root': os.path.normcase(str(binding.client)),
            'files': {p: {'before': store.put(originals[p]), 'after': store.put(outputs[p])} for p in PATHS}}


def _validate(binding, store, record):
    _store(binding, store)
    require(isinstance(record, dict) and set(record) == {'schema', 'kind', 'client_root', 'files'}
            and type(record['schema']) is int and record['schema'] == 1
            and record['kind'] == 'client-pack-files'
            and record['client_root'] == os.path.normcase(str(binding.client))
            and isinstance(record['files'], dict) and set(record['files']) == set(PATHS),
            'client_pack_record', 'Invalid or relocated client pack operation.')
    totals = {'before': 0, 'after': 0}
    for row in record['files'].values():
        require(isinstance(row, dict) and set(row) == {'before', 'after'},
                'client_pack_record', 'Invalid client pack operation.')
        for phase in totals:
            raw = store.get(row[phase])  # Verify every backup/output before writing either file.
            totals[phase] += len(raw)
            require(raw and totals[phase] <= MAX_PAIR, 'client_pack_limit', 'Client pack pair exceeds its limit.')


def verify(binding, store, record, phase='after'):
    require(phase in ('before', 'after'), 'client_pack_record', 'Invalid client pack phase.')
    _validate(binding, store, record)
    require(all(fingerprint_file(confined(binding.client, p))['sha256'] == record['files'][p][phase]
                for p in PATHS), 'client_pack_drift', 'Client pack differs from the recorded revision.')


def write(binding, store, record, phase='after', *, checkpoint=None):
    """Idempotent journal step; restoring uses phase='before'. Never clears state."""
    require(phase in ('before', 'after'), 'client_pack_record', 'Invalid client pack phase.')
    _validate(binding, store, record)
    checkpoint = checkpoint or (lambda path: None)
    # Check the complete pair before changing either member. A foreign edit,
    # official update, missing file or corrupt backup prevents all restoration.
    for p in PATHS:
        require(fingerprint_file(confined(binding.client, p))['sha256'] in record['files'][p].values(),
                'client_pack_drift', 'External client pack changes prevent automatic replacement.')
    order = reversed(PATHS) if phase == 'before' else PATHS
    for p in order:
        row = record['files'][p]
        target = confined(binding.client, p)
        observed = fingerprint_file(target)['sha256']
        require(observed in row.values(), 'client_pack_drift', 'Client pack changed during replacement.')
        if observed != row[phase]:
            storage.atomic_write(target, store.get(row[phase]))
            require(fingerprint_file(confined(binding.client, p))['sha256'] == row[phase],
                    'client_pack_drift', 'Client pack replacement verification failed.')
            checkpoint(p)
    verify(binding, store, record, phase)
