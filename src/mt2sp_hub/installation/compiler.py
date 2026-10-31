"""Fixed, isolated quest preparation. No world mounts, deployment or restart."""
from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid

from ..core.validation import (MAX_FILE, MAX_FILES, MAX_TOTAL, SHA, digest,
                               encode, identifier, logical_path, parse_json, path_set)
from ..errors import HubError, require
from .quests import _source_name, validate_artifacts
from .runtime_probe import ObservationError, _endpoint


MAX_COMPILER = 32 * 1024 * 1024
MAX_WIRE = MAX_TOTAL + 8 * 1024 * 1024
CONTAINER_SECONDS = 30
COMMAND_SECONDS = 45
LABEL = 'org.mt2sp.hub.compile'
RECIPE = 'qc-ascii-v1'
IMAGE_FORMAT = '{"id":{{json .Id}},"os":{{json .Os}},"volumes":{{json .Config.Volumes}}}'
SCRIPT = '''set -eu
umask 077
ulimit -c 0
tar -xf -
./qc "$1.quest" > compiler.log 2>&1
tar --format=ustar -cf - object
'''


@dataclass(frozen=True)
class CompilerProfile:
    """Reviewed caller-owned pins, never fields supplied by an add-on manifest."""
    image: str
    compiler_sha256: str
    functions_sha256: str


