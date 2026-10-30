import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mt2sp_hub.cli import main
from mt2sp_hub.installation.probe import locate, probe
from mt2sp_hub.installation import runtime_probe as runtime


ENDPOINT = 'npipe:////./pipe/docker_engine'
COMPOSE = 'docker-compose.yml'


class RuntimeProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hub-runtime-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'Klient').mkdir()
        self.directory = self.root / 'Serwer/linux-port/docker'
        self.directory.mkdir(parents=True)
        (self.directory / COMPOSE).write_text('services: {}')
        self.binding = locate(self.root)
        self.directory = self.binding.world / 'linux-port/docker'
        self.record = {'id': '1' * 64, 'image': 'sha256:' + '2' * 64,
                       'state': 'running', 'health': 'healthy', 'project': 'example-world',
                       'service': 'game', 'oneoff': 'False', 'directory': str(self.directory),
                       'files': str(self.directory / COMPOSE)}

    def inspect(self, records=None, *, environment=None, responses=None):
        records = [self.record] if records is None else records
        if responses is None:
            responses = ['example-context', json.dumps(ENDPOINT),
                         '\n'.join(record['id'] for record in records),
                         '\n'.join(json.dumps(record) for record in records)]
        with patch.dict(os.environ, environment or {}, clear=True), \
                patch.object(runtime.shutil, 'which', return_value=sys.executable), \
                patch.object(runtime, '_read_command', side_effect=responses) as command:
            result = runtime.inspect_runtime(self.binding, COMPOSE)
        return result, command

    def test_matching_running_container_is_not_world_or_deployment_verification(self):
        result, command = self.inspect()
        self.assertEqual(result['folder_binding'], 'matched')
        self.assertEqual(result['server'], 'running')
        self.assertEqual(result['health'], 'healthy')
        self.assertEqual(result['image_identity'], 'observed')
        self.assertEqual(result['world_identity'], 'not_verified')
        self.assertEqual(result['deployment_revision'], 'not_verified')
        self.assertEqual(result['compiler'], 'not_checked')
        self.assertTrue(result['snapshot_only'])
        rendered = json.dumps(result)
        for private in (str(self.root), self.record['id'], self.record['image'], self.record['project']):
            self.assertNotIn(private, rendered)
        commands = [call.args[1] for call in command.call_args_list]
        self.assertEqual(commands[0], ['context', 'show'])
        self.assertEqual(commands[2][:4], ['--host', ENDPOINT, 'container', 'ls'])
        self.assertEqual(commands[3][:4], ['--host', ENDPOINT, 'container', 'inspect'])
        self.assertNotIn('.Config.Env', runtime.CONTAINER_FORMAT)
        self.assertNotIn('.State.Health.Log', runtime.CONTAINER_FORMAT)

    def test_remote_and_tcp_endpoints_are_rejected_before_daemon_contact(self):
        for host in ('tcp://127.0.0.1:2375', 'ssh://example.invalid', 'unix:///var/run/docker.sock',
                     'npipe:////remote/pipe/docker_engine', 'npipe:////./pipe/name/extra'):
            with self.subTest(host=host):
                result, command = self.inspect(responses=['example', json.dumps(host)])
                self.assertEqual(result['docker'], 'unsupported_endpoint')
                self.assertEqual(command.call_count, 2)
                self.assertNotIn(host, json.dumps(result))

    def test_explicit_host_and_context_precedence_and_pinned_environment(self):
        result, command = self.inspect(environment={'DOCKER_HOST': ENDPOINT}, responses=[''])
        self.assertEqual(result['docker'], 'available')
        self.assertEqual(command.call_count, 1)
        result, command = self.inspect(environment={'DOCKER_CONTEXT': 'example',
                                                    'DOCKER_HOST': 'ssh://private-endpoint',
                                                    'DOCKER_TLS_VERIFY': '1'},
                                       responses=[json.dumps(ENDPOINT), ''])
        self.assertEqual(result['docker'], 'available')
        self.assertEqual(command.call_args_list[0].args[1][:3], ['context', 'inspect', 'example'])
        daemon_environment = command.call_args_list[1].args[2]
        for name in ('DOCKER_CONTEXT', 'DOCKER_HOST', 'DOCKER_TLS_VERIFY'):
            self.assertNotIn(name, daemon_environment)

    def test_context_option_injection_and_invalid_host_types_are_rejected(self):
        for context in ('--host=private', 'bad\ncontext', '', 'x' * 129):
            result, command = self.inspect(responses=[context])
            self.assertEqual(result['docker'], 'invalid_response')
            self.assertEqual(command.call_count, 1)
        result, _ = self.inspect(responses=['example', '{"Host":"private"}'])
        self.assertEqual(result['docker'], 'unsupported_endpoint')

    def test_absent_cli_and_ambiguous_compose_do_not_launch_commands(self):
        with patch.object(runtime.shutil, 'which', return_value=None), \
                patch.object(runtime, '_read_command') as command:
            self.assertEqual(runtime.inspect_runtime(self.binding, COMPOSE)['docker'], 'not_found')
            self.assertEqual(runtime.inspect_runtime(self.binding, None)['folder_binding'], 'unsupported_config')
            command.assert_not_called()

    def test_no_container_and_foreign_world_are_not_selected(self):
        result, command = self.inspect([])
        self.assertEqual(result['server'], 'not_found')
        self.assertEqual(command.call_count, 3)
        foreign = dict(self.record, directory='/invented/other-world', files='/invented/other-world/compose.yaml')
        result, _ = self.inspect([foreign])
        self.assertEqual(result['folder_binding'], 'not_found')
        self.assertEqual(result['image_identity'], 'unverified')

    def test_multiple_containers_for_selected_folder_are_ambiguous(self):
        result, _ = self.inspect([self.record, dict(self.record, id='3' * 64)])
        self.assertEqual(result['folder_binding'], 'ambiguous')
        self.assertEqual(result['server'], 'not_checked')

    def test_other_worlds_do_not_hide_the_selected_one(self):
        foreign = dict(self.record, id='3' * 64, directory='/invented/other', files='/invented/other/compose.yaml')
        result, _ = self.inspect([foreign, self.record])
        self.assertEqual(result['folder_binding'], 'matched')

    def test_overrides_mismatched_directory_and_oneoff_are_not_supported(self):
        for changes in ({'files': self.record['files'] + ',/invented/override.yml'},
                        {'directory': '/invented/other'}, {'oneoff': 'True'}, {'project': ''}):
            with self.subTest(changes=changes):
                result, _ = self.inspect([dict(self.record, **changes)])
                self.assertEqual(result['folder_binding'], 'unsupported_config')
                self.assertEqual(result['server'], 'not_checked')

    def test_stopped_unhealthy_and_missing_health_are_distinct(self):
        for state, health in (('exited', None), ('running', 'unhealthy'), ('running', 'starting'), ('paused', 'healthy')):
            result, _ = self.inspect([dict(self.record, state=state, health=health)])
            self.assertEqual(result['server'], state)
            self.assertEqual(result['health'], health or 'not_available')
            self.assertEqual(result['deployment_revision'], 'not_verified')

    def test_invalid_inspection_and_identifier_responses_fail_closed(self):
        for output in ('{}', 'not-json-private-sentinel', json.dumps([self.record]),
                       json.dumps(dict(self.record, image='mutable:tag')),
                       json.dumps(dict(self.record, id='4' * 64)),
                       json.dumps(dict(self.record, state='private-state-sentinel')),
                       json.dumps(dict(self.record, health={'Output': 'private-log-sentinel'})),
                       json.dumps(self.record) + '\n' + json.dumps(self.record)):
            result, _ = self.inspect(responses=['example', json.dumps(ENDPOINT), self.record['id'], output])
            self.assertEqual(result['docker'], 'invalid_response')
            self.assertEqual(result['folder_binding'], 'unverified')
            self.assertNotIn('sentinel', json.dumps(result))
        for identifiers in ('--option', '1' * 64 + '\n' + '1' * 64):
            result, command = self.inspect(responses=['example', json.dumps(ENDPOINT), identifiers])
            self.assertEqual(result['docker'], 'invalid_response')
            self.assertEqual(command.call_count, 3)

    def test_inventory_limit_and_command_failures_are_sanitized(self):
        identifiers = '\n'.join(format(number, '064x') for number in range(runtime.MAX_CONTAINERS + 1))
        result, command = self.inspect(responses=['example', json.dumps(ENDPOINT), identifiers])
        self.assertEqual(result['docker'], 'output_limit')
        self.assertEqual(command.call_count, 3)
        for error in (runtime.ObservationError('timeout'), runtime.ObservationError('unavailable'),
                      OSError('private-error-sentinel')):
            result, _ = self.inspect(responses=[error])
            self.assertIn(result['docker'], ('timeout', 'unavailable'))
            self.assertNotIn('private-error', json.dumps(result))

    def test_cli_opt_in_keeps_game_files_unchanged_and_reports_private_data_safely(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*'))
        with patch.object(runtime, '_read_command', side_effect=AssertionError('Default probe must stay offline')):
            self.assertNotIn('docker', probe(self.root)['runtime'])
        result, _ = self.inspect()
        for suffix in ([], ['--json']):
            output = io.StringIO()
            with patch('mt2sp_hub.installation.probe.inspect_runtime', return_value=result) as inspect, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(main(['probe', str(self.root), '--runtime', *suffix]), 0)
                inspect.assert_called_once_with(self.binding, COMPOSE)
            self.assertNotIn(str(self.root), output.getvalue())
            self.assertNotIn(self.record['project'], output.getvalue())
            if suffix:
                self.assertFalse(json.loads(output.getvalue())['can_install'])
            else:
                self.assertIn('Server container matches', output.getvalue())
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*')))


class CommandBoundaryTests(unittest.TestCase):
    def run_python(self, script):
        return runtime._read_command(sys.executable, ['-c', script], dict(os.environ))

    def test_output_and_stderr_are_not_mixed(self):
        self.assertEqual(self.run_python('import sys; print("ok"); sys.stderr.write("private-sentinel")'), 'ok')
        with self.assertRaises(runtime.ObservationError) as caught:
            self.run_python('import sys; sys.stderr.write("private-sentinel"); sys.exit(1)')
        self.assertEqual(str(caught.exception), 'unavailable')

    def test_output_limit_includes_a_process_that_keeps_writing(self):
        with self.assertRaises(runtime.ObservationError) as caught:
            self.run_python('import os\nwhile True: os.write(1, b"x" * 65536)')
        self.assertEqual(str(caught.exception), 'output_limit')

    def test_exact_output_boundary_and_one_byte_more(self):
        self.assertEqual(len(self.run_python('import os; os.write(1, b"x" * 65536)')), runtime.MAX_OUTPUT)
        with self.assertRaises(runtime.ObservationError) as caught:
            self.run_python('import os; os.write(1, b"x" * 65537)')
        self.assertEqual(str(caught.exception), 'output_limit')

    def test_timeout_terminates_the_command(self):
        processes = []
        original = subprocess.Popen

        def start(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process

        with patch.object(runtime, 'COMMAND_TIMEOUT', 0.2), patch.object(runtime.subprocess, 'Popen', start):
            with self.assertRaises(runtime.ObservationError) as caught:
                self.run_python('import time; time.sleep(30)')
        self.assertEqual(str(caught.exception), 'timeout')
        self.assertIsNotNone(processes[0].poll())

    def test_invalid_utf8_is_not_echoed(self):
        with self.assertRaises(runtime.ObservationError) as caught:
            self.run_python('import os; os.write(1, b"\\xffprivate-sentinel")')
        self.assertEqual(str(caught.exception), 'invalid_response')
