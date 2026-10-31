"""Journaled client/quest lifecycle for one reviewed local game installation."""
from __future__ import annotations

import copy
from contextlib import ExitStack, contextmanager
import os
import re
import shutil
import uuid

from ..core.packages import Package
from ..core.validation import (MAX_FILE, MAX_FILES, MAX_PACKAGES, MAX_SELECTED_ARCHIVES, MAX_TOTAL,
                               SHA, confined, digest, encode, identifier, path_set, read_bounded)
from ..errors import HubError, require
from .baseline import check_build, fingerprint_file, fingerprint_tree
from . import client_files
from .client_pack import compose
from .compiler import CompilerProfile, compile_quest, _run
from .game_server import COMPOSE, GAME, OBJECTS, Server, compose_bytes
from .locking import exclusive
from .official_build import PROFILE
from .probe import CONTROL, _record, _version, locate
from .quests import collect_quests
from .storage import Store, atomic_write, unlink


def client_closed(binding):
    require(os.name == 'nt', 'game_platform', 'Real installation currently requires Windows.')
    executable = shutil.which('powershell.exe')
    require(executable is not None, 'client_status', 'Client process status could not be checked.')
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process -Filter "
              "\"Name='metin2client.exe'\" | Select-Object -ExpandProperty ExecutablePath) | ConvertTo-Json -Compress")
    code, raw = _run(executable, ['-NoProfile', '-NonInteractive', '-Command', script], dict(os.environ), limit=65536)
    require(code == 0, 'client_status', 'Client process status could not be checked.')
    from ..core.validation import parse_json
    values = parse_json(raw, 65536) if raw.strip() else []
    if isinstance(values, str) or values is None:
        values = [values]
    require(isinstance(values, list) and all(isinstance(p, str) and p for p in values),
            'client_status', 'A game client process could not be identified; close game clients first.')
    wanted = os.path.normcase(str(binding.client / 'metin2client.exe'))
    require(not any(os.path.normcase(os.path.normpath(p)) == wanted for p in values),
            'client_running', 'Close this game client before installing or recovering add-ons.')


@contextmanager
def target_locks(binding):
    with ExitStack() as stack:
        for root in sorted((binding.world, binding.client), key=lambda p: os.path.normcase(str(p))):
            control = confined(root, CONTROL)
            control.mkdir(exist_ok=True)
            stack.enter_context(exclusive(confined(root, CONTROL + '/lock')))
        yield


def _identity(binding, token, attachment):
    return {'schema': 1, 'kind': 'metin2sp', 'id': token, 'attachment': attachment,
            'world_root': os.path.normcase(str(binding.world)), 'client_root': os.path.normcase(str(binding.client))}


def _claim(binding, token):
    return {'schema': 1, 'kind': 'metin2sp-client', 'installation': token,
            'world_root': os.path.normcase(str(binding.world)), 'client_root': os.path.normcase(str(binding.client))}


def _target(binding, relative):
    require(relative == COMPOSE or isinstance(relative, str) and relative.startswith(OBJECTS + 'object/')
            and re.fullmatch(r'[A-Za-z0-9_./-]+', relative[len(OBJECTS):]),
            'game_target', 'Only the reviewed Compose file and compiled quest resources are writable.')
    return confined(binding.world, relative)


