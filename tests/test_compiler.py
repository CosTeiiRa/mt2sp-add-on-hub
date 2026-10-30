import io
import json
import os
import subprocess
import sys
import tarfile
import time
import unittest
from unittest.mock import patch

from mt2sp_hub.core.validation import digest, encode
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation import compiler as qc
from mt2sp_hub.installation.quests import QuestSource
from mt2sp_hub.installation.runtime_probe import ObservationError


NAME = 'example_hello_greeting'
QUEST = QuestSource('example.hello', NAME, ('quest ' + NAME + ' begin state start begin when login begin chat("Hello") end end end\n').encode())
COMPILER = b'original synthetic compiler bytes; never executed by Docker in CI'
FUNCTIONS = b'chat\r\nsay\r\n'
PROFILE = qc.CompilerProfile('sha256:' + '1' * 64, digest(COMPILER), digest(FUNCTIONS))
ENDPOINT = 'npipe:////./pipe/docker_engine'
TOKEN = '2' * 32
FILES = {'object/state/' + NAME: b'original state', 'object/notarget/login/' + NAME + '.start': b'original handler'}


def tar_bytes(entries=None):
    entries = list(FILES.items()) if entries is None else entries
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, raw in entries:
            if isinstance(name, tarfile.TarInfo):
                member = name
            else:
                member = tarfile.TarInfo(name)
                member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw) if raw else None)
    return output.getvalue()


