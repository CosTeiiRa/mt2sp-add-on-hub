import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mt2sp_hub.cli import main
from mt2sp_hub.core.packages import Package
from mt2sp_hub.installation.manager import Manager
from helpers import package


class CliTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(map(str, args)))
        return code, json.loads(output.getvalue())

    def test_offline_cli_lifecycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'sandbox'
            source = Path(temporary) / 'example.zip'
            source.write_bytes(package().raw)
            self.assertEqual(self.call('validate', source)[0], 0)
            self.assertEqual(self.call('sandbox-init', root)[0], 0)
            code, plan = self.call('plan', '--root', root, '--add', source)
            self.assertEqual(code, 0)
            self.assertEqual(self.call('apply', '--root', root, '--plan', plan['plan'])[1]['error'], 'confirmation_required')
            self.assertEqual(self.call('apply', '--root', root, '--plan', plan['plan'], '--yes')[0], 0)
            source.unlink()  # Installed operations depend on local cached objects only.
            code, removal = self.call('plan', '--root', root, '--remove', 'example.one')
            self.assertEqual(code, 0)
            self.assertEqual(self.call('apply', '--root', root, '--plan', removal['plan'], '--yes')[0], 0)
            self.assertEqual(self.call('status', '--root', root)[1]['packages'], [])

    def test_os_errors_do_not_disclose_local_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / 'sensitive-local-folder' / 'missing.zip'
            code, result = self.call('validate', missing)
            self.assertEqual(code, 2)
            self.assertEqual(result['error'], 'io_error')
            self.assertNotIn(temporary, json.dumps(result))
            self.assertNotIn('sensitive-local-folder', json.dumps(result))
            code, result = self.call('build', missing, Path(temporary) / 'output.zip', '--json')
            self.assertEqual((code, result['error']), (2, 'io_error'))
            self.assertIn('missing', result['message'])
            self.assertNotIn(temporary, json.dumps(result))
            self.assertNotIn('sensitive-local-folder', json.dumps(result))

    def test_original_creator_examples_pack_for_each_component_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            for kind in ['client', 'server', 'combined']:
                source = Path(temporary) / kind
                output = Path(temporary) / (kind + '.zip')
                self.assertEqual(self.call('new', source, '--id', 'example.hello', '--kind', kind, '--json')[0], 0)
                self.assertEqual(self.call('build', source, output, '--json')[0], 0)
                code, observed = self.call('validate', output)
                self.assertEqual(code, 0)
                self.assertEqual(observed['components'], ['client', 'server'] if kind == 'combined' else [kind])
                sandbox = Path(temporary) / (kind + '-sandbox')
                self.assertEqual(self.call('sandbox-init', sandbox)[0], 0)
                code, plan = self.call('plan', '--root', sandbox, '--add', output)
                self.assertEqual(code, 0)
                self.assertEqual(self.call('apply', '--root', sandbox, '--plan', plan['plan'], '--yes')[0], 0)
                for component in observed['components']:
                    self.assertEqual((sandbox / component / 'example.hello/message.txt').read_bytes(),
                                     (source / 'payload' / (component + '.txt')).read_bytes())

    def test_creator_edit_update_and_remove_without_handwritten_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, first, second, sandbox = [base / name for name in ('source', 'one.zip', 'two.zip', 'sandbox')]
            self.assertEqual(self.call('new', source, '--id', 'example.hello', '--json')[0], 0)
            self.assertEqual(self.call('build', source, first, '--json')[0], 0)
            self.call('sandbox-init', sandbox)
            manager = Manager(sandbox)
            manager.apply(manager.plan([Package.load(first)])['plan'])
            (source / 'payload/client.txt').write_bytes(b'Edited client content')
            manifest_path = source / 'addon.json'
            manifest = json.loads(manifest_path.read_bytes())
            manifest['version'] = '0.1.1'
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(self.call('build', source, second, '--json')[0], 0)
            manager.apply(manager.plan([Package.load(second)])['plan'])
            self.assertEqual((sandbox / 'client/example.hello/message.txt').read_bytes(), b'Edited client content')
            manager.apply(manager.plan(remove=['example.hello'])['plan'])
            self.assertFalse((sandbox / 'client/example.hello/message.txt').exists())
            self.assertFalse((sandbox / 'server/example.hello/message.txt').exists())

    def test_creator_never_overwrites_existing_source_or_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / 'source', Path(temporary) / 'release.zip'
            self.call('new', source, '--id', 'example.hello', '--json')
            before = (source / 'addon.json').read_bytes()
            code, error = self.call('new', source, '--id', 'example.replacement', '--json')
            self.assertEqual((code, error['error']), (2, 'project_exists'))
            self.assertEqual((source / 'addon.json').read_bytes(), before)
            output.write_bytes(b'Existing artifact')
            code, error = self.call('build', source, output, '--json')
            self.assertEqual((code, error['error']), (2, 'output_exists'))
            self.assertEqual(output.read_bytes(), b'Existing artifact')
            code, error = self.call('build', source, source / 'release.zip', '--json')
            self.assertEqual((code, error['error']), (2, 'output_in_source'))
            self.assertFalse((source / 'release.zip').exists())

    def test_invalid_starter_id_creates_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            code, error = self.call('new', source, '--id', 'invalid', '--json')
            self.assertEqual((code, error['error']), (2, 'package_id'))
            self.assertFalse(source.exists())

    def test_creator_default_output_explains_the_sandbox_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / 'source', Path(temporary) / 'release.zip'
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                self.assertEqual(main(['new', str(source), '--id', 'example.hello']), 0)
                self.assertEqual(main(['build', str(source), str(output)]), 0)
            self.assertIn('not a working game add-on', text.getvalue())
            self.assertIn('Checksums generated', text.getvalue())
            self.assertNotIn(temporary, text.getvalue())
