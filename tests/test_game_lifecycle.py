from contextlib import contextmanager, redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from game_fixture import addon, environment, FakeServer
from mt2sp_hub.cli import main
from mt2sp_hub.core.validation import digest
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation import storage
from mt2sp_hub.installation.client_files import PATHS
from mt2sp_hub.installation.game_manager import GameManager, attach
from mt2sp_hub.installation.game_server import COMPOSE, GAME, OBJECTS, compose_bytes
from mt2sp_hub.installation.probe import locate
from storage_faults import write_fault


class GameLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hub-game-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    @contextmanager
    def case(self, label='game', attached=True):
        root = self.root / label
        with environment(root, fresh=True):
            if attached:
                attach(root)
            yield root

    def crash(self, root, operation, step, token='-'):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('game_crash_worker.py')),
                                 str(root), operation, token, step], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 73, 'Expected crash boundary was not reached: ' + step)

    def test_install_update_disable_enable_remove_restores_original_pack_and_retains_progress(self):
        with self.case() as root:
            manager = GameManager(root)
            original = {p: (root / 'Klient' / p).read_bytes() for p in PATHS}
            before = manager._state()
            actions = [dict(additions=[addon(root)]), dict(additions=[addon(root, version='0.2.0')]),
                       dict(disable=['example.lifecycle']), dict(enable=['example.lifecycle']),
                       dict(remove=['example.lifecycle'])]
            for generation, action in enumerate(actions, 1):
                plan = manager.plan(**action)
                self.assertTrue(plan['server_restart'])
                manager.apply(plan['plan'])
                manager = GameManager(root)
                self.assertEqual(manager.status()['generation'], generation)
                self.assertFalse(manager.status()['recovery_required'])
                self.assertEqual((root / 'fixture-player-progress.json').read_bytes(), b'{"visits":7}')
                if generation in (3, 5):
                    self.assertEqual(manager._state()['server_files'], {})
                    self.assertEqual({p: (root / 'Klient' / p).read_bytes() for p in PATHS}, original)
            self.assertEqual(manager.status()['packages'], [])
            self.assertEqual(manager._state()['runtime']['world'], before['runtime']['world'])
            self.assertEqual(manager.server.read()['stops'], 5)

    def test_client_only_does_not_restart_server(self):
        with self.case() as root:
            m = GameManager(root)
            plan = m.plan([addon(root, kind='client')])
            self.assertFalse(plan['server_restart'])
            m.apply(plan['plan'])
            self.assertEqual(m.server.read()['stops'], 0)
            self.assertEqual(m._state()['server_files'], {})

    def test_public_cli_uses_guarded_game_attachment_plan_apply_and_status(self):
        with self.case(attached=False) as root:
            def command(args, expected=0):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(args), expected)
                self.assertNotIn(str(root), output.getvalue())
                return json.loads(output.getvalue())
            self.assertEqual(command(['attach', str(root)], 2)['error'], 'confirmation_required')
            self.assertFalse((root / 'Serwer/.mt2sp-hub').exists())
            self.assertTrue(command(['attach', str(root), '--yes'])['attached'])
            package = addon(root)
            archive = root / 'example.zip'
            archive.write_bytes(package.raw)
            plan = command(['plan', '--root', str(root), '--add', str(archive)])
            args = ['apply', '--root', str(root), '--plan', plan['plan']]
            self.assertEqual(command(args, 2)['error'], 'confirmation_required')
            self.assertEqual(command(args + ['--yes'])['outcome'], 'applied')
            self.assertEqual(command(['status', '--root', str(root)])['generation'], 1)
            self.assertEqual(command(['recover', '--root', str(root), '--yes'])['outcome'], 'nothing_pending')

    def test_pending_attachment_rejects_damaged_record_before_compose_write(self):
        with self.case(attached=False) as root:
            self.crash(root, 'attach', 'attachment_journal')
            store = storage.Store(root / 'Serwer/.mt2sp-hub')
            pending = store.verified('attachment.json')
            pending['state']['client'] = None
            store.envelope('attachment.json', pending)
            before = (root / 'Serwer' / COMPOSE).read_bytes()
            with self.assertRaises(HubError):
                attach(root)
            self.assertEqual((root / 'Serwer' / COMPOSE).read_bytes(), before)

    def test_process_exit_at_every_install_checkpoint_recovers_one_consistent_generation(self):
        steps = ['journal', 'server_stopped', 'file:' + COMPOSE,
                 'file:' + OBJECTS + 'object/notarget/login/example_lifecycle_greeting.start',
                 'file:' + OBJECTS + 'object/state/example_lifecycle_greeting',
                 'file:client/pack/root.index', 'file:client/pack/root.data', 'files_written',
                 'server_started', 'state', 'receipt', 'complete']
        for index, step in enumerate(steps):
            with self.subTest(step=step), self.case(str(index)) as root:
                m = GameManager(root)
                before = m._state()
                token = m.plan([addon(root)])['plan']
                self.crash(root, 'apply', step, token)
                m = GameManager(root)
                committed = step in ('state', 'receipt', 'complete')
                outcome = m.recover()['outcome']
                self.assertEqual(outcome, 'nothing_pending' if step == 'complete' else 'applied' if committed else 'rolled_back')
                self.assertEqual(m.status()['generation'], int(committed))
                self.assertFalse(m.status()['recovery_required'])
                if not committed:
                    self.assertEqual(m._state(), before)
                self.assertEqual(m.recover()['outcome'], 'nothing_pending')

    def test_recovery_itself_can_be_interrupted_and_repeated(self):
        steps = ['recovery_server_stopped', 'restore:client/pack/root.data', 'restore:client/pack/root.index',
                 'restore:' + OBJECTS + 'object/state/example_lifecycle_greeting',
                 'restore:' + OBJECTS + 'object/notarget/login/example_lifecycle_greeting.start',
                 'restore:' + COMPOSE, 'recovery_server_started', 'receipt']
        for index, step in enumerate(steps):
            with self.subTest(step=step), self.case(str(index)) as root:
                m = GameManager(root)
                token = m.plan([addon(root)])['plan']
                self.crash(root, 'apply', 'server_started', token)
                self.crash(root, 'recover', step)
                self.assertEqual(GameManager(root).recover()['outcome'], 'rolled_back')
                self.assertEqual(GameManager(root).status()['packages'], [])

    def test_attachment_recovers_each_process_exit_without_restart(self):
        steps = ['attachment_identity', 'attachment_claim', 'attachment_journal', 'attachment_compose', 'attachment_state']
        for index, step in enumerate(steps):
            with self.subTest(step=step), self.case(str(index), attached=False) as root:
                self.crash(root, 'attach', step)
                self.assertTrue(attach(root)['attached'])
                self.assertEqual(GameManager(root).status()['generation'], 0)
                self.assertEqual(GameManager(root).server.read()['stops'], 0)

    def test_server_start_failure_leaves_journal_and_recovers_previous_deployment(self):
        with self.case() as root:
            m = GameManager(root)
            before = m._state()
            token = m.plan([addon(root)])['plan']
            with patch.object(FakeServer, 'start', side_effect=HubError('server_start', 'Invented start failure')):
                with self.assertRaises(HubError):
                    m.apply(token)
            self.assertTrue(m.status()['recovery_required'])
            self.assertEqual(GameManager(root).recover()['outcome'], 'rolled_back')
            self.assertEqual(GameManager(root)._state(), before)

    def test_external_change_or_corrupt_backup_blocks_all_restoration(self):
        for kind in ('client', 'server', 'backup', 'environment', 'official', 'world', 'image'):
            with self.subTest(kind=kind), self.case(kind) as root:
                m = GameManager(root)
                token = m.plan([addon(root)])['plan']
                self.crash(root, 'apply', 'files_written', token)
                plan = m.store.verified('active.json')
                if kind == 'client':
                    (m.binding.client / PATHS[0]).write_bytes(b'foreign edit')
                elif kind == 'server':
                    (m.binding.world / next(iter(plan['after']['server_files']))).write_bytes(b'foreign edit')
                elif kind == 'backup':
                    m.store.path('objects/' + plan['before']['client'][PATHS[0]]).write_bytes(b'damaged backup')
                elif kind == 'environment':
                    (m.binding.world / 'linux-port/docker/.env').write_bytes(b'foreign settings')
                elif kind == 'official':
                    (m.binding.world / GAME / 'bin/game').write_bytes(b'foreign engine')
                else:
                    data = m.server.read()
                    if kind == 'world':
                        data['observed']['world'] = 'c' * 32
                    else:
                        data['tags'].pop(compose_bytes(m.store.get(plan['before']['compose'])))
                    m.server.save(data)
                snapshot = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaises(HubError):
                    GameManager(root).recover()
                self.assertEqual(snapshot, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_client_only_recovery_checks_world_before_restoring(self):
        with self.case() as root:
            m = GameManager(root)
            token = m.plan([addon(root, kind='client')])['plan']
            self.crash(root, 'apply', 'files_written', token)
            data = m.server.read()
            data['observed']['world'] = 'c' * 32
            m.server.save(data)
            raw = (m.binding.client / PATHS[0]).read_bytes()
            with self.assertRaises(HubError):
                m.recover()
            self.assertEqual((m.binding.client / PATHS[0]).read_bytes(), raw)

    def test_client_busy_low_disk_or_changed_image_prevents_journal_and_stop(self):
        for kind in ('busy', 'disk', 'image'):
            with self.subTest(kind=kind), self.case(kind) as root:
                m = GameManager(root)
                token = m.plan([addon(root)])['plan']
                target = {'busy': 'client_closed', 'disk': 'GameManager._space', 'image': 'GameManager._deployment_images'}[kind]
                with patch('mt2sp_hub.installation.game_manager.' + target, side_effect=HubError('preflight', 'Blocked')):
                    with self.assertRaises(HubError):
                        m.apply(token)
                self.assertFalse(m.store.path('active.json').exists())
                self.assertEqual(m.server.read()['stops'], 0)
                with patch('mt2sp_hub.installation.game_manager.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100, 100, 0)):
                    with self.assertRaises(HubError) as caught:
                        m._space(m.store.verified('plans/' + token + '.json'))
                    self.assertEqual(caught.exception.code, 'disk_space')

    def test_storage_failure_preserves_complete_files_and_can_recover(self):
        for phase in ('server', 'client', 'state'):
            with self.subTest(phase=phase), self.case(phase) as root:
                m = GameManager(root)
                token = m.plan([addon(root)])['plan']
                target = {'server': m.binding.world / COMPOSE, 'client': m.binding.client / PATHS[0],
                          'state': m.store.path('state.json')}[phase]
                with write_fault(target, 'fsync'):
                    with patch('mt2sp_hub.installation.game_manager.atomic_write', storage.atomic_write):
                        with self.assertRaises(OSError):
                            m.apply(token)
                self.assertEqual(GameManager(root).recover()['outcome'], 'rolled_back')
                self.assertEqual(GameManager(root).status()['generation'], 0)

    def test_removal_crash_restores_installed_package_and_same_world(self):
        with self.case() as root:
            m = GameManager(root)
            m.apply(m.plan([addon(root)])['plan'])
            before = m._state()
            token = m.plan(remove=['example.lifecycle'])['plan']
            self.crash(root, 'apply', 'files_written', token)
            self.assertEqual(GameManager(root).recover()['outcome'], 'rolled_back')
            self.assertEqual(GameManager(root)._state(), before)
            self.assertTrue(GameManager(root).status()['deployment_files_verified'])

    def test_partial_server_write_crash_does_not_pollute_immutable_tree_or_block_recovery(self):
        for stage in ('crash-partial', 'crash-flushed', 'crash-replaced'):
            with self.subTest(stage=stage), self.case(stage) as root:
                m = GameManager(root)
                token = m.plan([addon(root)])['plan']
                path = 'Serwer/' + OBJECTS + 'object/notarget/login/example_lifecycle_greeting.start'
                self.crash(root, 'apply-write', stage + ':' + path, token)
                self.assertEqual(list((m.binding.world / GAME).rglob('.hub-*.tmp')), [])
                scratch = {p: p.read_bytes() for p in m.store.path('scratch').glob('.hub-*.tmp')}
                self.assertEqual(GameManager(root).recover()['outcome'], 'rolled_back')
                self.assertEqual(scratch, {p: p.read_bytes() for p in m.store.path('scratch').glob('.hub-*.tmp')})

    def test_changed_release_stale_plan_and_copied_ownership_are_rejected(self):
        with self.case() as root:
            m = GameManager(root)
            package = addon(root)
            first = m.plan([package])['plan']
            second = m.plan([package])['plan']
            m.apply(first)
            with self.assertRaises(HubError):
                m.apply(second)
            changed = addon(root, kind='client')
            with self.assertRaises(HubError) as caught:
                m.plan([changed])
            self.assertEqual(caught.exception.code, 'release_changed')
            copied = self.root / 'copied'
            shutil.copytree(root, copied)
            with self.assertRaises(HubError):
                GameManager(copied)

    def test_malformed_plan_never_mutates_targets(self):
        with self.case() as root:
            m = GameManager(root)
            token = m.plan([addon(root)])['plan']
            good = m.store.verified('plans/' + token + '.json')
            for key, value in [('before', None), ('after', []), ('changes', [None]), ('server_changed', 1)]:
                bad = copy.deepcopy(good)
                bad[key] = value
                with self.subTest(key=key), self.assertRaises(HubError):
                    m._validate_plan(bad)
            self.assertEqual(m.server.read()['stops'], 0)