def image_reply(**changes):
    image = {'id': PROFILE.image, 'os': 'linux', 'volumes': {'/opt/metin2/var': {}}}
    image.update(changes)
    return 0, json.dumps(image).encode()


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.responses = [image_reply(), (0, tar_bytes()), (0, b'')]
        for mocked in (patch.object(qc.shutil, 'which', return_value=sys.executable),
                       patch.object(qc, '_endpoint', return_value=ENDPOINT),
                       patch.object(qc.uuid, 'uuid4', return_value=type('Token', (), {'hex': TOKEN})()),
                       patch.object(qc, '_run', side_effect=self.command)):
            mocked.start()
            self.addCleanup(mocked.stop)

    def command(self, executable, arguments, environment, **kwargs):
        self.commands.append((arguments, environment, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def compile(self, **changes):
        values = dict(profile=PROFILE, compiler=COMPILER, functions=FUNCTIONS, occupied_paths=set())
        values.update(changes)
        return qc.compile_quest(QUEST, **values)

    def error(self, code, operation=None):
        with self.assertRaises(HubError) as caught:
            (operation or self.compile)()
        self.assertEqual(caught.exception.code, code)
        return str(caught.exception)

    def test_success_captures_artifacts_and_exact_preparation_evidence(self):
        files, receipt = self.compile()
        self.assertEqual(files, FILES)
        self.assertEqual(receipt['kind'], 'quest-preparation')
        self.assertEqual(receipt['source_sha256'], QUEST.sha256)
        self.assertEqual(receipt['compiler_sha256'], digest(COMPILER))
        self.assertEqual(receipt['functions_sha256'], digest(FUNCTIONS))
        self.assertEqual(receipt['artifact_sha256'], digest(encode(receipt['artifacts'])))
        self.assertEqual(receipt['artifacts'], {path: {'sha256': digest(raw), 'bytes': len(raw)} for path, raw in FILES.items()})
        self.assertNotIn(TOKEN, json.dumps(receipt))
        self.assertEqual(len(self.commands), 3)

    def test_recipe_has_no_host_mount_pull_world_command_or_package_shell(self):
        with patch.dict(os.environ, {'DOCKER_HOST': 'private', 'DOCKER_CONTEXT': 'private', 'DOCKER_TLS_VERIFY': '1'}):
            self.compile()
        args, environment, options = self.commands[1]
        self.assertEqual(args[:3], ['--host', ENDPOINT, 'run'])
        for key, value in (('--network', 'none'), ('--user', '65534:65534'), ('--entrypoint', '/usr/bin/timeout'),
                           ('--memory', '256m'), ('--memory-swap', '256m'), ('--pids-limit', '64'), ('--cpus', '1')):
            self.assertEqual(args[args.index(key) + 1], value)
        for flag in ('--rm', '--read-only', '--pull=never'):
            self.assertIn(flag, args)
        for forbidden in ('--mount', '-v', '--volume', 'build', 'exec', 'restart', 'compose'):
            self.assertNotIn(forbidden, args)
        self.assertEqual(args[-1], QUEST.name)
        self.assertNotIn(QUEST.source.decode(), args)
        self.assertEqual(options['limit'], qc.MAX_WIRE)
        self.assertEqual(options['timeout'], qc.COMMAND_SECONDS)
        self.assertFalse(set(environment) & {'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY'})
        with tarfile.open(fileobj=io.BytesIO(options['input_bytes']), mode='r:') as archive:
            self.assertEqual(archive.getnames(), ['qc', 'quest_functions', NAME + '.quest'])
            self.assertEqual(archive.extractfile('qc').read(), COMPILER)
            self.assertEqual(archive.extractfile('quest_functions').read(), b'chat\nsay\n')
            self.assertEqual(archive.extractfile(NAME + '.quest').read(), QUEST.source)
            self.assertTrue(all(member.isfile() for member in archive))

    def test_changed_inputs_invalid_profile_and_bounds_fail_before_docker(self):
        for changes, code in (({'compiler': COMPILER + b'changed'}, 'compiler_changed'),
                              ({'functions': FUNCTIONS + b'changed'}, 'compiler_changed'),
                              ({'compiler': b''}, 'compiler_inputs'),
                              ({'functions': bytearray(FUNCTIONS)}, 'compiler_inputs'),
                              ({'profile': qc.CompilerProfile('latest', digest(COMPILER), digest(FUNCTIONS))}, 'compiler_profile')):
            self.error(code, lambda: self.compile(**changes))
        with patch.object(qc, 'MAX_COMPILER', len(COMPILER) - 1):
            self.error('compiler_inputs')
        self.assertEqual(self.commands, [])

    def test_known_ownership_collision_fails_before_docker(self):
        self.error('path_collision', lambda: self.compile(occupied_paths={'object/state/' + NAME}))
        self.assertEqual(self.commands, [])

    def test_unpreflighted_identity_and_line_endings_are_refused(self):
        for quest in (QuestSource('example.hello', NAME + ';bad', QUEST.source),
                      QuestSource('example.other', NAME, QUEST.source),
                      QuestSource('example.hello', NAME, QUEST.source.replace(b'\n', b'\r\n'))):
            self.error('quest_identity', lambda: qc.compile_quest(quest, profile=PROFILE, compiler=COMPILER,
                                                                 functions=FUNCTIONS, occupied_paths=set()))
        self.assertEqual(self.commands, [])

    def test_unavailable_docker_and_remote_endpoint_do_not_start_container(self):
        with patch.object(qc.shutil, 'which', return_value=None):
            self.error('compiler_unavailable')
        with patch.object(qc, '_endpoint', side_effect=ObservationError('private endpoint')):
            self.assertNotIn('private endpoint', self.error('compiler_endpoint'))
        self.assertEqual(self.commands, [])

    def test_wrong_image_os_or_unreviewed_volume_never_starts_container(self):
        for reply in (image_reply(id='sha256:' + '3' * 64), image_reply(os='windows'),
                      image_reply(volumes={'/unknown-volume': {}}), (1, b'private failure'), (0, b'{}')):
            self.responses = [reply]
            self.error('compiler_image')
        self.assertTrue(all('run' not in args for args, _, _ in self.commands))

    def test_nonzero_compiler_never_accepts_even_valid_artifacts(self):
        self.responses[1] = (1, tar_bytes())
        self.error('compiler_failed')
        self.assertIn('ls', self.commands[-1][0])

    def test_timeout_and_overflow_always_attempt_owned_cleanup(self):
        for code in ('compiler_timeout', 'compiler_output_limit'):
            self.responses = [image_reply(), HubError(code, 'fixed failure'), (0, b'')]
            self.error(code)
            self.assertIn('ls', self.commands[-1][0])

    def test_cleanup_removes_only_the_filtered_container_id(self):
        ident = '4' * 64
        self.responses[-1:] = [(0, (ident + '\n').encode()), (0, b'')]
        self.compile()
        query = self.commands[-2][0]
        self.assertIn('name=^/mt2sp-hub-compile-' + TOKEN + '$', query)
        self.assertIn('label=' + qc.LABEL + '=' + TOKEN, query)
        self.assertEqual(self.commands[-1][0], ['--host', ENDPOINT, 'container', 'rm', '--force', '--volumes', ident])

    def test_auto_removal_race_is_confirmed_by_absence(self):
        self.responses[-1:] = [(0, ('4' * 64).encode()), (1, b''), (0, b'')]
        self.compile()
        self.assertIn('ls', self.commands[-1][0])

    def test_cleanup_failure_suppresses_otherwise_valid_result(self):
        for response in ((1, b'private docker error'), (0, b'not-an-id'),
                         (0, (('4' * 64) + '\n' + ('5' * 64)).encode()),
                         HubError('compiler_timeout', 'private timeout')):
            self.responses = [image_reply(), (0, tar_bytes()), response]
            self.assertNotIn('private', self.error('compiler_cleanup'))
            self.assertNotIn('rm', self.commands[-1][0])

    def test_unexpected_artifacts_are_rejected_and_cleanup_still_runs(self):
        self.responses[1] = (0, tar_bytes([*FILES.items(), ('object/state/unowned', b'wrong')]))
        self.error('quest_artifact')
        self.assertIn('ls', self.commands[-1][0])


class ArtifactTransportTests(unittest.TestCase):
    def read(self, raw, occupied_paths=frozenset()):
        return qc._artifacts(QUEST, raw, occupied_paths)

    def test_directories_and_empty_dialog_condition_are_supported(self):
        root = tarfile.TarInfo('object/')
        root.type = tarfile.DIRTYPE
        dialog = 'object/12345/chat/' + NAME + '.start.0.'
        entries = [(root, b''), *FILES.items(), (dialog + 'arg', b'label'),
                   (dialog + 'when', b''), (dialog + 'script', b'original dialog')]
        self.assertEqual(self.read(tar_bytes(entries))[dialog + 'when'], b'')

    def test_traversal_links_devices_duplicates_and_unused_directories_fail(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            member = tarfile.TarInfo('object/notarget/login/' + NAME + '.other')
            member.type, member.linkname = kind, 'private-target'
            with self.assertRaises(HubError):
                self.read(tar_bytes([*FILES.items(), (member, b'')]))
        directory = tarfile.TarInfo('object/unused')
        directory.type = tarfile.DIRTYPE
        for extra in (('../outside', b'bad'), ('object/../../outside', b'bad'),
                      next(iter(FILES.items())), (directory, b'')):
            with self.assertRaises(HubError):
                self.read(tar_bytes([*FILES.items(), extra]))

    def test_malformed_truncated_and_oversized_transport_fails(self):
        raw = tar_bytes()
        for bad in (b'not tar', raw[:-1], b'x' * 1024, b'\0' * 1024):
            with self.assertRaises(HubError):
                self.read(bad)
        with patch.object(qc, 'MAX_WIRE', len(raw) - 1), self.assertRaises(HubError):
            self.read(raw)
        with patch.object(qc, 'MAX_FILE', 1), self.assertRaises(HubError):
            self.read(raw)
        with patch.object(qc, 'MAX_TOTAL', 1), self.assertRaises(HubError):
            self.read(raw)

    def test_incomplete_groups_and_occupied_paths_use_shared_validator(self):
        dialog = 'object/12345/chat/' + NAME + '.start.0.arg'
        with self.assertRaises(HubError) as caught:
            self.read(tar_bytes([*FILES.items(), (dialog, b'label')]))
        self.assertEqual(caught.exception.code, 'quest_artifact')
        with self.assertRaises(HubError) as caught:
            self.read(tar_bytes(), occupied_paths={next(iter(FILES))})
        self.assertEqual(caught.exception.code, 'path_collision')


class BoundedCompilerCommandTests(unittest.TestCase):
    def run_python(self, script, **options):
        return qc._run(sys.executable, ['-c', script], dict(os.environ), **options)

    def test_binary_input_output_and_exit_status(self):
        code, raw = self.run_python('import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.exit(7)', input_bytes=b'\x00\xfforiginal')
        self.assertEqual((code, raw), (7, b'\x00\xfforiginal'))

    def test_timeout_and_output_limit_kill_the_owned_cli(self):
        for script, options, expected in (('import time; time.sleep(10)', {'timeout': 0.1}, 'compiler_timeout'),
                                           ('import sys; sys.stdout.buffer.write(b"x" * 4096)', {'limit': 100}, 'compiler_output_limit')):
            started = time.monotonic()
            with self.assertRaises(HubError) as caught:
                self.run_python(script, **options)
            self.assertEqual(caught.exception.code, expected)
            self.assertLess(time.monotonic() - started, 5)

    def test_start_failure_does_not_expose_exception_or_command(self):
        with patch.object(qc.subprocess, 'Popen', side_effect=OSError('private command')), self.assertRaises(HubError) as caught:
            self.run_python('pass')
        self.assertEqual(caught.exception.code, 'compiler_unavailable')
        self.assertNotIn('private command', str(caught.exception))

    def test_reader_start_failure_still_stops_the_owned_process(self):
        processes = []
        original = subprocess.Popen
        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(qc.subprocess, 'Popen', side_effect=launch), \
                patch.object(qc.threading.Thread, 'start', side_effect=RuntimeError('reader unavailable')), \
                self.assertRaises(HubError) as caught:
            self.run_python('import time; time.sleep(10)')
        self.assertEqual(caught.exception.code, 'compiler_unavailable')
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())


if __name__ == '__main__':
    unittest.main()
