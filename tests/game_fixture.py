"""Invented game bytes and a persistent fake server for coordinator fault tests."""
from contextlib import contextmanager, ExitStack
import copy
import json
from pathlib import Path
import struct
import uuid
from unittest.mock import patch

from mt2sp_hub.authoring import create
from mt2sp_hub.core.packages import build
from mt2sp_hub.core.validation import digest, encode
from mt2sp_hub.errors import require
from mt2sp_hub.installation.baseline import fingerprint_file, fingerprint_tree
from mt2sp_hub.installation.client_files import PATHS
from mt2sp_hub.installation.game_server import GAME, COMPOSE, OBJECTS, compose_bytes
from mt2sp_hub.installation.pack_codec import EterPack
from mt2sp_hub.installation.probe import Binding

COMPOSE_BYTES = b'services:\n  game:\n    image: metin2/game:mt2009\n  panel:\n    image: invented/panel\n'
CONFIG = {'eter_pack_index_key': [1, 2, 3, 4], 'eter_pack_data_key': [5, 6, 7, 8]}


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def initialize(root):
    binding = Binding(root / 'Serwer', root / 'Klient')
    pair = EterPack(struct.pack('<4sII', b'EPKD', 2, 0), b'', CONFIG).build(
        {'game.py': b'class GameWindow(object):\n    pass\n', 'untouched.txt': b'original'})
    client = {**dict(zip(PATHS, pair)), 'pack/root.json': encode(CONFIG), 'metin2client.exe': b'invented client'}
    server = {GAME + '/Dockerfile': b'FROM scratch\n', GAME + '/bin/game': b'invented server',
              GAME + '/bin/qc': b'invented compiler', OBJECTS + 'quest_functions': b'chat\npc.setqf\n',
              OBJECTS + 'object/state/stock': b'invented stock quest'}
    for p, raw in client.items():
        write(binding.client / p, raw)
    for p, raw in server.items():
        write(binding.world / p, raw)
    write(binding.client / 'client.version', b'2.0.3')
    write(binding.world / 'VERSION', b'2.2.3')
    write(binding.world / COMPOSE, COMPOSE_BYTES)
    write(binding.world / 'linux-port/docker/.env', b'INVENTED_TEST_SETTING=1\n')
    profile = {'id': 'invented-2.2.3', 'client_version': '2.0.3', 'server_version': '2.2.3',
               'files': {'client': {p: fingerprint_file(binding.client / p) for p in client},
                         'server': {p: fingerprint_file(binding.world / p) for p in server}},
               'server_trees': {GAME: fingerprint_tree(binding.world / GAME)}}
    write(root / 'fixture-profile.json', encode(profile))
    image = 'sha256:' + digest(b'official fixture image')
    quests = {'object/state/stock': digest(b'invented stock quest')}
    observed = {'world': 'a' * 32, 'project': 'hub-fixture', 'container': 'b' * 64, 'image': image,
                'quests': quests, 'volumes': {'/var/lib/mysql': 'fixture-db', '/opt/metin2/var': 'fixture-game',
                                             '/opt/m2spool': 'fixture-spool'}}
    write(root / 'fixture-runtime.json', encode({'observed': observed, 'running': True,
          'tags': {'metin2/game:mt2009': image}, 'images': {image: quests}, 'stops': 0, 'starts': 0}))
    write(root / 'fixture-player-progress.json', b'{"visits":7}')


class FakeServer:
    def __init__(self, binding):
        self.binding = binding
        self.path = binding.world.parent / 'fixture-runtime.json'
        compose_bytes((binding.world / COMPOSE).read_bytes())

    def read(self):
        return json.loads(self.path.read_bytes())

    def save(self, data):
        self.path.write_bytes(encode(data))

    def snapshot(self):
        data = self.read()
        require(data['running'], 'server_not_ready', 'Fixture server stopped.')
        return copy.deepcopy(data['observed'])

    def verify(self, expected):
        actual = self.snapshot()
        require(all(actual[k] == expected[k] for k in ('world', 'volumes', 'project', 'image', 'quests')),
                'server_revision', 'Fixture deployment differs.')
        return actual

    def verify_world(self, expected):
        actual = self.read()['observed']
        require(all(actual[k] == expected[k] for k in ('world', 'volumes', 'project')),
                'world_identity', 'Fixture world changed.')
        return copy.deepcopy(actual)

    def retain_image(self, image):
        data = self.read()
        tag = 'mt2sp-hub-build:' + uuid.uuid4().hex
        data['tags'][tag] = image
        self.save(data)
        return tag

    def verify_image(self, tag, image):
        require(self.read()['tags'].get(tag) == image, 'server_image', 'Fixture image changed.')

    def build_baseline(self):
        data = self.read()
        image = data['tags']['metin2/game:mt2009']
        return {'tag': self.retain_image(image), 'image': image, 'quests': data['images'][image]}

    def build_selection(self, baseline, artifacts):
        quests = {**baseline['quests'], **{p: digest(raw) for p, raw in artifacts.items()}}
        image = 'sha256:' + digest(encode(quests))
        data = self.read()
        data['images'][image] = quests
        self.save(data)
        return {'tag': self.retain_image(image), 'image': image, 'quests': quests}

    def stop(self, project):
        data = self.read()
        require(project == data['observed']['project'], 'world_identity', 'Fixture project changed.')
        data['running'] = False
        data['stops'] += 1
        self.save(data)

    def start(self, expected):
        data = self.read()
        image = data['tags'][compose_bytes((self.binding.world / COMPOSE).read_bytes())]
        data['observed'].update(image=image, quests=data['images'][image])
        data['running'] = True
        data['starts'] += 1
        self.save(data)
        self.verify(expected)


def compile_fixture(quest, **kwargs):
    return {'object/state/' + quest.name: b'fixture state ' + quest.name.encode(),
            'object/notarget/login/' + quest.name + '.start': quest.source}, {'source_sha256': quest.sha256}


@contextmanager
def environment(root, *, fresh=False):
    if fresh:
        initialize(root)
    profile = json.loads((root / 'fixture-profile.json').read_bytes())
    with ExitStack() as stack:
        for target, value in (
            ('mt2sp_hub.installation.baseline.PROFILE', profile),
            ('mt2sp_hub.installation.game_manager.PROFILE', profile),
            ('mt2sp_hub.installation.game_manager.Server', FakeServer),
            ('mt2sp_hub.installation.game_manager.compile_quest', compile_fixture),
            ('mt2sp_hub.installation.game_manager.client_closed', lambda _: None),
            ('mt2sp_hub.installation.game_server.COMPOSE_SHA', digest(COMPOSE_BYTES))):
            stack.enter_context(patch(target, value))
        yield


def addon(root, *, version='0.1.0', kind='combined'):
    folder = root / ('source-' + uuid.uuid4().hex)
    create(folder, 'example.lifecycle', kind, profile='game')
    manifest = json.loads((folder / 'addon.json').read_bytes())
    manifest['version'] = version
    (folder / 'addon.json').write_bytes(encode(manifest))
    if kind != 'client':
        path = folder / 'payload/server/example_lifecycle_greeting.quest'
        path.write_bytes(path.read_bytes().replace(b'Hello', ('Version ' + version + ' Hello').encode()))
    return build(folder)
