"""Reproduce the built-in reference from separately obtained official archives.

No download, extraction, game code execution or profile registration occurs.
Output contains only public archive metadata and fingerprints, never game bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mt2sp_hub.core.validation import digest, path_set
from mt2sp_hub.errors import require
from mt2sp_hub.installation.baseline import tree_digest
from mt2sp_hub.installation.official_build import PROFILE


def open_archive(path, pin):
    info = path.stat()
    require(info.st_size == pin['bytes'], 'archive_size', 'Official archive size differs from the reviewed pin.')
    # Use the same descriptor for validation and ZIP reads, so a replaced path
    # cannot substitute another archive after validation.
    stream = path.open('rb')
    try:
        hashed, count = hashlib.sha256(), 0
        while chunk := stream.read(min(1024 * 1024, pin['bytes'] - count + 1)):
            count += len(chunk)
            require(count <= pin['bytes'], 'archive_size', 'Official archive size differs from the reviewed pin.')
            hashed.update(chunk)
        require(count == pin['bytes'] and hashed.hexdigest() == pin['sha256'],
                'archive_hash', 'Official archive checksum differs from the reviewed pin.')
        stream.seek(0)
        archive = zipfile.ZipFile(stream)
        entries = archive.infolist()
        require(len(entries) <= 65536 and len({i.filename for i in entries}) == len(entries),
                'archive_entries', 'Official archive has an invalid entry inventory.')
        return archive, stream
    except BaseException:
        stream.close()
        raise


def inventory(archive, prefix, selected=None):
    result = {}
    for info in archive.infolist():
        if info.filename.startswith(prefix) and not info.is_dir():
            relative = info.filename[len(prefix):]
            if selected is not None and not selected(relative):
                continue
            require(0 <= info.file_size <= 64 * 1024 * 1024 and not info.flag_bits & 1,
                    'archive_member', 'Unsupported official baseline member.')
            with archive.open(info) as stream:
                raw = stream.read(info.file_size + 1)
            require(len(raw) == info.file_size, 'archive_member', 'Official archive member is truncated.')
            result[relative] = {'bytes': len(raw), 'sha256': digest(raw)}
    path_set(result)
    return result


def derive(archives):
    server = inventory(archives['base'], 'Metin2 Singleplayer/Serwer/linux-port/docker/game/')
    server.update(inventory(archives['server'], 'linux-port/docker/game/'))
    # Only the root pack, its local configuration and the shipped native runtime
    # inputs are used by this first client adapter. Other game packs are outside
    # this check; matching these inputs is not connected-gameplay certification.
    files = inventory(archives['client'], '', lambda p:
                      p in ('pack/root.index', 'pack/root.data') or '/' not in p and p.endswith('.dll'))
    supplement = inventory(archives['supplement'], '', lambda p: p == 'pack/root.json')
    files['pack/root.json'] = supplement['pack/root.json']
    executable = PROFILE['sources']['executable']
    files['metin2client.exe'] = {key: executable[key] for key in ('bytes', 'sha256')}
    inputs = ('Dockerfile', 'bin/qc', 'bin/game', 'bin/db', 'scripts/entrypoint.sh',
              'share/locale/poland/quest/quest_functions')
    prefix = 'linux-port/docker/game/'
    compose = inventory(archives['server'], '', lambda p: p == 'linux-port/docker/docker-compose.yml')
    return {**{key: PROFILE[key] for key in ('id', 'client_version', 'server_version', 'sources')},
            'compose_sha256': compose['linux-port/docker/docker-compose.yml']['sha256'],
            'files': {'client': dict(sorted(files.items())),
                      'server': {prefix + p: server[p] for p in inputs}},
            'server_trees': {prefix.rstrip('/'): tree_digest(server)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'client', 'supplement', 'server'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    opened = []
    try:
        archives = {}
        for name in ('base', 'client', 'supplement', 'server'):
            archive, stream = open_archive(getattr(args, name), PROFILE['sources'][name])
            opened.append((archive, stream))
            archives[name] = archive
        candidate = derive(archives)
        require(candidate == PROFILE, 'profile_difference', 'Reviewed profile differs from the pinned official inputs.')
        print(json.dumps({'profile': PROFILE['id'], 'outcome': 'reproduced',
                          'client_inputs': len(candidate['files']['client']),
                          'server_tree': next(iter(candidate['server_trees'].values()))}, sort_keys=True))
    finally:
        for archive, stream in opened:
            archive.close()
            stream.close()


if __name__ == '__main__':
    main()
