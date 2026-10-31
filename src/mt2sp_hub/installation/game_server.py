"""One fixed local Docker adapter for the reviewed protected server layout."""
from __future__ import annotations

import io
import os
import re
import shutil
import tarfile
import time
import uuid

from ..core.validation import MAX_FILE, MAX_FILES, MAX_TOTAL, confined, digest, parse_json, path_set, read_bounded
from ..errors import HubError, require
from .baseline import fingerprint_tree
from .compiler import _run, _cleanup
from .official_build import PROFILE
from .runtime_probe import ObservationError, _endpoint, _same_path

COMPOSE = 'linux-port/docker/docker-compose.yml'
GAME = 'linux-port/docker/game'
OBJECTS = GAME + '/share/locale/poland/quest/'
COMPOSE_SHA = PROFILE['compose_sha256']
IMAGE_LINE = re.compile(rb'(?m)^    image: ([A-Za-z0-9_./:@-]+)\r?$')
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}')
FORMAT = ('{"id":{{json .Id}},"image":{{json .Image}},"state":{{json .State.Status}},'
          '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
          '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
          '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
          '"directory":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},'
          '"files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},'
          '"mounts":{{json .Mounts}}}')
HASH_SCRIPT = '''set -eu
cd /opt/metin2/share/locale/poland/quest
find object -type l -print -quit | grep -q . && exit 21
find object -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
'''
WORLD_SCRIPT = 'set -eu; cat /opt/metin2/var/.world-id; cat /opt/m2spool/world-id'
DB_WORLD_SCRIPT = ('MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb --batch --skip-column-names '
                   '-uroot -e "SELECT world_id FROM player.web_m2p_world WHERE singleton = 1"')


def compose_bytes(raw, image=None):
    """Change only the single reviewed game image line; preserve every other byte."""
    require(isinstance(raw, bytes) and len(raw) <= 128 * 1024, 'server_compose', 'Unsupported Compose input.')
    # The public profile fixes every byte except the game image reference. Other
    # services have image lines too; isolate the known game service block first.
    start = raw.find(b'\n  game:')
    end = raw.find(b'\n  panel:', start)
    require(0 <= start < end, 'server_compose', 'Unsupported game service layout.')
    block = raw[start:end]
    matches = list(IMAGE_LINE.finditer(block))
    require(len(matches) == 1, 'server_compose', 'Game service must have one image reference.')
    match = matches[0]
    before, after = start + match.start(1), start + match.end(1)
    normalized = raw[:before] + b'metin2/game:mt2009' + raw[after:]
    require(digest(normalized) == COMPOSE_SHA, 'server_compose', 'Compose differs from the reviewed official layout.')
    if image is None:
        return match[1].decode('ascii')
    require(isinstance(image, str) and re.fullmatch(r'mt2sp-hub-build:[0-9a-f]{32}', image),
            'server_image', 'Invalid prepared Hub image reference.')
    return raw[:before] + image.encode('ascii') + raw[after:]


def parse_inventory(raw):
    result = {}
    for line in raw.decode('ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (object/[A-Za-z0-9_./-]+)', line)
        require(match is not None and match[2] not in result, 'server_inventory', 'Invalid quest inventory response.')
        result[match[2]] = match[1]
    require(0 < len(result) <= 32768, 'server_inventory', 'Quest inventory exceeds its limit or is empty.')
    path_set(result)
    return result


