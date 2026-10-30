"""Measure the 64 MiB package lifecycle using disposable, invented files only.

Reports elapsed time and traced Python allocations, not total process memory or
hardware power-loss guarantees. No installation path or machine identity is output.
"""
import gc
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from mt2sp_hub.core.packages import build
from mt2sp_hub.core.validation import MAX_FILE, MAX_TOTAL, encode
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.manager import Manager, initialize


def main():
    with tempfile.TemporaryDirectory(prefix='hub-measure-') as temporary:
        root = Path(temporary)
        source = root / 'source'
        (source / 'payload').mkdir(parents=True)
        manifest = {'format_version': 2, 'id': 'example.measure', 'version': '1.0.0',
                    'name': 'Synthetic size measurement', 'license': 'MIT',
                    'requires': {}, 'conflicts': [], 'components': {}}
        remaining, index = MAX_TOTAL, 0
        while remaining:
            kind = 'client' if index % 2 == 0 else 'server'
            name = 'file' + str(index) + '.bin'
            size = min(remaining, MAX_FILE)
            chunk = bytes([65 + index % 26]) * (64 * 1024)
            with (source / 'payload' / name).open('wb') as stream:
                pending = size
                while pending:
                    part = chunk[:min(len(chunk), pending)]
                    stream.write(part)
                    pending -= len(part)
            component = manifest['components'].setdefault(kind, {
                'api': '>=1.0.0 <2.0.0', 'capabilities': ['fixture.files'], 'files': []})
            component['files'].append({'source': name, 'target': 'example.measure/' + name})
            remaining -= size
            index += 1
        (source / 'addon.json').write_bytes(encode(manifest))
        initialize(root / 'sandbox')
        manager = Manager(root / 'sandbox')
        stages = []
        tracemalloc.start()

        def measure(name, operation):
            gc.collect()
            tracemalloc.reset_peak()
            start = time.perf_counter()
            result = operation()
            _, peak = tracemalloc.get_traced_memory()
            stages.append({'stage': name, 'seconds': round(time.perf_counter() - start, 3),
                           'peak_traced_mib': round(peak / 1024**2, 2)})
            return result

        addon = measure('build', lambda: build(source))
        archive_bytes = len(addon.raw)
        measure('validate', addon.unpack)
        plan = measure('plan_install', lambda: manager.plan([addon]))
        measure('apply_install', lambda: manager.apply(plan['plan']))
        del addon  # Removal uses the installation cache, not the original object.
        plan = measure('plan_remove', lambda: manager.plan(remove=['example.measure']))
        measure('apply_remove', lambda: manager.apply(plan['plan']))
        tracemalloc.stop()
        if manager.status()['packages'] or manager.status()['recovery_required']:
            raise RuntimeError('Measurement did not finish cleanly')
        report = {'python': platform.python_version(), 'platform': sys.platform,
                  'payload_bytes': MAX_TOTAL, 'files': index, 'archive_bytes': archive_bytes,
                  'stages': stages}
    # Emit only after temporary-directory cleanup succeeds.
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, HubError, RuntimeError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': 'Synthetic measurement failed.'}))
        raise SystemExit(1)
