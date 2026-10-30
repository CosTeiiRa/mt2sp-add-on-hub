"""Read-only layout and ownership inspection; never grants game write access."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from ..core.validation import confined, digest, encode, parse_json, read_bounded
from ..errors import HubError, require

CONTROL = '.mt2sp-hub'
COMPOSE_FILES = ('compose.yaml', 'compose.yml', 'docker-compose.yml', 'docker-compose.yaml')
CLIENT_FILES = ('metin2client.exe', 'pack/root.index', 'pack/root.data')
WORLD_FILES = ('VERSION', 'files/items.json', 'linux-port/docker/game/Dockerfile')
MAX_METADATA = 64 * 1024


@dataclass(frozen=True)
class Binding:
    """Private local paths, deliberately absent from the public probe report."""
    world: Path
    client: Path


def locate(selected):
    try:
        selected = Path(selected).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise HubError('installation_unreadable', 'Could not resolve the selected game folder.') from exc
    candidates = [selected, selected / 'Metin2 Singleplayer']
    if selected.name.casefold() in ('serwer', 'klient'):
        candidates.append(selected.parent)
    elif selected.name.casefold() == 'pack' and selected.parent.name.casefold() == 'klient':
        candidates.append(selected.parent.parent)
    matches = {}
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        candidate = candidate.resolve()
        client, world = confined(candidate, 'Klient'), confined(candidate, 'Serwer')
        if client.is_dir() and world.is_dir():
            matches[os.path.normcase(str(candidate))] = Binding(world.resolve(), client.resolve())
    require(bool(matches), 'installation_not_found',
            'Choose the game folder containing Klient and Serwer, or one of those folders.')
    require(len(matches) == 1, 'installation_ambiguous',
            'More than one game layout matches. Select its Klient or Serwer folder directly.')
    return next(iter(matches.values()))


def _file_status(root, relative):
    try:
        path = confined(root, relative)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return 'not_regular'
        return 'present' if info.st_size else 'empty'
    except FileNotFoundError:
        return 'missing'
    except HubError:
        return 'unsafe_path'
    except OSError:
        return 'unreadable'


def _version(root, relative):
    # Version files are untrusted labels, not compatibility evidence. Never echo
    # arbitrary file contents (including personal notes or credential text).
    try:
        raw = read_bounded(confined(root, relative), 256)
        label = raw.decode('utf-8-sig').strip()
        return label if re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,6}){2,3}', label) else None
    except (OSError, HubError, UnicodeError):
        return None


def _record(root, name):
    value = parse_json(read_bounded(confined(root, CONTROL + '/' + name), MAX_METADATA), MAX_METADATA)
    require(isinstance(value, dict) and set(value) == {'sha256', 'data'}
            and value['sha256'] == digest(encode(value['data'])),
            'ownership_invalid', 'Ownership record checksum does not match.')
    require(isinstance(value['data'], dict), 'ownership_invalid', 'Invalid ownership record.')
    return value['data']


def ownership(binding):
    """Inspect only the selected roots; never follow paths stored in a record.

    This is an unlocked snapshot. Absence of Hub records is not a reservation,
    and matching records are not proof that an adapter or external tool is idle.
    """
    try:
        world_control = confined(binding.world, CONTROL)
        client_control = confined(binding.client, CONTROL)
        if not world_control.exists() and not client_control.exists():
            return 'no_hub_records'
        if any(path.exists() and not path.is_dir() for path in (world_control, client_control)):
            return 'invalid'
        if confined(binding.client, CONTROL + '/identity.json').exists() or confined(binding.world, CONTROL + '/claim.json').exists():
            return 'conflict'
        identity_path = confined(binding.world, CONTROL + '/identity.json')
        claim_path = confined(binding.client, CONTROL + '/claim.json')
        if not identity_path.exists():
            return 'incomplete' if claim_path.exists() else 'unrecognized'
        identity = _record(binding.world, 'identity.json')
        if identity.get('kind') == 'synthetic':
            return 'synthetic'
        require(set(identity) == {'schema', 'kind', 'id', 'world_root', 'client_root', 'attachment'}
                and type(identity['schema']) is int and identity['schema'] == 1
                and identity['kind'] == 'metin2sp'
                and isinstance(identity['id'], str) and re.fullmatch(r'[0-9a-f]{32}', identity['id'])
                and identity['attachment'] in ('pending', 'ready'),
                'ownership_invalid', 'Unsupported ownership record.')
        expected_world = os.path.normcase(str(binding.world))
        expected_client = os.path.normcase(str(binding.client))
        if identity['world_root'] != expected_world or identity['client_root'] != expected_client:
            return 'conflict'
        if claim_path.exists():
            claim = _record(binding.client, 'claim.json')
            require(set(claim) == {'schema', 'kind', 'installation', 'world_root', 'client_root'}
                    and type(claim['schema']) is int and claim['schema'] == 1
                    and claim['kind'] == 'metin2sp-client'
                    and isinstance(claim['installation'], str)
                    and re.fullmatch(r'[0-9a-f]{32}', claim['installation']),
                    'ownership_invalid', 'Unsupported client claim.')
            if claim['installation'] != identity['id'] or claim['world_root'] != expected_world or claim['client_root'] != expected_client:
                return 'conflict'
        if identity['attachment'] == 'pending' or any(confined(root, CONTROL + '/active.json').exists()
                                                     for root in (binding.world, binding.client)):
            return 'recovery_required'
        return 'matching_claims' if claim_path.exists() else 'incomplete'
    except (HubError, OSError, ValueError, TypeError):
        return 'invalid'


def probe(selected):
    binding = locate(selected)
    client_files = {name: _file_status(binding.client, name) for name in CLIENT_FILES}
    world_files = {name: _file_status(binding.world, name) for name in WORLD_FILES}
    compose_files = {name: _file_status(binding.world, 'linux-port/docker/' + name) for name in COMPOSE_FILES}
    present = [name for name, status in compose_files.items() if status == 'present']
    if any(status not in ('present', 'missing') for status in compose_files.values()):
        compose_status = 'invalid'
    else:
        compose_status = 'single' if len(present) == 1 else 'ambiguous' if present else 'missing'
    complete = all(status == 'present' for status in (*client_files.values(), *world_files.values())) and compose_status == 'single'
    return {
        'mode': 'read_only', 'layout': 'metin2sp_local_docker',
        'layout_complete': complete,
        'client': {'files': client_files, 'version_label': _version(binding.client, 'client.version')},
        'server': {'files': world_files, 'version_label': _version(binding.world, 'VERSION'),
                   'compose': compose_status},
        'ownership': {'status': ownership(binding), 'snapshot_only': True},
        'compatibility': 'unverified', 'can_install': False,
        'runtime': {'client': 'not_checked', 'server': 'not_checked', 'compiler': 'not_checked',
                    'world_identity': 'not_verified', 'other_managers': 'not_checked'},
        'next_step': 'Real installation requires a verified game adapter and recoverable ownership attachment.'}


def describe(report):
    """Short console presentation; all values come from the sanitized report."""
    print('Game folder layout found: ' + ('required files present.' if report['layout_complete'] else 'incomplete; inspect the file checks.'))
    for component in ('client', 'server'):
        print(component.capitalize() + ' version label: ' + (report[component]['version_label'] or 'unrecognized or missing'))
        for name, status in report[component]['files'].items():
            if status != 'present':
                print('  ' + name + ': ' + status)
    print('Server Compose file: ' + report['server']['compose'])
    labels = {'no_hub_records': 'No Hub ownership records found (not a reservation).',
              'matching_claims': 'Matching ownership records found (snapshot only).',
              'recovery_required': 'An unfinished attachment or operation needs recovery.',
              'conflict': 'Ownership records belong to different targets or installations.',
              'incomplete': 'Ownership records are incomplete; preserve them.',
              'unrecognized': 'An existing Hub directory has unrecognized state; preserve it.',
              'synthetic': 'Synthetic sandbox state cannot authorize game installation.',
              'invalid': 'Ownership records are unsafe, unreadable or invalid; preserve them.'}
    print(labels[report['ownership']['status']])
    print('Game installation is disabled. Build, runtime and external-manager checks are still unverified.')
    print('Read-only inspection finished; no state was created or changed.')