def _run(executable, arguments, environment, *, input_bytes=None, timeout=5, limit=64 * 1024):
    """Bound binary output and CLI lifetime; never include stderr in errors."""
    try:
        with tempfile.TemporaryFile() as incoming:
            if input_bytes is not None:
                incoming.write(input_bytes)
                incoming.seek(0)
            process = subprocess.Popen(
                [executable, *arguments], stdin=incoming if input_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
                env=environment, cwd=str(Path(executable).parent),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            output = []
            def read():
                try:
                    output.append(process.stdout.read(limit + 1))
                except OSError:
                    pass
            reader = threading.Thread(target=read, daemon=True)
            deadline = time.monotonic() + timeout
            try:
                reader.start()
                reader.join(timeout)
                require(not reader.is_alive(), 'compiler_timeout', 'Compiler command did not finish in time.')
                require(output, 'compiler_unavailable', 'Compiler command output could not be read.')
                require(len(output[0]) <= limit, 'compiler_output_limit', 'Compiler command exceeded its output limit.')
                try:
                    code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise HubError('compiler_timeout', 'Compiler command did not finish in time.') from None
                return code, output[0]
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
                if reader.ident is not None:
                    reader.join(2)
                if not reader.is_alive():
                    process.stdout.close()
    except (OSError, subprocess.SubprocessError, RuntimeError):
        raise HubError('compiler_unavailable', 'Could not run the local compiler command.') from None


def _inputs(quest, compiler, functions):
    """Only three fixed regular files enter the container, through stdin."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, raw in (('qc', compiler), ('quest_functions', functions.replace(b'\r\n', b'\n')),
                          (quest.name + '.quest', quest.source)):
            member = tarfile.TarInfo(name)
            member.mode = 0o555 if name == 'qc' else 0o444
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def _artifacts(quest, raw, occupied_paths):
    """Read bounded tar data without extracting any archive path to disk."""
    require(len(raw) <= MAX_WIRE and len(raw) >= 1024 and len(raw) % 512 == 0
            and raw[-1024:] == b'\0' * 1024,
            'compiler_archive', 'Compiler returned an invalid or oversized artifact archive.')
    files, directories, seen, total = {}, [], set(), 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
            for member in archive:
                require(len(seen) < MAX_FILES * 3 + 1, 'compiler_archive', 'Too many compiler archive entries.')
                path = logical_path(member.name.rstrip('/') if member.isdir() else member.name)
                require(path.casefold() not in seen and not member.pax_headers and not member.issparse(),
                        'compiler_archive', 'Duplicate or extended compiler archive entry.')
                seen.add(path.casefold())
                require(path == 'object' or path.startswith('object/'), 'compiler_archive', 'Unexpected compiler archive root.')
                if member.isdir():
                    parts = path.split('/')[1:]
                    require(member.size == 0 and len(parts) <= 2 and all(re.fullmatch(r'[A-Za-z0-9_]{1,64}', part) for part in parts)
                            and (not parts or parts[0] != 'state' or len(parts) == 1),
                            'compiler_archive', 'Unexpected compiler output directory.')
                    directories.append(path + '/')
                    continue
                require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and 0 <= member.size <= MAX_FILE
                        and len(files) < MAX_FILES and total + member.size <= MAX_TOTAL,
                        'compiler_archive', 'Compiler output must contain only bounded regular files.')
                stream = archive.extractfile(member)
                with stream:
                    content = stream.read(member.size + 1)
                require(len(content) == member.size, 'compiler_archive', 'Compiler artifact data was truncated.')
                files[path] = content
                total += len(content)
        require(all(any(path.startswith(directory) for path in files) for directory in directories),
                'compiler_archive', 'Compiler emitted an unused directory.')
        return validate_artifacts(quest, files, occupied_paths=occupied_paths)
    except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
        if isinstance(exc, HubError):
            raise
        raise HubError('compiler_archive', 'Compiler artifact archive could not be read.') from None


def _cleanup(executable, prefix, environment, token, *, name_prefix='mt2sp-hub-compile-', label=LABEL):
    """Remove only this operation's exact name AND random ownership label."""
    name = name_prefix + token
    query = [*prefix, 'container', 'ls', '--all', '--no-trunc', '--filter', 'name=^/' + name + '$',
             '--filter', 'label=' + label + '=' + token, '--format', '{{.ID}}']
    try:
        code, raw = _run(executable, query, environment)
        require(code == 0, 'compiler_cleanup', 'Could not inspect compiler cleanup.')
        identifiers = raw.decode('ascii').splitlines()
        require(len(identifiers) <= 1 and all(re.fullmatch(r'[0-9a-f]{64}', ident) for ident in identifiers),
                'compiler_cleanup', 'Unexpected compiler cleanup response.')
        if identifiers:
            code, _ = _run(executable, [*prefix, 'container', 'rm', '--force', '--volumes', identifiers[0]], environment)
            if code:
                # Auto-removal can race the explicit cleanup. Confirm absence.
                code, raw = _run(executable, query, environment)
                require(code == 0 and not raw.strip(), 'compiler_cleanup', 'Compiler cleanup is unconfirmed.')
    except (HubError, UnicodeError):
        raise HubError('compiler_cleanup', 'Could not confirm temporary compiler cleanup; check local Docker before retrying.') from None


def compile_quest(quest, *, profile, compiler, functions, occupied_paths):
    """Return (captured artifacts, private preparation receipt), never deploy.

    Use a source from collect_quests and a reviewed compiler profile. Observing
    hashes from arbitrary installed inputs is not how a supported profile is
    established. Official inventories and full selection checks are caller gates.
    """
    identifier(quest.package_id)
    name, normalized = _source_name(quest.source)
    require(name == quest.name and normalized == quest.source
            and name.startswith(quest.package_id.replace('.', '_').replace('-', '_') + '_'),
            'quest_identity', 'Compile a normalized, preflighted quest source.')
    require(isinstance(profile, CompilerProfile) and isinstance(profile.image, str)
            and re.fullmatch(r'sha256:[0-9a-f]{64}', profile.image)
            and all(isinstance(value, str) and SHA.fullmatch(value)
                    for value in (profile.compiler_sha256, profile.functions_sha256)),
            'compiler_profile', 'A reviewed exact compiler/image profile is required.')
    require(isinstance(compiler, bytes) and 0 < len(compiler) <= MAX_COMPILER
            and isinstance(functions, bytes) and 0 < len(functions) <= MAX_FILE,
            'compiler_inputs', 'Compiler inputs are missing or exceed their limits.')
    require(digest(compiler) == profile.compiler_sha256 and digest(functions) == profile.functions_sha256,
            'compiler_changed', 'Compiler inputs no longer match the reviewed profile.')
    require(isinstance(occupied_paths, (set, frozenset)), 'quest_inventory', 'Provide the verified occupied artifact paths.')
    path_set([*occupied_paths, 'object/state/' + quest.name])
    occupied_paths = frozenset(occupied_paths)
    executable = shutil.which('docker.exe' if os.name == 'nt' else 'docker')
    require(executable is not None, 'compiler_unavailable', 'Local Docker is required for isolated quest compilation.')
    environment = dict(os.environ)
    try:
        endpoint = _endpoint(executable, environment)
    except ObservationError:
        raise HubError('compiler_endpoint', 'Select an available local Windows Docker Desktop endpoint.') from None
    for key in ('DOCKER_CONTEXT', 'DOCKER_HOST', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        environment.pop(key, None)
    prefix = ['--host', endpoint]
    code, raw = _run(executable, [*prefix, 'image', 'inspect', profile.image, '--format', IMAGE_FORMAT], environment)
    try:
        image = parse_json(raw, 64 * 1024)
        require(code == 0 and isinstance(image, dict) and set(image) == {'id', 'os', 'volumes'}
                and image['id'] == profile.image and image['os'] == 'linux'
                and image['volumes'] in (None, {}, {'/opt/metin2/var': {}}),
                'compiler_image', 'Compiler runtime image is absent or has an unsupported layout.')
    except HubError:
        raise HubError('compiler_image', 'Compiler runtime image is absent or has an unsupported layout.') from None
    token = uuid.uuid4().hex
    arguments = [*prefix, 'run', '--rm', '--pull=never', '--interactive',
                 '--name', 'mt2sp-hub-compile-' + token, '--label', LABEL + '=' + token,
                 '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                 '--user', '65534:65534', '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
                 '--tmpfs', '/work:rw,exec,nosuid,nodev,size=128m,mode=1777',
                 '--tmpfs', '/opt/metin2/var:rw,noexec,nosuid,nodev,size=1m',
                 '--workdir', '/work', '--entrypoint', '/usr/bin/timeout', profile.image,
                 '--signal=KILL', str(CONTAINER_SECONDS), '/bin/sh', '-c', SCRIPT, 'hub-compile', quest.name]
    try:
        code, raw = _run(executable, arguments, environment, input_bytes=_inputs(quest, compiler, functions),
                         timeout=COMMAND_SECONDS, limit=MAX_WIRE)
        require(code == 0, 'compiler_failed', 'Quest compilation failed; the active deployment was not changed.')
        artifacts = _artifacts(quest, raw, occupied_paths)
    finally:
        _cleanup(executable, prefix, environment, token)
    inventory = {path: {'sha256': digest(value), 'bytes': len(value)} for path, value in artifacts.items()}
    receipt = {'schema': 1, 'kind': 'quest-preparation', 'recipe': RECIPE, 'package_id': quest.package_id,
               'quest': quest.name, 'source_sha256': quest.sha256, 'image': profile.image,
               'compiler_sha256': profile.compiler_sha256, 'functions_sha256': profile.functions_sha256,
               'artifacts': inventory, 'artifact_sha256': digest(encode(inventory))}
    return artifacts, receipt
