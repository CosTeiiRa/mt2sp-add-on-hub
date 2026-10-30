"""Measure package limits using disposable, invented files only.

Reports elapsed time and traced Python allocations, not total process memory or
hardware power-loss guarantees. No installation path or machine identity is output.
"""
import argparse
import gc
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from mt2sp_hub.core.packages import build
from mt2sp_hub.core.validation import MAX_FILE, MAX_FILES, MAX_PACKAGES, MAX_SELECTED_ARCHIVES, MAX_TOTAL, encode
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.manager import Manager, initialize


def sources(profile):
    if profile == 'large':
        return [('e.large', 4, MAX_FILE)]
    if profile == 'files':
        return [('e.f', MAX_FILES, MAX_TOTAL // MAX_FILES)]
    if profile == 'packages':
        return [('e.p' + str(i), MAX_FILES // MAX_PACKAGES, MAX_TOTAL // MAX_FILES)
                for i in range(MAX_PACKAGES)]
    # Leave room for ZIP/manifest overhead inside the selected-archive limit.
    return [('e.cache' + str(i), 4, MAX_FILE - 2048) for i in range(2)]


def create_source(source, ident, count, size):
    (source / 'payload').mkdir(parents=True)
    manifest = {'format_version': 2, 'id': ident, 'version': '1.0.0',
                'name': 'Synthetic size measurement', 'license': 'MIT',
                'requires': {}, 'conflicts': [], 'components': {}}
    for index in range(count):
        kind = 'client' if index % 2 == 0 else 'server'
        name = 'f' + str(index)
        marker = (ident + '/' + name + '\n').encode('ascii')
        chunk = (marker * (65536 // len(marker) + 1))[:65536]
        with (source / 'payload' / name).open('wb') as stream:
            pending = size
            while pending:
                part = chunk[:min(len(chunk), pending)]
                if stream.write(part) != len(part):
                    raise OSError('Incomplete fixture write')
                pending -= len(part)
        component = manifest['components'].setdefault(kind, {
            'api': '>=1.0.0 <2.0.0', 'capabilities': ['fixture.files'], 'files': []})
        component['files'].append({'source': name, 'target': ident + '/' + name})
    (source / 'addon.json').write_bytes(encode(manifest))


def run(profile):
    specs = sources(profile)
    with tempfile.TemporaryDirectory(prefix='hub-measure-') as temporary:
        root = Path(temporary)
        for ident, count, size in specs:
            create_source(root / ident, ident, count, size)
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

        addons = measure('build', lambda: [build(root / ident) for ident, _, _ in specs])
        archive_bytes = sum(len(addon.raw) for addon in addons)
        if archive_bytes > MAX_SELECTED_ARCHIVES:
            raise RuntimeError('Measurement fixture exceeds the archive budget')

        def validate():
            for addon in addons:
                addon.unpack()

        measure('validate', validate)
        if profile == 'cached':
            first = measure('plan_first', lambda: manager.plan(addons[:1]))
            measure('apply_first', lambda: manager.apply(first['plan']))
            disabled = measure('plan_disable', lambda: manager.plan(disable=[specs[0][0]]))
            measure('apply_disable', lambda: manager.apply(disabled['plan']))
        plan = measure('plan_install', lambda: manager.plan(addons[1:] if profile == 'cached' else addons))
        measure('apply_install', lambda: manager.apply(plan['plan']))
        if profile == 'cached':
            try:
                manager.plan(enable=[specs[0][0]])
            except HubError as exc:
                if exc.code != 'selection_limit':
                    raise
            else:
                raise RuntimeError('Combined active-byte limit was not enforced')
        del addons  # Removal uses the installation cache, not the original objects.
        plan = measure('plan_remove', lambda: manager.plan(remove=[ident for ident, _, _ in specs]))
        measure('apply_remove', lambda: manager.apply(plan['plan']))
        tracemalloc.stop()
        if manager.status()['packages'] or manager.status()['recovery_required']:
            raise RuntimeError('Measurement did not finish cleanly')
        report = {'profile': profile, 'python': platform.python_version(), 'platform': sys.platform,
                  'payload_bytes': sum(count * size for _, count, size in specs),
                  'files': sum(count for _, count, _ in specs), 'packages': len(specs),
                  'archive_bytes': archive_bytes,
                  'largest_record_bytes': max(p.stat().st_size for p in manager.store.root.rglob('*.json')),
                  'stages': stages}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('large', 'files', 'packages', 'cached', 'all'), default='large')
    args = parser.parse_args()
    profiles = ('large', 'files', 'packages', 'cached') if args.profile == 'all' else (args.profile,)
    for profile in profiles:
        # Emit each completed profile only after its temporary cleanup succeeds.
        print(json.dumps(run(profile), sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, HubError, RuntimeError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': 'Synthetic measurement failed.'}))
        raise SystemExit(1)
