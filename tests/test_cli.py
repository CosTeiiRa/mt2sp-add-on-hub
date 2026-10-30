import contextlib
import io
import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from mt2sp_hub.cli import main
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

    def test_original_creator_examples_pack_for_each_component_type(self):
        tool = Path(__file__).resolve().parents[1] / 'tools/make_example.py'
        with tempfile.TemporaryDirectory() as temporary:
            for kind in ['client', 'server', 'combined']:
                source = Path(temporary) / kind
                output = Path(temporary) / (kind + '.zip')
                result = subprocess.run([sys.executable, str(tool), str(source), '--kind', kind],
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, 'Example creation failed')
                self.assertEqual(self.call('pack', source, output)[0], 0)
                code, observed = self.call('validate', output)
                self.assertEqual(code, 0)
                self.assertEqual(observed['components'], ['client', 'server'] if kind == 'combined' else [kind])
