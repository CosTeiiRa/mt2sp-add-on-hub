"""Prepare original client pack members without patching or executing a game."""
import base64
from importlib.resources import files
import json
import posixpath
import re

from ..core.resolver import resolve
from ..core.validation import MAX_PACKAGES, MAX_SELECTED_ARCHIVES, MAX_TOTAL, path_set
from ..errors import HubError, require


HOST_MODULES = {
    'mt2sp_hub_bootstrap.py': 'client_bootstrap.py',
    'mt2sp_hub_hooks.py': 'client_hooks.py',
    'mt2sp_hub_runtime.py': 'client_runtime.py',
}
PAYLOAD_MODULE = 'mt2sp_hub_payload.py'
# Base64 plus bounded package/path metadata fit within twice the raw budget.
# These generated host members are not additional author package resources.
MAX_BUNDLE = 2 * MAX_TOTAL
PYTHON_PATH = re.compile(r'(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py')


def prepare_client(packages, *, occupied_paths):
    """Return deterministic pack-member bytes for an explicitly enabled set.

    occupied_paths is the complete reviewed pack baseline, excluding previous
    Hub members only after the coordinator proves their ownership. No startup
    patch, filesystem write, build compatibility or server validation happens.
    """
    require(isinstance(occupied_paths, (set, frozenset)), 'client_inventory',
            'Provide the verified client pack inventory.')
    selected, archive_bytes = [], 0
    for package in packages:
        require(len(selected) < MAX_PACKAGES, 'package_limit', 'Too many selected packages.')
        archive_bytes += len(package.raw)
        require(archive_bytes <= MAX_SELECTED_ARCHIVES, 'archive_budget',
                'Selected archives exceed the shared byte limit.')
        selected.append(package)
    order, outputs, owners = resolve(selected, capabilities={'client.module', 'server.quest'})
    manifests = {}
    for package in selected:
        manifest = package.manifest
        manifests[manifest['id']] = manifest
    for manifest in manifests.values():
        for kind, component in manifest['components'].items():
            expected = 'client.module' if kind == 'client' else 'server.quest'
            require(component['capabilities'] == [expected], 'client_profile',
                    'Game staging requires client.module or server.quest on its matching component.')
    client_ids = {ident for ident in order if 'client' in manifests[ident]['components']}
    if not client_ids:
        return {}  # Removing the last client module needs no resident loader.
    member_names = set(HOST_MODULES) | {PAYLOAD_MODULE}
    module_names = {name[:-3] for name in member_names}
    # Baseline names may contain game-specific characters. Compare their case
    # and ancestry to our fixed names, without interpreting them as disk paths.
    for occupied in occupied_paths:
        require(isinstance(occupied, str), 'client_inventory', 'Invalid client pack inventory.')
        folded = posixpath.normpath(occupied.replace('\\', '/')).casefold().lstrip('/')
        require(folded.split('/')[0].split('.')[0] not in module_names,
                'client_collision', 'A generated Hub module collides with the client baseline.')
    path_set(member_names)
    dependencies, payload = {}, []
    for ident in order:
        required = set()
        for dependency in manifests[ident]['requires']:
            required.update(dependencies[dependency])
            if dependency in client_ids:
                required.add(dependency)
        dependencies[ident] = required
        if ident not in client_ids:
            continue
        prefix = 'client/' + ident + '/'
        sources = {}
        for path, owner in owners.items():
            if owner != ident or not path.startswith('client/'):
                continue
            require(path.startswith(prefix) and PYTHON_PATH.fullmatch(path[len(prefix):]),
                    'client_source', 'Client modules require PACKAGE_ID/main.py and local Python helpers.')
            sources[path[len(prefix):]] = base64.b64encode(outputs[path]).decode('ascii')
        require('main.py' in sources, 'client_entry', 'Client modules require main.py.')
        payload.append([ident, sorted(required), sources])
    # Only lists and ASCII strings/dictionaries: this JSON is also Python 2.7
    # syntax. Source bytes are data until Runtime.load compiles each module.
    data = ('ADDONS = ' + json.dumps(payload, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':')) + '\n').encode('ascii')
    try:
        members = {target: files('mt2sp_hub').joinpath(source).read_bytes()
                   for target, source in HOST_MODULES.items()}
    except OSError:
        raise HubError('client_host_missing', 'Required Hub runtime source is unavailable; repair the Hub installation.') from None
    members[PAYLOAD_MODULE] = data
    require(sum(map(len, members.values())) <= MAX_BUNDLE, 'client_bundle_limit',
            'Generated client members exceed the staging byte limit.')
    return members