def validate_state(binding, token, state):
    require(isinstance(state, dict) and set(state) == {'schema', 'installation', 'generation', 'profile', 'baseline',
            'runtime', 'installed', 'server_files', 'client', 'compose', 'environment'}
            and type(state.get('schema')) is int and state['schema'] == 1 and state.get('installation') == token
            and state.get('profile') == PROFILE['id'] and type(state.get('generation')) is int
            and state['generation'] >= 0 and isinstance(state.get('installed'), dict)
            and len(state['installed']) <= MAX_PACKAGES and isinstance(state.get('server_files'), dict)
            and len(state['server_files']) <= MAX_FILES and isinstance(state['client'], dict)
            and set(state['client']) == set(client_files.PATHS),
            'state_schema', 'Unsupported or damaged game installation state.')
    for row in (state['client'], {'compose': state['compose'], 'environment': state['environment']}):
        require(all(isinstance(key, str) and SHA.fullmatch(key) for key in row.values()),
                'state_schema', 'Invalid game state object reference.')
    for ident, row in state['installed'].items():
        identifier(ident)
        require(isinstance(row, dict) and set(row) == {'archive', 'version', 'enabled'}
                and isinstance(row['archive'], str) and SHA.fullmatch(row['archive'])
                and isinstance(row['version'], str) and len(row['version']) <= 128 and type(row['enabled']) is bool,
                'state_schema', 'Invalid installed package record.')
    baseline, runtime = state['baseline'], state['runtime']
    require(isinstance(baseline, dict) and set(baseline) == {'tag', 'image', 'quests', 'client', 'config', 'compiler', 'functions'}
            and isinstance(baseline['tag'], str) and re.fullmatch(r'mt2sp-hub-build:[0-9a-f]{32}', baseline['tag'])
            and isinstance(baseline['image'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', baseline['image'])
            and baseline['client'] == {p: PROFILE['files']['client'][p]['sha256'] for p in client_files.PATHS}
            and baseline['config'] == PROFILE['files']['client']['pack/root.json']['sha256']
            and baseline['compiler'] == PROFILE['files']['server'][GAME + '/bin/qc']['sha256']
            and baseline['functions'] == PROFILE['files']['server'][GAME + '/share/locale/poland/quest/quest_functions']['sha256'],
            'state_schema', 'Retained baseline differs from the reviewed profile.')
    require(isinstance(runtime, dict) and set(runtime) == {'world', 'volumes', 'project', 'image', 'container', 'quests'}
            and isinstance(runtime['world'], str) and re.fullmatch(r'[0-9a-f]{32}', runtime['world'])
            and isinstance(runtime['project'], str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}', runtime['project'])
            and isinstance(runtime['image'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', runtime['image'])
            and isinstance(runtime['container'], str) and re.fullmatch(r'[0-9a-f]{64}', runtime['container'])
            and isinstance(runtime['volumes'], dict)
            and set(runtime['volumes']) == {'/var/lib/mysql', '/opt/metin2/var', '/opt/m2spool'}
            and all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,254}', v) for v in runtime['volumes'].values())
            and len(set(runtime['volumes'].values())) == 3,
            'state_schema', 'Invalid persistent world or deployment record.')
    for rows in (baseline['quests'], runtime['quests']):
        require(isinstance(rows, dict) and 0 < len(rows) <= 32768
                and all(isinstance(p, str) and p.startswith('object/') and isinstance(v, str) and SHA.fullmatch(v) for p, v in rows.items()),
                'state_schema', 'Invalid quest deployment inventory.')
        path_set(rows)
    for relative, key in state['server_files'].items():
        _target(binding, relative)
        require(relative != COMPOSE and isinstance(key, str) and SHA.fullmatch(key), 'state_schema', 'Invalid owned server file digest.')
    owned = {p[len(OBJECTS):]: v for p, v in state['server_files'].items()}
    require(not (set(owned) & set(baseline['quests'])) and runtime['quests'] == {**baseline['quests'], **owned},
            'state_schema', 'Owned quest inventory disagrees with the deployment record.')


def attach(selected, checkpoint=None):
    """Retryable attachment; reserve an image tag without restarting the server."""
    checkpoint = checkpoint or (lambda _: None)
    binding = locate(selected)
    store = Store(binding.world / CONTROL)
    with target_locks(binding):
        checks = check_build(binding, _version(binding.client, 'client.version'), _version(binding.world, 'VERSION'))
        require(checks['status'] == 'reference_match', 'game_build', 'Attachment requires matching reviewed official build inputs.')
        server = Server(binding)
        runtime = server.snapshot()
        identity_path = store.path('identity.json')
        if identity_path.exists():
            identity = _record(binding.world, 'identity.json')
            require(identity == _identity(binding, identity.get('id'), 'pending')
                    and isinstance(identity.get('id'), str) and re.fullmatch(r'[0-9a-f]{32}', identity['id']),
                    'attachment_conflict', 'Existing ownership is not a matching pending attachment.')
            token = identity['id']
        else:
            require(all(set(p.name for p in (root / CONTROL).iterdir()) <= {'lock'}
                        for root in (binding.world, binding.client)),
                    'attachment_conflict', 'Existing state must be recovered or migrated before attachment.')
            token = uuid.uuid4().hex
            store.envelope('identity.json', _identity(binding, token, 'pending'))
            checkpoint('attachment_identity')
        client_store = Store(binding.client / CONTROL)
        claim = _claim(binding, token)
        if client_store.path('claim.json').exists():
            require(_record(binding.client, 'claim.json') == claim, 'attachment_conflict', 'Client belongs to another installation.')
        else:
            # Both ownership locks are held. Publish a complete claim atomically;
            # a killed writer must not leave an unreadable half-claim behind.
            client_store.envelope('claim.json', claim)
            checkpoint('attachment_claim')
        if store.path('attachment.json').exists():
            pending = store.verified('attachment.json')
            require(isinstance(pending, dict) and set(pending) == {'state', 'compose_before', 'compose_after'},
                    'attachment_conflict', 'Invalid pending attachment journal.')
            state = pending['state']
        else:
            baseline = server.build_baseline()
            require(baseline['quests'] == runtime['quests'], 'server_baseline', 'Running quests differ from the reviewed official build.')
            originals = {p: store.put(read_bounded(confined(binding.client, p), client_files.MAX_PAIR)) for p in client_files.PATHS}
            baseline.update(client=originals,
                            config=store.put(read_bounded(confined(binding.client, 'pack/root.json'), 65536)),
                            compiler=store.put(read_bounded(confined(binding.world, GAME + '/bin/qc'), 32 * 1024 * 1024)),
                            functions=store.put(read_bounded(confined(binding.world, GAME + '/share/locale/poland/quest/quest_functions'), MAX_FILE)))
            old_compose = read_bounded(confined(binding.world, COMPOSE), 128 * 1024)
            retained = server.retain_image(runtime['image'])
            new_compose = compose_bytes(old_compose, retained)
            state = {'schema': 1, 'installation': token, 'generation': 0, 'profile': PROFILE['id'],
                     'baseline': baseline, 'runtime': runtime, 'installed': {}, 'server_files': {}, 'client': originals,
                     'compose': store.put(new_compose),
                     'environment': fingerprint_file(confined(binding.world, 'linux-port/docker/.env'))['sha256']}
            pending = {'state': state, 'compose_before': store.put(old_compose), 'compose_after': state['compose']}
            store.envelope('attachment.json', pending)
            checkpoint('attachment_journal')
        validate_state(binding, token, state)
        require(state['generation'] == 0 and not state['installed'] and not state['server_files']
                and state['client'] == state['baseline']['client'] and state['compose'] == pending['compose_after']
                and state['runtime']['quests'] == state['baseline']['quests'],
                'attachment_conflict', 'Pending attachment state is inconsistent.')
        for key in (*state['baseline']['client'].values(), state['baseline']['config'],
                    state['baseline']['compiler'], state['baseline']['functions']):
            store.get(key)
        compose_bytes(store.get(pending['compose_before']))
        server.verify_image(compose_bytes(store.get(pending['compose_after'])), state['runtime']['image'])
        server.verify_image(state['baseline']['tag'], state['baseline']['image'])
        require(fingerprint_file(confined(binding.world, 'linux-port/docker/.env'))['sha256'] == state['environment'],
                'attachment_conflict', 'Launch settings changed during attachment.')
        server.verify(state['runtime'])
        current = fingerprint_file(confined(binding.world, COMPOSE))['sha256']
        require(current in (pending['compose_before'], pending['compose_after']),
                'attachment_conflict', 'Compose changed during attachment; preserve it.')
        if current != pending['compose_after']:
            atomic_write(confined(binding.world, COMPOSE), store.get(pending['compose_after']))
            checkpoint('attachment_compose')
        server.verify(state['runtime'])
        if store.path('state.json').exists():
            require(store.verified('state.json') == state, 'attachment_conflict', 'Pending state differs from its journal.')
        else:
            store.envelope('state.json', state)
            checkpoint('attachment_state')
        store.envelope('identity.json', _identity(binding, token, 'ready'))
        checkpoint('attachment_ready')
    return {'kind': 'metin2sp', 'attached': True, 'generation': 0}


class GameManager:
    def __init__(self, selected, checkpoint=None):
        self.binding = locate(selected)
        self.store = Store(self.binding.world / CONTROL)
        self.checkpoint = checkpoint or (lambda _: None)
        self.identity = _record(self.binding.world, 'identity.json')
        self._ownership()
        self.server = Server(self.binding)

    def _ownership(self):
        require(self.identity == _identity(self.binding, self.identity.get('id'), 'ready')
                and isinstance(self.identity.get('id'), str) and re.fullmatch(r'[0-9a-f]{32}', self.identity['id'])
                and _record(self.binding.world, 'identity.json') == self.identity
                and _record(self.binding.client, 'claim.json') == _claim(self.binding, self.identity['id']),
                'installation_identity', 'Game ownership changed or the installation was moved/copied.')

    @contextmanager
    def locked(self):
        with target_locks(self.binding):
            self._ownership()
            yield

    def _state(self):
        state = self.store.verified('state.json')
        self._validate_state(state)
        return state

    def _validate_state(self, state):
        validate_state(self.binding, self.identity['id'], state)

    def _clear(self):
        require(not self.store.path('active.json').exists(), 'recovery_required', 'Recover the unfinished game operation first.')

    def _target(self, relative):
        return _target(self.binding, relative)

    def _bytes(self, relative):
        path = self._target(relative)
        return read_bounded(path, MAX_FILE) if path.exists() else None

    def _hash(self, relative):
        raw = self._bytes(relative)
        return digest(raw) if raw is not None else None

    def _immutable_inputs(self, state, extra_files=()):
        require(_version(self.binding.client, 'client.version') == PROFILE['client_version']
                and _version(self.binding.world, 'VERSION') == PROFILE['server_version'],
                'game_build', 'Game version changed; review compatibility before applying add-ons.')
        for p, expected in PROFILE['files']['client'].items():
            if p in client_files.PATHS:
                continue
            require(fingerprint_file(confined(self.binding.client, p))['sha256'] == expected['sha256'],
                    'target_drift', 'Client build inputs changed outside Hub.')
        excluded = {p[len(GAME) + 1:] for p in set(state['server_files']) | set(extra_files)}
        require(fingerprint_tree(confined(self.binding.world, GAME), excluded=excluded) == PROFILE['server_trees'][GAME],
                'server_baseline', 'Official server inputs changed outside Hub.')
        require(fingerprint_file(confined(self.binding.world, 'linux-port/docker/.env'))['sha256'] == state['environment'],
                'target_drift', 'Server launch settings changed; preserve them and review the installation.')

    def _inputs(self, state):
        self._immutable_inputs(state)
        for p, expected in PROFILE['files']['client'].items():
            wanted = state['client'].get(p, expected['sha256'])
            require(fingerprint_file(confined(self.binding.client, p))['sha256'] == wanted,
                    'target_drift', 'Client build inputs changed outside Hub.')
        require(all(self._hash(p) == key for p, key in state['server_files'].items()),
                'target_drift', 'Managed quest files changed outside Hub.')
        require(self._hash(COMPOSE) == state['compose']
                and fingerprint_file(confined(self.binding.world, 'linux-port/docker/.env'))['sha256'] == state['environment'],
                'target_drift', 'Server launch configuration changed; preserve it and review the installation.')

    def _selection(self, state, additions, remove, enable, disable):
        require(len(additions) <= MAX_PACKAGES and sum(len(p.raw) for p in additions) <= MAX_SELECTED_ARCHIVES,
                'selection_limit', 'Package additions exceed their limits.')
        selected, touched = copy.deepcopy(state['installed']), set()
        for package in additions:
            manifest = package.manifest
            ident = manifest['id']
            require(ident not in touched, 'duplicate_package', 'A package was selected twice.')
            touched.add(ident)
            key = self.store.put(package.raw)
            release = 'releases/' + ident + '/' + digest(manifest['version'].encode()) + '.json'
            if self.store.path(release).exists():
                require(self.store.verified(release) == {'archive': key}, 'release_changed', 'Use a new version for changed package bytes.')
            else:
                self.store.envelope(release, {'archive': key})
            selected[ident] = {'archive': key, 'version': manifest['version'], 'enabled': selected.get(ident, {}).get('enabled', True)}
        for action, ids in (('remove', remove), ('enable', enable), ('disable', disable)):
            for ident in ids:
                identifier(ident)
                require(ident in selected and ident not in touched, 'package_selection', 'Conflicting or unknown package selection.')
                touched.add(ident)
                if action == 'remove':
                    del selected[ident]
                else:
                    selected[ident]['enabled'] = action == 'enable'
        require(touched and len(selected) <= MAX_PACKAGES, 'package_selection', 'Select a bounded nonempty package operation.')
        packages, total = [], 0
        for ident, row in selected.items():
            raw = self.store.get(row['archive'])
            total += len(raw)
            require(total <= MAX_SELECTED_ARCHIVES, 'selection_limit', 'Selected package cache exceeds its limit.')
            package = Package(raw)
            require(package.manifest['id'] == ident and package.manifest['version'] == row['version']
                    and type(row['enabled']) is bool, 'state_schema', 'Package cache and installed state disagree.')
            if row['enabled']:
                packages.append(package)
        return selected, packages

    def plan(self, additions=(), remove=(), enable=(), disable=()):
        with self.locked():
            self._clear()
            before = self._state()
            self._inputs(before)
            self.server.verify(before['runtime'])
            selected, packages = self._selection(before, additions, remove, enable, disable)
            baseline = before['baseline']
            pack_bytes = {p: self.store.get(key) for p, key in baseline['client'].items()}
            config = self.store.get(baseline['config'])
            pins = {p: PROFILE['files']['client'][p]['sha256'] for p in (*client_files.PATHS, 'pack/root.json')}
            output = compose(pack_bytes, config, packages, pins)
            client = client_files.prepare(self.binding, self.store, output, before['client'])
            official_names = {p.split('/')[-1] for p in baseline['quests'] if p.startswith('object/state/')}
            quests = collect_quests(packages, official_names=official_names)
            artifacts, receipts = {}, []
            compiler, functions = self.store.get(baseline['compiler']), self.store.get(baseline['functions'])
            profile = CompilerProfile(baseline['image'], digest(compiler), digest(functions))
            for quest in quests.values():
                files, receipt = compile_quest(quest, profile=profile, compiler=compiler, functions=functions,
                                              occupied_paths=set(baseline['quests']) | set(artifacts))
                artifacts.update(files)
                receipts.append(receipt)
                require(len(artifacts) <= MAX_FILES and sum(map(len, artifacts.values())) <= MAX_TOTAL,
                        'quest_limit', 'Selected compiled quests exceed their combined limits.')
            desired_files = {OBJECTS + p: self.store.put(raw) for p, raw in artifacts.items()}
            server_changed = desired_files != before['server_files']
            deployment = self.server.build_selection(baseline, artifacts) if server_changed else None
            raw_compose = self.store.get(before['compose'])
            desired_compose = compose_bytes(raw_compose, deployment['tag']) if deployment else raw_compose
            changes = []
            for p in sorted(set(before['server_files']) | set(desired_files) | {COMPOSE}):
                old = self._bytes(p)
                old_key = self.store.put(old) if old is not None else None
                require(p == COMPOSE or old_key == before['server_files'].get(p),
                        'quest_collision', 'An unowned file occupies a selected quest destination.')
                new_key = self.store.put(desired_compose) if p == COMPOSE else desired_files.get(p)
                changes.append({'path': p, 'before': old_key, 'after': new_key})
            after = copy.deepcopy(before)
            after.update(generation=before['generation'] + 1, installed=selected, server_files=desired_files,
                         client={p: digest(raw) for p, raw in output.items()}, compose=digest(desired_compose))
            if deployment:
                after['runtime'].update(image=deployment['image'], quests=deployment['quests'])
            plan = {'schema': 1, 'id': uuid.uuid4().hex, 'installation': self.identity['id'],
                    'before': before, 'after': after, 'client': client, 'changes': changes,
                    'server_changed': server_changed}
            self._inputs(before)
            self.server.verify(before['runtime'])
            self.store.envelope('preparations/' + plan['id'] + '.json', receipts)
            self.store.envelope('plans/' + plan['id'] + '.json', plan)
            return {'plan': plan['id'], 'packages': sorted(selected), 'server_restart': server_changed,
                    'client_close_required': True, 'player_quest_state': 'retained'}

    def _validate_plan(self, plan):
        require(isinstance(plan, dict) and set(plan) == {'schema', 'id', 'installation', 'before', 'after', 'client', 'changes', 'server_changed'}
                and plan['schema'] == 1 and plan['installation'] == self.identity['id']
                and isinstance(plan['id'], str) and re.fullmatch(r'[0-9a-f]{32}', plan['id'])
                and type(plan['server_changed']) is bool and isinstance(plan['changes'], list)
                and len(plan['changes']) <= MAX_FILES * 2 + 1,
                'plan_invalid', 'Invalid game operation journal.')
        self._validate_state(plan['before'])
        self._validate_state(plan['after'])
        require(plan['after']['generation'] == plan['before']['generation'] + 1
                and plan['before']['baseline'] == plan['after']['baseline']
                and plan['before']['environment'] == plan['after']['environment']
                and plan['server_changed'] == (plan['before']['server_files'] != plan['after']['server_files'])
                and all(plan['before']['runtime'][k] == plan['after']['runtime'][k] for k in ('world', 'volumes', 'project', 'container'))
                and (plan['server_changed'] or plan['before']['runtime'] == plan['after']['runtime']),
                'plan_invalid', 'Operation changes an immutable baseline or world identity.')
        client_files._validate(self.binding, self.store, plan['client'])
        require(all(isinstance(row, dict) and set(row) == {'path', 'before', 'after'}
                    and isinstance(row['path'], str) for row in plan['changes']),
                'plan_invalid', 'Invalid server file change.')
        expected_paths = set(plan['before']['server_files']) | set(plan['after']['server_files']) | {COMPOSE}
        require(len(plan['changes']) == len(expected_paths) and {r['path'] for r in plan['changes']} == expected_paths,
                'plan_invalid', 'Game operation does not cover its server resources.')
        for row in plan['changes']:
            require(set(row) == {'path', 'before', 'after'}, 'plan_invalid', 'Invalid server file change.')
            self._target(row['path'])
            for phase in ('before', 'after'):
                key = row[phase]
                if key is not None:
                    self.store.get(key)
                expected = plan[phase]['compose'] if row['path'] == COMPOSE else plan[phase]['server_files'].get(row['path'])
                require(key == expected, 'plan_invalid', 'Server file change and state disagree.')
        for p in client_files.PATHS:
            require(all(plan['client']['files'][p][phase] == plan[phase]['client'][p] for phase in ('before', 'after')),
                    'plan_invalid', 'Client file change and state disagree.')

    def _deployment_images(self, plan):
        for phase in ('before', 'after'):
            state = plan[phase]
            tag = compose_bytes(self.store.get(state['compose']))
            self.server.verify_image(tag, state['runtime']['image'])

    def _space(self, plan):
        # Conservative headroom for either direction, atomic temporary files and
        # journal publication. Cached objects already exist at this point.
        reserve = 16 * 1024 * 1024
        client = sum(len(self.store.get(key)) for row in plan['client']['files'].values() for key in row.values())
        server = sum(len(self.store.get(row[phase])) for row in plan['changes']
                     for phase in ('before', 'after') if row[phase] is not None)
        for root in (self.binding.client, self.binding.world):
            require(shutil.disk_usage(root).free >= reserve + client + server,
                    'disk_space', 'Free disk space is insufficient for replacement and recovery.')

    def _preflight_files(self, plan, phase=None):
        for row in plan['changes']:
            allowed = {row[phase]} if phase else {row['before'], row['after']}
            require(self._hash(row['path']) in allowed, 'recovery_conflict', 'External server file changes prevent this operation.')
        for p, row in plan['client']['files'].items():
            allowed = {row[phase]} if phase else set(row.values())
            require(fingerprint_file(confined(self.binding.client, p))['sha256'] in allowed,
                    'recovery_conflict', 'External client file changes prevent this operation.')

    def _server_files(self, plan, phase):
        rows = reversed(plan['changes']) if phase == 'before' else plan['changes']
        for row in rows:
            require(self._hash(row['path']) in {row['before'], row['after']}, 'recovery_conflict', 'Server file changed during the operation.')
            if self._hash(row['path']) != row[phase]:
                path = self._target(row['path'])
                if row[phase] is None:
                    unlink(path)
                else:
                    # Keep interrupted scratch writes outside the immutable
                    # official build tree, on the same world filesystem.
                    atomic_write(path, self.store.get(row[phase]), temporary_directory=self.store.path('scratch'))
                require(self._hash(row['path']) == row[phase], 'write_verification', 'Server file did not verify.')
                self.checkpoint(('restore:' if phase == 'before' else 'file:') + row['path'])

    def _finish(self, plan, outcome):
        self.store.envelope('receipts/' + plan['id'] + '.json', {'outcome': outcome, 'plan': plan['id'],
                             'generation': plan['after' if outcome == 'applied' else 'before']['generation']})
        self.checkpoint('receipt')
        unlink(self.store.path('active.json'))
        self.checkpoint('complete')
        return {'outcome': outcome, 'plan': plan['id']}

    def apply(self, token):
        require(isinstance(token, str) and re.fullmatch(r'[0-9a-f]{32}', token), 'plan_id', 'Invalid operation ID.')
        with self.locked():
            self._clear()
            require(not self.store.path('receipts/' + token + '.json').exists(), 'plan_used', 'This operation already finished.')
            plan = self.store.verified('plans/' + token + '.json')
            self._validate_plan(plan)
            require(plan['id'] == token and self._state() == plan['before'], 'plan_stale', 'Installation state changed; review again.')
            client_closed(self.binding)
            self._inputs(plan['before'])
            self._preflight_files(plan, 'before')
            self.server.verify(plan['before']['runtime'])
            self._deployment_images(plan)
            self._space(plan)
            self.store.envelope('active.json', plan)
            self.checkpoint('journal')
            if plan['server_changed']:
                self.server.stop(plan['before']['runtime']['project'])
                self.checkpoint('server_stopped')
            self._immutable_inputs(plan['before'])
            self._server_files(plan, 'after')
            client_files.write(self.binding, self.store, plan['client'], checkpoint=lambda p: self.checkpoint('file:client/' + p))
            self.checkpoint('files_written')
            if plan['server_changed']:
                self.server.start(plan['after']['runtime'])
                self.checkpoint('server_started')
            self.server.verify(plan['after']['runtime'])
            self._preflight_files(plan, 'after')
            self._inputs(plan['after'])
            self.store.envelope('state.json', plan['after'])
            self.checkpoint('state')
            return self._finish(plan, 'applied')

    def recover(self):
        with self.locked():
            if not self.store.path('active.json').exists():
                return {'outcome': 'nothing_pending'}
            plan = self.store.verified('active.json')
            self._validate_plan(plan)
            current = self._state()
            require(current in (plan['before'], plan['after']), 'recovery_conflict', 'Installation state differs from both journal generations.')
            client_closed(self.binding)
            committed = current == plan['after']
            self._preflight_files(plan, 'after' if committed else None)
            self._immutable_inputs(current, set(plan['before']['server_files']) | set(plan['after']['server_files']))
            require(fingerprint_file(confined(self.binding.world, 'linux-port/docker/.env'))['sha256'] == current['environment'],
                    'recovery_conflict', 'Server launch settings changed during the operation.')
            # Establish world identity even for a client-only rollback, before
            # restoring either side. Never start an unknown or reset world.
            record = self.server.verify_world(current['runtime'])
            require(record is None or record['image'] in {plan['before']['runtime']['image'], plan['after']['runtime']['image']},
                    'recovery_conflict', 'An unrelated server deployment prevents recovery.')
            self._deployment_images(plan)
            if not committed:
                self._space(plan)
                if plan['server_changed']:
                    if record is not None:
                        self.server.stop(current['runtime']['project'])
                    self.checkpoint('recovery_server_stopped')
                client_files.write(self.binding, self.store, plan['client'], 'before',
                                   checkpoint=lambda p: self.checkpoint('restore:client/' + p))
                self._server_files(plan, 'before')
                if plan['server_changed']:
                    self.server.start(plan['before']['runtime'])
                    self.checkpoint('recovery_server_started')
            self.server.verify(current['runtime'])
            self._preflight_files(plan, 'after' if committed else 'before')
            return self._finish(plan, 'applied' if committed else 'rolled_back')

    def status(self):
        with self.locked():
            state = self._state()
            pending = self.store.path('active.json').exists()
            verified = False
            if not pending:
                self._inputs(state)
                self.server.verify(state['runtime'])
                verified = True
            return {'kind': 'metin2sp', 'generation': state['generation'], 'profile': state['profile'],
                    'packages': [{'id': ident, 'version': row['version'], 'enabled': row['enabled']}
                                 for ident, row in sorted(state['installed'].items())],
                    'recovery_required': pending, 'deployment_files_verified': verified,
                    'gameplay_verified': False}
