import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from mt2sp_hub.authoring import create
from mt2sp_hub.cli import main
from mt2sp_hub.core.packages import build
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.manager import Manager, initialize


class GameCreatorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hub-game-author-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_each_game_starter_builds_without_changing_source_or_enabling_installation(self):
        for kind in ('client', 'server', 'combined'):
            with self.subTest(kind=kind):
                source = self.root / kind
                manifest = create(source, 'example.hello', kind, profile='game')
                before = (source / 'addon.json').read_bytes()
                package = build(source)
                self.assertEqual(package.raw, build(source).raw)
                self.assertEqual(before, (source / 'addon.json').read_bytes())
                observed, files = package.unpack()
                self.assertEqual(set(observed['components']), {'client', 'server'} if kind == 'combined' else {kind})
                for component in manifest['components']:
                    self.assertEqual(observed['components'][component]['capabilities'], [component + ('.module' if component == 'client' else '.quest')])
                    for row in observed['components'][component]['files']:
                        self.assertTrue(row['target'].startswith('example.hello/'))
                        self.assertEqual(len(row['sha256']), 64)
                if 'server' in observed['components']:
                    quest = files['server/example.hello/quests/example_hello_greeting.quest']
                    self.assertTrue(quest.startswith(b'quest example_hello_greeting begin\n'))
                    self.assertIn(b'when login begin', quest)
                sandbox = self.root / (kind + '-sandbox')
                initialize(sandbox)
                manager = Manager(sandbox)
                before_state = manager.status()
                with self.assertRaises(HubError) as caught:
                    manager.plan([package])
                self.assertEqual(caught.exception.code, 'capability_missing')
                self.assertEqual(before_state, manager.status())
                self.assertFalse((sandbox / 'client').exists())
                self.assertFalse((sandbox / 'server').exists())

    def test_build_does_not_execute_or_claim_to_compile_game_sources(self):
        source = self.root / 'source'
        create(source, 'example.hello', 'combined', profile='game')
        (source / 'payload/client/main.py').write_bytes(b'raise AssertionError("Must not run")')
        (source / 'payload/server/example_hello_greeting.quest').write_bytes(b'invalid quest syntax')
        package = build(source)
        self.assertEqual(package.manifest['id'], 'example.hello')

    def test_bad_profile_or_long_generated_quest_name_creates_nothing(self):
        source = self.root / 'source'
        for ident, profile, expected in (('example.hello', 'unknown', 'profile'),
                                         ('example.' + 'a' * 60, 'game', 'quest_name')):
            with self.assertRaises(HubError) as caught:
                create(source, ident, 'combined', profile=profile)
            self.assertEqual(caught.exception.code, expected)
            self.assertFalse(source.exists())

    def test_cli_explains_game_preview_and_build_target_capabilities(self):
        source, archive = self.root / 'source', self.root / 'preview.zip'
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['new', str(source), '--id', 'example.hello', '--profile', 'game']), 0)
            self.assertEqual(main(['build', str(source), str(archive)]), 0)
        self.assertIn('Experimental game source', output.getvalue())
        self.assertIn('matching target capabilities', output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['new', str(self.root / 'json'), '--id', 'example.hello', '--profile', 'game', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue())['kind'], 'game_preview')
