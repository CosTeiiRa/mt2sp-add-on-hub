"""Create an original, non-executable conformance package source directory."""
import argparse
from pathlib import Path

from mt2sp_hub.core.validation import digest, encode

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path)
parser.add_argument('--kind', choices=['client', 'server', 'combined'], default='combined')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
(args.output / 'payload').mkdir()
manifest = {'format_version': 2, 'id': 'example.sandbox', 'version': '1.0.0',
            'name': 'Synthetic conformance example', 'license': 'MIT',
            'requires': {}, 'conflicts': [], 'components': {}}
for kind in (['client', 'server'] if args.kind == 'combined' else [args.kind]):
    raw = ('Original synthetic ' + kind + ' content.\n').encode('ascii')
    source = kind + '.txt'
    (args.output / 'payload' / source).write_bytes(raw)
    manifest['components'][kind] = {
        'api': '>=1.0.0 <2.0.0', 'capabilities': ['fixture.files'],
        'files': [{'source': source, 'target': 'example.sandbox/message.txt', 'sha256': digest(raw)}]}
(args.output / 'addon.json').write_bytes(encode(manifest))
print('Created synthetic package source; no game content or executable payload included.')
