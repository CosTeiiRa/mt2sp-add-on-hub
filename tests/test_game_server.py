import copy
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from game_fixture import COMPOSE_BYTES
from mt2sp_hub.core.validation import digest, encode
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.game_server import Server, compose_bytes, parse_inventory, GAME, COMPOSE
from mt2sp_hub.installation.probe import Binding


class ServerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.binding = Binding(root / 'Serwer', root / 'Klient')
        self.directory = self.binding.world / 'linux-port/docker'
        self.directory.mkdir(parents=True)
        (self.directory / 'docker-compose.yml').write_bytes(COMPOSE_BYTES)
        (self.directory / '.env').write_bytes(b'PRIVATE_SENTINEL=fixture\n')
        self.pins = patch('mt2sp_hub.installation.game_server.COMPOSE_SHA', digest(COMPOSE_BYTES))
        self.pins.start()
        self.addCleanup(self.pins.stop)
        with patch('mt2sp_hub.installation.game_server._endpoint', return_value='npipe:////./pipe/docker_engine'), \
             patch('mt2sp_hub.installation.game_server.shutil.which', return_value='docker'):
            self.server = Server(self.binding)
        self.image = 'sha256:' + '1' * 64
        self.tag = 'mt2sp-hub-build:' + '2' * 32
        self.game = {'id': '3' * 64, 'image': self.image, 'state': 'running', 'health': 'healthy',
                     'directory': str(self.directory), 'files': str(self.directory / 'docker-compose.yml'),
                     'project': 'fixture', 'service': 'game', 'mounts': []}
        self.db = {**self.game, 'id': '4' * 64, 'service': 'mariadb', 'mounts': []}
        volumes = {'/var/lib/mysql': ('db-data', self.db), '/opt/metin2/var': ('game-var', self.game),
                   '/opt/m2spool': ('rates-spool', self.game)}
        self.volumes = []
        for path, (name, container) in volumes.items():
            container['mounts'].append({'Destination': path, 'Name': 'fixture-' + name, 'Type': 'volume', 'RW': True})
            self.volumes.append({'Name': 'fixture-' + name, 'Driver': 'local', 'Options': None,
                                 'Labels': {'com.docker.compose.project': 'fixture', 'com.docker.compose.volume': name}})
        self.expected = {'project': 'fixture', 'world': '5' * 32, 'image': self.image, 'container': self.game['id'],
                         'volumes': {p: 'fixture-' + n for p, (n, _) in volumes.items()},
                         'quests': {'object/state/stock': digest(b'stock')}}

    def test_compose_changes_only_game_image_and_rejects_any_other_difference(self):
        changed = compose_bytes(COMPOSE_BYTES, self.tag)
        self.assertEqual(compose_bytes(changed), self.tag)
        self.assertEqual(changed.replace(self.tag.encode(), b'metin2/game:mt2009'), COMPOSE_BYTES)
        for raw in (COMPOSE_BYTES + b'\n', COMPOSE_BYTES.replace(b'invented/panel', b'foreign/panel'),
                    COMPOSE_BYTES.replace(b'  game:', b'  alternate:')):
            with self.assertRaises(HubError):
                compose_bytes(raw)
        for tag in ('other/image', self.tag + '\nRUN echo unsafe', None):
            if tag is not None:
                with self.assertRaises(HubError):
                    compose_bytes(COMPOSE_BYTES, tag)

    def test_inventory_rejects_traversal_duplicates_and_case_collisions(self):
        line = digest(b'stock') + '  object/state/stock\n'
        self.assertEqual(parse_inventory(line.encode()), self.expected['quests'])
        for raw in ('', line + line, line + line.replace('/stock', '/Stock'), line.replace('object/state', 'object/../state')):
            with self.assertRaises(HubError):
                parse_inventory(raw.encode())

    def test_matching_world_checks_database_and_all_three_volume_owners(self):
        responses = [self.db['id'].encode(), encode(self.db), self.expected['world'].encode(), encode(self.volumes)]
        with patch.object(self.server, 'command', side_effect=responses), patch.object(self.server, 'discover', return_value=self.game):
            self.assertEqual(self.server.verify_world(self.expected), self.game)
        for failure in ('reset', 'foreign_volume', 'readonly', 'wrong_folder', 'missing_volume'):
            db, volumes = copy.deepcopy(self.db), copy.deepcopy(self.volumes)
            world = self.expected['world']
            if failure == 'reset':
                world = 'a' * 32
            elif failure == 'foreign_volume':
                volumes[1]['Labels']['com.docker.compose.volume'] = 'other'
            elif failure == 'readonly':
                db['mounts'][0]['RW'] = False
            elif failure == 'wrong_folder':
                db['directory'] = str(self.directory.parent)
            else:
                volumes.pop()
            with self.subTest(failure=failure), patch.object(self.server, 'command', side_effect=[self.db['id'].encode(), encode(db), world.encode(), encode(volumes)]), \
                 patch.object(self.server, 'discover', return_value=self.game), self.assertRaises(HubError):
                self.server.verify_world(self.expected)

    def test_stopped_or_absent_game_does_not_prevent_world_identity_check(self):
        for game in (None, {**self.game, 'state': 'exited'}):
            with patch.object(self.server, 'command', side_effect=[self.db['id'].encode(), encode(self.db), self.expected['world'].encode(), encode(self.volumes)]), \
                 patch.object(self.server, 'discover', return_value=game):
                self.assertEqual(self.server.verify_world(self.expected), game)

    def test_ambiguous_or_foreign_compose_binding_is_rejected(self):
        for records in ([self.game, self.game], [{**self.game, 'files': self.game['files'] + ',override.yml'}]):
            raw = b'\n'.join(encode(record) for record in records)
            with patch.object(self.server, 'command', side_effect=[b'\n'.join(r['id'].encode() for r in records), raw]), self.assertRaises(HubError):
                self.server.discover()

    def test_image_inspection_is_bounded_isolated_and_always_cleans_up_its_own_container(self):
        raw = (digest(b'stock') + '  object/state/stock\n').encode()
        for failure in (False, True):
            with patch.object(self.server, 'command', side_effect=HubError('failed', 'fixture') if failure else None, return_value=raw) as command, \
                 patch('mt2sp_hub.installation.game_server._cleanup') as cleanup:
                if failure:
                    with self.assertRaises(HubError):
                        self.server.image_inventory(self.image)
                else:
                    self.assertEqual(self.server.image_inventory(self.image), self.expected['quests'])
                args = command.call_args.args[0]
                self.assertIn('--network=none', args)
                self.assertIn('--read-only', args)
                self.assertIn('/usr/bin/timeout', args)
                self.assertNotIn('--volume', args)
                self.assertNotIn('--mount', args)
                cleanup.assert_called_once()
                self.assertEqual(args[args.index('--name') + 1], 'mt2sp-hub-inspect-' + cleanup.call_args.args[3])

    def test_prepared_image_checks_retained_baseline_before_and_after_build(self):
        baseline = {'tag': self.tag, 'image': self.image, 'quests': self.expected['quests']}
        artifacts = {'object/state/example_quest': b'invented compiled quest'}
        desired = {**baseline['quests'], **{p: digest(raw) for p, raw in artifacts.items()}}
        with patch.object(self.server, 'verify_image') as verify, patch.object(self.server, 'command', return_value=self.image.encode()) as command, \
             patch.object(self.server, 'image_inventory', return_value=desired):
            output = self.server.build_selection(baseline, artifacts)
            self.assertEqual(output['quests'], desired)
            self.assertEqual(verify.call_count, 2)
            self.assertTrue(all(call.args == (self.tag, self.image) for call in verify.call_args_list))
            with tarfile.open(fileobj=io.BytesIO(command.call_args.kwargs['incoming'])) as archive:
                self.assertEqual(set(archive.getnames()), {'Dockerfile', *artifacts})
                self.assertIn(self.tag.encode(), archive.extractfile('Dockerfile').read())
        with patch.object(self.server, 'verify_image'), patch.object(self.server, 'command') as command:
            for artifacts in ({'Dockerfile': b'unsafe'}, {'object/state/stock': b'collision'}, {'object/../outside': b'escape'}):
                with self.assertRaises(HubError):
                    self.server.build_selection(baseline, artifacts)
            command.assert_not_called()

    def test_command_failures_do_not_echo_private_output(self):
        for result in ((2, b'private-sentinel'), HubError('compiler_timeout', 'private-sentinel')):
            with patch('mt2sp_hub.installation.game_server._run', side_effect=result if isinstance(result, Exception) else None, return_value=result):
                with self.assertRaises(HubError) as caught:
                    self.server.command(['info'])
                self.assertNotIn('private-sentinel', str(caught.exception))
                self.assertEqual(caught.exception.code, 'server_command')
