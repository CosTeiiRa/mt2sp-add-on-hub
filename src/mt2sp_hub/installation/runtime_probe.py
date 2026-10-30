"""Optional, read-only Docker observations. No deployment or compatibility grant."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from ..core.validation import parse_json
from ..errors import HubError

MAX_OUTPUT = 64 * 1024
MAX_CONTAINERS = 32
COMMAND_TIMEOUT = 5
CONTEXT_FORMAT = '{{json (index .Endpoints "docker").Host}}'
# Project labels are compared privately; neither they nor image/container IDs
# enter a report. Never request Config.Env, health logs or the complete object.
CONTAINER_FORMAT = (
    '{"id":{{json .Id}},"image":{{json .Image}},"state":{{json .State.Status}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"oneoff":{{json (index .Config.Labels "com.docker.compose.oneoff")}},'
    '"directory":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},'
    '"files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}}}'
)


class ObservationError(Exception):
    """Only fixed codes cross the command boundary, never raw stderr."""


def _read_command(executable, arguments, environment):
    """Bound both output retained in memory and time, including a stalled CLI."""
    try:
        process = subprocess.Popen(
            [executable, *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False, env=environment,
            cwd=str(Path(executable).parent),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        raise ObservationError('unavailable') from None
    output = []

    def read():
        try:
            output.append(process.stdout.read(MAX_OUTPUT + 1))
        except OSError:
            pass

    reader = threading.Thread(target=read, daemon=True)
    deadline = time.monotonic() + COMMAND_TIMEOUT
    reader.start()
    try:
        reader.join(COMMAND_TIMEOUT)
        if reader.is_alive():
            raise ObservationError('timeout')
        if not output:
            raise ObservationError('unavailable')
        if len(output[0]) > MAX_OUTPUT:
            raise ObservationError('output_limit')
        try:
            result = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise ObservationError('timeout') from None
        if result:
            raise ObservationError('unavailable')
        try:
            return output[0].decode('utf-8').strip()
        except UnicodeError:
            raise ObservationError('invalid_response') from None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        reader.join(2)
        if not reader.is_alive():
            process.stdout.close()


def _json(text):
    try:
        return parse_json(text.encode('utf-8'), MAX_OUTPUT)
    except (HubError, UnicodeError):
        raise ObservationError('invalid_response') from None


def _endpoint(executable, environment):
    # DOCKER_CONTEXT overrides DOCKER_HOST. Context inspection itself is local;
    # do not contact a daemon until the actual endpoint has been checked.
    context = environment.get('DOCKER_CONTEXT')
    host = environment.get('DOCKER_HOST')
    if context or not host:
        if not context:
            context = _read_command(executable, ['context', 'show'], environment)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}', context):
            raise ObservationError('invalid_response')
        host = _json(_read_command(executable, ['context', 'inspect', context,
                                              '--format', CONTEXT_FORMAT], environment))
    # This first runtime profile is local Windows Docker Desktop. Even a TCP
    # loopback endpoint or a remote named pipe requires a separate review.
    if not isinstance(host, str) or not re.fullmatch(r'npipe:////\./pipe/[A-Za-z0-9_.-]+', host):
        raise ObservationError('unsupported_endpoint')
    return host


def _same_path(label, expected):
    # Labels are data, not paths to resolve, open or execute. Accept only the
    # exact normalized selected binding; aliases/overrides stay unverified.
    return isinstance(label, str) and os.path.isabs(label) and os.path.normcase(os.path.normpath(label)) == os.path.normcase(str(expected))


def _containers(text, identifiers):
    records = [_json(line) for line in text.splitlines()]
    fields = {'id', 'image', 'state', 'health', 'project', 'service', 'oneoff', 'directory', 'files'}
    if len(records) != len(identifiers):
        raise ObservationError('invalid_response')
    found = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != fields:
            raise ObservationError('invalid_response')
        if any(not isinstance(record[name], str) for name in fields - {'health'}):
            raise ObservationError('invalid_response')
        if (record['id'] not in identifiers or record['id'] in found
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', record['image'])
                or record['state'] not in ('created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead')
                or record['health'] not in (None, 'healthy', 'starting', 'unhealthy')
                or record['service'] != 'game'):
            raise ObservationError('invalid_response')
        found.add(record['id'])
    return records


def inspect_runtime(binding, compose_name):
    """Return sanitized observations, not a lock, world identity or health receipt."""
    report = {'docker': 'not_checked', 'server': 'not_checked', 'health': 'not_checked',
              'folder_binding': 'unverified', 'image_identity': 'unverified',
              'client': 'not_checked', 'compiler': 'not_checked',
              'world_identity': 'not_verified', 'deployment_revision': 'not_verified',
              'other_managers': 'not_checked', 'snapshot_only': True}
    if compose_name is None:
        report['folder_binding'] = 'unsupported_config'
        return report
    executable = shutil.which('docker.exe' if os.name == 'nt' else 'docker')
    if not executable:
        report['docker'] = 'not_found'
        return report
    environment = dict(os.environ)
    try:
        endpoint = _endpoint(executable, environment)
        # Pin subsequent calls to the inspected endpoint, regardless of a
        # context switch. Do not read Compose/.env or accept package commands.
        for name in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
            environment.pop(name, None)
        prefix = ['--host', endpoint, 'container']
        text = _read_command(executable, [*prefix, 'ls', '--all', '--no-trunc',
                             '--filter', 'label=com.docker.compose.service=game', '--format', '{{.ID}}'], environment)
        identifiers = text.splitlines()
        if len(identifiers) > MAX_CONTAINERS:
            raise ObservationError('output_limit')
        if len(set(identifiers)) != len(identifiers) or any(not re.fullmatch(r'[0-9a-f]{64}', item) for item in identifiers):
            raise ObservationError('invalid_response')
        report['docker'] = 'available'
        if not identifiers:
            report.update(server='not_found', folder_binding='not_found')
            return report
        records = _containers(_read_command(executable, [*prefix, 'inspect', '--format',
                                           CONTAINER_FORMAT, *identifiers], environment), identifiers)
        directory = binding.world / 'linux-port/docker'
        config = directory / compose_name
        candidates = [item for item in records if _same_path(item['directory'], directory)
                      or _same_path(item['files'], config)]
        if not candidates:
            report.update(server='not_found', folder_binding='not_found')
        elif len(candidates) != 1:
            report['folder_binding'] = 'ambiguous'
        else:
            item = candidates[0]
            if (not _same_path(item['directory'], directory) or not _same_path(item['files'], config)
                    or item['oneoff'] != 'False' or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}', item['project'])):
                report['folder_binding'] = 'unsupported_config'
            else:
                report.update(folder_binding='matched', server=item['state'],
                              health=item['health'] or 'not_available', image_identity='observed')
    except ObservationError as exc:
        report['docker'] = str(exc)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        report['docker'] = 'unavailable'
    return report


def describe_runtime(report):
    docker = report['docker']
    messages = {'not_found': 'Docker is not installed or is not on PATH.',
                'unavailable': 'Docker could not be read. Check Docker Desktop and local access.',
                'timeout': 'Docker did not answer in time. Check Docker Desktop and try again.',
                'output_limit': 'Docker returned more data than this probe accepts.',
                'invalid_response': 'Docker returned unsupported status data.',
                'unsupported_endpoint': 'Select a local Docker Desktop context; remote/TCP endpoints are unsupported.'}
    if docker in messages:
        print(messages[docker])
    elif report['folder_binding'] == 'matched':
        print('Server container matches the selected folder: ' + report['server'] + '; health: ' + report['health'] + '.')
        if report['server'] != 'running':
            print('Start the selected server through its normal launcher before a future installation.')
        elif report['health'] != 'healthy':
            print('Wait for the normal launcher to report a healthy server; this probe does not repair it.')
    elif report['folder_binding'] == 'not_found':
        print('No server container matches this folder. Start the selected world through its normal launcher.')
    else:
        print('Server folder association: ' + report['folder_binding'] + '. Select a single standard Compose installation.')
    print('A container status or image ID does not verify the persistent world, compiler or active add-on revision.')