class Server:
    def __init__(self, binding):
        self.binding = binding
        self.directory = binding.world / 'linux-port/docker'
        self.compose = confined(binding.world, COMPOSE)
        self.environment_file = confined(binding.world, 'linux-port/docker/.env')
        compose_bytes(read_bounded(self.compose, 128 * 1024))
        read_bounded(self.environment_file, 64 * 1024)
        self.executable = shutil.which('docker.exe' if os.name == 'nt' else 'docker')
        require(self.executable is not None, 'docker_missing', 'Docker Desktop is required.')
        self.environment = dict(os.environ)
        try:
            endpoint = _endpoint(self.executable, self.environment)
        except ObservationError:
            raise HubError('docker_endpoint', 'Select an available local Docker Desktop endpoint.') from None
        for key in list(self.environment):
            if key.startswith(('DOCKER_', 'COMPOSE_', 'M2_', 'PLAYERBOT_')):
                self.environment.pop(key)
        self.prefix = ['--host', endpoint]

    def command(self, args, *, incoming=None, timeout=15, limit=8 * 1024 * 1024):
        try:
            code, output = _run(self.executable, [*self.prefix, *args], self.environment,
                                input_bytes=incoming, timeout=timeout, limit=limit)
        except HubError:
            raise HubError('server_command', 'The local server command did not finish; retain the operation journal.') from None
        require(code == 0, 'server_command', 'The local server command failed; retain the operation journal.')
        return output

    def verify_image(self, tag, image):
        require(isinstance(tag, str) and re.fullmatch(r'mt2sp-hub-build:[0-9a-f]{32}', tag)
                and isinstance(image, str) and IMAGE_ID.fullmatch(image), 'server_image', 'Invalid retained image reference.')
        observed = self.command(['image', 'inspect', '--format', '{{.Id}}', tag], limit=1024).decode().strip()
        require(observed == image, 'server_image', 'A retained deployment image is missing or changed.')

    def discover(self, *, running=True, allow_missing=False):
        raw = self.command(['container', 'ls', '--all', '--no-trunc', '--filter',
                            'label=com.docker.compose.service=game', '--format', '{{.ID}}'], limit=65536)
        ids = raw.decode('ascii').splitlines()
        require(len(ids) <= 32 and all(re.fullmatch(r'[0-9a-f]{64}', v) for v in ids),
                'server_identity', 'Unexpected Docker container inventory.')
        records = [] if not ids else [parse_json(line.encode(), 65536) for line in
                    self.command(['container', 'inspect', '--format', FORMAT, *ids], limit=65536).decode().splitlines()]
        matches = [r for r in records if _same_path(r.get('directory'), self.directory)]
        if not matches and not running and allow_missing:
            return None
        require(len(matches) == 1, 'server_identity', 'Exactly one server must belong to the selected folder.')
        record = matches[0]
        require(_same_path(record.get('files'), self.compose) and record.get('service') == 'game'
                and isinstance(record.get('project'), str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}', record['project'])
                and IMAGE_ID.fullmatch(record.get('image', '')),
                'server_identity', 'Server must use the reviewed single Compose file and a pinned image.')
        if running:
            require(record['state'] == 'running' and record['health'] == 'healthy',
                    'server_not_ready', 'Start the selected server and wait until it is healthy.')
        return record

    def retain_image(self, image):
        require(IMAGE_ID.fullmatch(image), 'server_image', 'An immutable local image is required.')
        tag = 'mt2sp-hub-build:' + uuid.uuid4().hex
        self.command(['image', 'tag', image, tag], limit=1024)
        require(self.command(['image', 'inspect', '--format', '{{.Id}}', tag], limit=1024).decode().strip() == image,
                'server_image', 'Retained image did not verify.')
        return tag

    def verify_world(self, expected):
        """Works with the game stopped or absent; never starts a world to identify it."""
        project = expected['project']
        require(re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}', project), 'world_identity', 'Invalid world project.')
        ids = self.command(['container', 'ls', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
                            '--filter', 'label=com.docker.compose.service=mariadb', '--format', '{{.ID}}'], limit=65536).decode().splitlines()
        require(len(ids) == 1 and re.fullmatch(r'[0-9a-f]{64}', ids[0]), 'world_identity', 'The selected database is unavailable.')
        db = parse_json(self.command(['container', 'inspect', '--format', FORMAT, ids[0]], limit=65536), 65536)
        require(_same_path(db.get('directory'), self.directory) and _same_path(db.get('files'), self.compose)
                and db.get('project') == project and db.get('service') == 'mariadb',
                'world_identity', 'Database identity changed.')
        mounts = [m for m in db['mounts'] if m.get('Destination') == '/var/lib/mysql']
        require(len(mounts) == 1 and mounts[0].get('Type') == 'volume' and mounts[0].get('RW') is True
                and mounts[0].get('Name') == expected['volumes']['/var/lib/mysql'],
                'world_identity', 'Database storage changed.')
        world = self.command(['exec', ids[0], '/bin/sh', '-c', DB_WORLD_SCRIPT], limit=1024).decode().strip()
        require(world == expected['world'], 'world_identity', 'Persistent world changed; preserve the operation journal.')
        descriptions = parse_json(self.command(['volume', 'inspect', *expected['volumes'].values()], limit=65536), 65536)
        volume_kinds = {'/var/lib/mysql': 'db-data', '/opt/metin2/var': 'game-var', '/opt/m2spool': 'rates-spool'}
        labels = {name: volume_kinds[path] for path, name in expected['volumes'].items()}
        require(len(descriptions) == 3 and {v.get('Name') for v in descriptions} == set(expected['volumes'].values())
                and all(v.get('Driver') == 'local' and not v.get('Options')
                        and v.get('Labels', {}).get('com.docker.compose.project') == project
                        and v['Labels'].get('com.docker.compose.volume') == labels[v['Name']] for v in descriptions),
                'world_identity', 'World storage ownership changed.')
        game = self.discover(running=False, allow_missing=True)
        if game:
            actual = {m['Destination']: m.get('Name') for m in game['mounts']
                      if m.get('Destination') in ('/opt/metin2/var', '/opt/m2spool')
                      and m.get('Type') == 'volume' and m.get('RW') is True}
            require(game['project'] == project and actual == {p: n for p, n in expected['volumes'].items() if p != '/var/lib/mysql'},
                    'world_identity', 'Game storage changed.')
        return game

    def inventory(self, container):
        require(re.fullmatch(r'[0-9a-f]{64}', container), 'server_identity', 'Invalid server identity.')
        return parse_inventory(self.command(['exec', container, '/bin/sh', '-c', HASH_SCRIPT]))

    def image_inventory(self, image):
        require(IMAGE_ID.fullmatch(image), 'server_image', 'An immutable local image is required.')
        # No inherited game data volume, network, host directory or entrypoint.
        token = uuid.uuid4().hex
        label, name_prefix = 'org.mt2sp.hub.inspect', 'mt2sp-hub-inspect-'
        try:
            return parse_inventory(self.command(['run', '--rm', '--pull=never', '--network=none', '--read-only',
                     '--name', name_prefix + token, '--label', label + '=' + token,
                     '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=32', '--memory=128m',
                     '--tmpfs', '/opt/metin2/var:rw,noexec,nosuid,nodev,size=1m', '--entrypoint', '/usr/bin/timeout',
                     image, '--signal=KILL', '30', '/bin/sh', '-c', HASH_SCRIPT], timeout=45))
        finally:
            _cleanup(self.executable, self.prefix, self.environment, token, name_prefix=name_prefix, label=label)

    def snapshot(self):
        record = self.discover()
        project = record['project']
        raw = self.command(['container', 'ls', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
                            '--filter', 'label=com.docker.compose.service=mariadb', '--format', '{{.ID}}'], limit=65536)
        ids = raw.decode('ascii').splitlines()
        require(len(ids) == 1 and re.fullmatch(r'[0-9a-f]{64}', ids[0]), 'world_identity', 'One database must belong to this world.')
        db = parse_json(self.command(['container', 'inspect', '--format', FORMAT, ids[0]], limit=65536), 65536)
        require(_same_path(db.get('directory'), self.directory) and _same_path(db.get('files'), self.compose)
                and db.get('project') == project and db.get('service') == 'mariadb',
                'world_identity', 'Database folder binding could not be verified.')
        wanted = {'/opt/metin2/var': 'game-var', '/opt/m2spool': 'rates-spool', '/var/lib/mysql': 'db-data'}
        volumes = {}
        for item in [*record['mounts'], *db['mounts']]:
            destination = item.get('Destination')
            if destination not in wanted:
                continue
            require(item.get('Type') == 'volume' and destination not in volumes
                    and isinstance(item.get('Name'), str) and item.get('RW') is True,
                    'world_identity', 'World storage must use distinct local named volumes.')
            volumes[destination] = item['Name']
        require(set(volumes) == set(wanted) and len(set(volumes.values())) == 3,
                'world_identity', 'World volume bindings are incomplete or shared.')
        descriptions = parse_json(self.command(['volume', 'inspect', *volumes.values()], limit=65536), 65536)
        require(len(descriptions) == 3 and {v.get('Name') for v in descriptions} == set(volumes.values()),
                'world_identity', 'World volume inventory is incomplete.')
        for item in descriptions:
            destination = next((p for p, name in volumes.items() if name == item.get('Name')), None)
            require(destination is not None and item.get('Driver') == 'local' and not item.get('Options')
                    and item.get('Labels', {}).get('com.docker.compose.project') == project
                    and item['Labels'].get('com.docker.compose.volume') == wanted[destination],
                    'world_identity', 'World volume ownership could not be verified.')
        world = self.command(['exec', db['id'], '/bin/sh', '-c', DB_WORLD_SCRIPT], limit=1024).decode().strip()
        copied = self.command(['exec', record['id'], '/bin/sh', '-c', WORLD_SCRIPT], limit=1024).decode().splitlines()
        require(re.fullmatch(r'[0-9a-f]{32}', world) and copied == [world, world],
                'world_identity', 'Database, game state and spool must identify the same persistent world.')
        engine = self.command(['exec', record['id'], 'sha256sum', '/opt/metin2/share/bin/game'], limit=1024).decode().split()[0]
        require(engine == PROFILE['files']['server'][GAME + '/bin/game']['sha256'],
                'server_build', 'Running server engine differs from the reviewed build.')
        return {'world': world, 'volumes': volumes, 'project': project, 'image': record['image'],
                'container': record['id'], 'quests': self.inventory(record['id'])}

    def _compose(self, project, args):
        require(re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}', project), 'server_identity', 'Invalid project identity.')
        compose_bytes(read_bounded(self.compose, 128 * 1024))
        return self.command(['compose', '--project-directory', str(self.directory), '--env-file', str(self.environment_file),
                             '--project-name', project, '--file', str(self.compose), *args], timeout=180)

    def stop(self, project):
        record = self.discover(running=False)
        require(record['project'] == project, 'world_identity', 'Selected server project changed.')
        self._compose(project, ['stop', '--timeout', '60', 'game'])
        require(self.discover(running=False)['state'] == 'exited', 'server_stop', 'Server did not stop cleanly.')

    def start(self, expected, *, timeout=180):
        self._compose(expected['project'], ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'game'])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.discover(running=False)
            if record['state'] == 'running' and record['health'] == 'healthy':
                self.verify(expected)
                return
            time.sleep(1)
        raise HubError('server_start', 'Server readiness timed out; recovery is required.')

    def verify(self, expected):
        observed = self.snapshot()
        require(all(observed[key] == expected[key] for key in ('world', 'volumes', 'project', 'image', 'quests')),
                'server_revision', 'Running server does not match the recorded world and quest revision.')
        return observed

    def build_baseline(self):
        root = confined(self.binding.world, GAME)
        expected = PROFILE['server_trees'][GAME]
        require(fingerprint_tree(root) == expected, 'server_baseline', 'Server source differs from the official baseline.')
        tag = 'mt2sp-hub-build:' + uuid.uuid4().hex
        output = self.command(['build', '--quiet', '--pull=false', '--tag', tag, str(root)], timeout=900, limit=65536)
        image = output.decode().strip()
        require(IMAGE_ID.fullmatch(image) and fingerprint_tree(root) == expected,
                'server_build', 'Official build failed verification or its inputs changed.')
        return {'tag': tag, 'image': image, 'quests': self.image_inventory(image)}

    def build_selection(self, baseline, artifacts):
        require(IMAGE_ID.fullmatch(baseline['image']) and re.fullmatch(r'mt2sp-hub-build:[0-9a-f]{32}', baseline['tag']),
                'server_image', 'Invalid retained baseline image.')
        self.verify_image(baseline['tag'], baseline['image'])
        require(isinstance(artifacts, dict) and len(artifacts) <= MAX_FILES
                and all(isinstance(p, str) and re.fullmatch(r'object/[A-Za-z0-9_./-]+', p)
                        and isinstance(raw, bytes) and 0 < len(raw) <= MAX_FILE for p, raw in artifacts.items())
                and sum(map(len, artifacts.values())) <= MAX_TOTAL,
                'quest_limit', 'Prepared quest artifacts exceed their bounds.')
        require(not (set(artifacts) & set(baseline['quests'])), 'quest_collision', 'Selected quest artifacts overlap official files.')
        path_set(artifacts)
        desired = {**baseline['quests'], **{p: digest(raw) for p, raw in artifacts.items()}}
        # Dockerfile FROM needs a repository reference, not the local image's
        # config ID. Use our reserved tag, checking its exact ID on both sides
        # of the build; the resulting deployment is recorded by immutable ID.
        dockerfile = ('FROM ' + baseline['tag'] + '\n').encode()
        if artifacts:
            dockerfile += b'COPY object/ /opt/metin2/share/locale/poland/quest/object/\n'
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, raw in [('Dockerfile', dockerfile), *sorted(artifacts.items())]:
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(raw), 0o644
                archive.addfile(member, io.BytesIO(raw))
        tag = 'mt2sp-hub-build:' + uuid.uuid4().hex
        output = self.command(['build', '--quiet', '--pull=false', '--tag', tag, '-'], incoming=stream.getvalue(),
                              timeout=180, limit=65536)
        image = output.decode().strip()
        self.verify_image(baseline['tag'], baseline['image'])
        require(IMAGE_ID.fullmatch(image) and self.image_inventory(image) == desired,
                'server_build', 'Prepared server image has an unexpected quest inventory.')
        return {'tag': tag, 'image': image, 'quests': desired}
