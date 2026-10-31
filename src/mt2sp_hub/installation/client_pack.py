"""Compose one client root pack from a verified baseline and enabled selection."""
from ..core.validation import digest, parse_json
from ..errors import HubError, require
from .client import prepare_client
from .client_files import MAX_PAIR, PATHS
from .pack_codec import EterPack

STARTUP = b'\n# MT2SP_HUB_STARTUP_V1\nimport mt2sp_hub_bootstrap\nmt2sp_hub_bootstrap.install(GameWindow)\n'


def compose(pack_bytes, config_bytes, packages, expected):
    """Return a verified pair; removal restores original bytes, not a repack.

    Baseline bytes and pins must come from the reviewed official reference or
    its retained baseline objects. Never use an already-modified pack as base.
    This function does not execute embedded game Python or write target files.
    """
    require(isinstance(pack_bytes, dict) and set(pack_bytes) == set(PATHS)
            and all(isinstance(raw, bytes) and raw for raw in pack_bytes.values())
            and sum(map(len, pack_bytes.values())) <= MAX_PAIR,
            'client_pack_limit', 'A bounded official root pack pair is required.')
    require(isinstance(config_bytes, bytes) and len(config_bytes) <= 64 * 1024,
            'client_configuration', 'Local pack configuration exceeds its limit.')
    inputs = {**pack_bytes, 'pack/root.json': config_bytes}
    require(isinstance(expected, dict) and set(expected) == set(inputs)
            and all(digest(raw) == expected[p] for p, raw in inputs.items()),
            'client_baseline', 'Client baseline differs from the reviewed official inputs.')
    try:
        config = parse_json(config_bytes.removeprefix(b'\xef\xbb\xbf'), 64 * 1024)
        require(isinstance(config, dict), 'client_configuration', 'Invalid local pack configuration.')
        baseline = EterPack(pack_bytes[PATHS[0]], pack_bytes[PATHS[1]], config)
        logical = baseline.files()
        members = prepare_client(packages, occupied_paths=set(logical))
        if not members:
            return dict(pack_bytes)
        require('game.py' in logical and b'MT2SP_HUB_STARTUP_V1' not in logical['game.py']
                and b'\x00' not in logical['game.py'],
                'client_startup', 'Official game startup input is missing or already modified.')
        desired = {**logical, **members}
        desired['game.py'] += STARTUP
        index, data = baseline.build(desired)
        require(len(index) + len(data) <= MAX_PAIR, 'client_pack_limit', 'Generated client pack exceeds its limit.')
        checked = EterPack(index, data, config)
        require(checked.files() == desired, 'client_pack_verify', 'Generated client pack did not verify.')
        return dict(zip(PATHS, (index, data)))
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        if isinstance(exc, HubError):
            raise
        raise HubError('client_pack_invalid', 'Client pack could not be composed; check game codec dependencies and the reviewed baseline.') from None
