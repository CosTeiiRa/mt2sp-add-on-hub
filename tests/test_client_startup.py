import base64
import builtins
import os
import sys
import types
import unittest
from unittest.mock import patch

from helpers import archive, example
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.client import prepare_client


def addon(ident='example.one', *, sources=None, requires=None, server=False):
    sources = sources if sources is not None else {'main.py': b'''def register(context):
    context.on('game.open', lambda game: game.events.append(context.id))
'''}
    raw = {'client/' + ident + '/' + path: value for path, value in sources.items()}
    if server:
        raw['server/' + ident + '/quests/fixture.quest'] = b'Original server fixture; not compiled here.'
    manifest, members = example(ident, files=raw, requires=requires)
    for kind, component in manifest['components'].items():
        component['capabilities'] = [kind + ('.module' if kind == 'client' else '.quest')]
    return archive(manifest, members)


def embedded_modules(members):
    """Exercise the emitted members with lazy virtual pack imports, no disk."""
    loaded = {}
    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith('mt2sp_hub_'):
            if name not in loaded:
                module = types.ModuleType(name)
                module.__dict__['__builtins__'] = dict(vars(builtins), __import__=importing)
                loaded[name] = module
                exec(compile(members[name + '.py'], name + '.py', 'exec'), module.__dict__)
            return loaded[name]
        return builtins.__import__(name, globals, locals, fromlist, level)
    return importing('mt2sp_hub_bootstrap'), loaded


def game_class():
    class Game:
        def __init__(self): self.events = []
        def Open(self): return 'opened'
        def Close(self): return 'closed'
    return Game


class ClientPreparationTests(unittest.TestCase):
    def test_deterministic_members_preserve_bytes_without_executing_sources(self):
        sources = {'main.py': b'raise AssertionError("Do not execute")',
                   'local/helper.py': b'# coding: latin1\nprint "\xff"\n'}
        package = addon(sources=sources)
        before = package.raw
        members = prepare_client([package], occupied_paths={'game.py', 'UI/Common.py'})
        self.assertEqual(members, prepare_client([package], occupied_paths=set()))
        self.assertEqual(package.raw, before)
        self.assertEqual(set(members), {'mt2sp_hub_bootstrap.py', 'mt2sp_hub_runtime.py',
                                       'mt2sp_hub_hooks.py', 'mt2sp_hub_payload.py'})
        data = {}
        exec(members['mt2sp_hub_payload.py'], data)
        ident, dependencies, encoded = data['ADDONS'][0]
        self.assertEqual((ident, dependencies), ('example.one', []))
        self.assertEqual({path: base64.b64decode(raw) for path, raw in encoded.items()}, sources)

    def test_dependency_order_includes_client_dependencies_through_server_packages(self):
        foundation = addon('example.z')
        server = addon('example.server', sources={}, server=True, requires={'example.z': '>=1.0.0'})
        client = addon('example.a', requires={'example.server': '>=1.0.0'})
        members = prepare_client([client, server, foundation], occupied_paths=set())
        data = {}
        exec(members['mt2sp_hub_payload.py'], data)
        self.assertEqual([(row[0], row[1]) for row in data['ADDONS']],
                         [('example.z', []), ('example.a', ['example.z'])])

    def test_missing_dependency_and_conflict_are_refused(self):
        with self.assertRaises(HubError) as caught:
            prepare_client([addon(requires={'example.absent': '>=1.0.0'})], occupied_paths=set())
        self.assertEqual(caught.exception.code, 'dependency_missing')
        manifest, original = example(files={'client/example.one/main.py': b'def register(context): pass'}, conflicts=['example.two'])
        manifest['components']['client']['capabilities'] = ['client.module']
        with self.assertRaises(HubError) as caught:
            prepare_client([archive(manifest, original), addon('example.two')], occupied_paths=set())
        self.assertEqual(caught.exception.code, 'package_conflict')

    def test_sources_require_owned_namespace_main_and_python_helpers(self):
        for path in ('example.other/main.py', 'example.one/data.txt', 'example.one/bad-name.py', 'example.one/helper.py'):
            manifest, members = example(files={'client/' + path: b'original fixture'})
            manifest['components']['client']['capabilities'] = ['client.module']
            with self.subTest(path=path), self.assertRaises(HubError):
                prepare_client([archive(manifest, members)], occupied_paths=set())

    def test_component_capabilities_and_api_are_checked(self):
        for capability in ('fixture.files', 'server.quest', None):
            manifest, members = example(files={'client/example.one/main.py': b''})
            manifest['components']['client']['capabilities'] = [capability] if capability else []
            with self.assertRaises(HubError):
                prepare_client([archive(manifest, members)], occupied_paths=set())
        manifest['components']['client']['capabilities'] = ['client.module']
        manifest['components']['client']['api'] = '>=2.0.0'
        with self.assertRaises(HubError) as caught:
            prepare_client([archive(manifest, members)], occupied_paths=set())
        self.assertEqual(caught.exception.code, 'api_incompatible')

    def test_baseline_collisions_include_case_aliases_and_parent_files(self):
        for name in ('mt2sp_hub_runtime.py', 'MT2SP_HUB_PAYLOAD.PY',
                     '.\\mt2sp_hub_hooks.py', 'folder/../mt2sp_hub_bootstrap.py',
                     'mt2sp_hub_payload.py/nested', 'mt2sp_hub_runtime.pyc',
                     'mt2sp_hub_hooks/__init__.py', 'mt2sp_hub_runtime.pyd'):
            with self.subTest(name=name), self.assertRaises(HubError) as caught:
                prepare_client([addon()], occupied_paths={name})
            self.assertEqual(caught.exception.code, 'client_collision')
        with self.assertRaises(HubError):
            prepare_client([addon()], occupied_paths=None)

    def test_empty_and_server_only_selection_need_no_client_loader(self):
        self.assertEqual(prepare_client([], occupied_paths=set()), {})
        self.assertEqual(prepare_client([addon(sources={}, server=True)], occupied_paths=set()), {})

    def test_selection_archive_and_generated_output_budgets(self):
        package = addon(server=True)
        for constant, value, code in (('MAX_PACKAGES', 0, 'package_limit'),
                                      ('MAX_SELECTED_ARCHIVES', len(package.raw) - 1, 'archive_budget'),
                                      ('MAX_BUNDLE', 1, 'client_bundle_limit')):
            with patch('mt2sp_hub.installation.client.' + constant, value), self.assertRaises(HubError) as caught:
                prepare_client([package], occupied_paths=set())
            self.assertEqual(caught.exception.code, code)

    def test_unavailable_host_source_uses_path_free_error(self):
        with patch('mt2sp_hub.installation.client.files', side_effect=OSError('private path')), self.assertRaises(HubError) as caught:
            prepare_client([addon()], occupied_paths=set())
        self.assertEqual(caught.exception.code, 'client_host_missing')
        self.assertNotIn('private path', str(caught.exception))


class ClientStartupTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'MT2SP_HUB_SAFE_MODE': ''})
        env.start()
        self.addCleanup(env.stop)
        self.game = game_class()
        self.events = []

    def startup(self, packages):
        return embedded_modules(prepare_client(packages, occupied_paths=set()))

    def test_generated_bootstrap_loads_once_and_shared_hooks_drive_callbacks(self):
        bootstrap, modules = self.startup([addon('example.two'), addon()])
        binding = bootstrap.install(self.game, lambda *args: self.events.append(args))
        self.assertIsNotNone(binding)
        self.addCleanup(binding.detach)
        self.assertIs(bootstrap.install(self.game), binding)
        game = self.game()
        self.assertEqual(game.Open(), 'opened')
        self.assertEqual(game.events, ['example.one', 'example.two'])
        game.Open()
        self.assertEqual(game.events, ['example.one', 'example.two'])
        self.assertEqual(game.Close(), 'closed')
        self.assertEqual(self.events, [])
        self.assertEqual(len(modules), 4)
        self.assertEqual(modules['mt2sp_hub_payload'].ADDONS, ())

    def test_safe_launch_skips_even_missing_runtime_payload_and_unreadable_class(self):
        members = prepare_client([addon()], occupied_paths=set())
        for value in ('1', 'true', '0'):
            with patch.dict(os.environ, {'MT2SP_HUB_SAFE_MODE': value}):
                bootstrap, modules = embedded_modules({'mt2sp_hub_bootstrap.py': members['mt2sp_hub_bootstrap.py']})
                self.assertIsNone(bootstrap.install(None))
                self.assertEqual(list(modules), ['mt2sp_hub_bootstrap'])
                os.environ['MT2SP_HUB_SAFE_MODE'] = ''
                self.assertIsNone(bootstrap.install(self.game))
                self.assertEqual(list(modules), ['mt2sp_hub_bootstrap'])

    def test_failed_dependency_skips_dependents_but_keeps_unrelated_module(self):
        broken = addon('example.broken', sources={'main.py': b'def register(context):\n    raise ValueError("private details")'})
        dependent = addon('example.dependent', requires={'example.broken': '>=1.0.0'})
        bootstrap, _ = self.startup([dependent, broken, addon('example.working')])
        binding = bootstrap.install(self.game, lambda *args: self.events.append(args))
        self.addCleanup(binding.detach)
        game = self.game()
        game.Open()
        self.assertEqual(game.events, ['example.working'])
        self.assertEqual(self.events, [('example.broken', 'registration_failed'),
                                       ('example.dependent', 'dependency_failed')])

    def test_broken_host_members_fail_closed_with_fixed_diagnostic_and_no_retry(self):
        members = prepare_client([addon()], occupied_paths=set())
        members['mt2sp_hub_payload.py'] = b'raise ValueError("private startup detail")'
        bootstrap, _ = embedded_modules(members)
        before = dict(self.game.__dict__)
        self.assertIsNone(bootstrap.install(self.game, lambda *args: self.events.append(args)))
        self.assertEqual(dict(self.game.__dict__), before)
        self.assertEqual(self.events, [(None, 'startup_failed')])
        self.assertIsNone(bootstrap.install(self.game))

    def test_failed_binding_discards_loaded_registrations(self):
        # Observe the actual generated runtime so the test verifies cleanup,
        # not just the bootstrap's return value.
        members = prepare_client([addon()], occupied_paths=set())
        members['mt2sp_hub_runtime.py'] += b'\nlast_runtime = None\n_original_init = Runtime.__init__\ndef capture(self, *args, **kwargs):\n    global last_runtime\n    last_runtime = self\n    _original_init(self, *args, **kwargs)\nRuntime.__init__ = capture\n'
        bootstrap, modules = embedded_modules(members)
        self.assertIsNone(bootstrap.install(object, lambda *args: self.events.append(args)))
        self.assertEqual(self.events, [(None, 'startup_failed')])
        self.assertIsNone(bootstrap._binding)
        runtime = modules['mt2sp_hub_runtime'].last_runtime
        self.assertTrue(runtime._closed)
        self.assertEqual(runtime._contexts, [])

    def test_existing_module_cache_is_preserved_and_startup_refused(self):
        bootstrap, _ = self.startup([addon()])
        external = types.ModuleType('mt2sp_hub_runtime')
        with patch.dict(sys.modules, {'mt2sp_hub_runtime': external}):
            self.assertIsNone(bootstrap.install(self.game, lambda *args: self.events.append(args)))
            self.assertIs(sys.modules['mt2sp_hub_runtime'], external)
        self.assertEqual(self.events, [(None, 'startup_failed')])

    def test_second_class_and_detached_binding_cannot_restart(self):
        bootstrap, _ = self.startup([addon()])
        binding = bootstrap.install(self.game)
        self.addCleanup(binding.detach)
        other = game_class()
        original = other.Open
        self.assertIsNone(bootstrap.install(other, lambda *args: self.events.append(args)))
        self.assertIs(other.Open, original)
        self.assertTrue(binding.detach())
        self.assertIsNone(bootstrap.install(self.game, lambda *args: self.events.append(args)))
        self.assertEqual(self.events, [(None, 'startup_conflict'), (None, 'startup_conflict')])

    def test_repeated_startup_detects_changed_hooks_without_replacing_them(self):
        bootstrap, _ = self.startup([addon()])
        binding = bootstrap.install(self.game)
        self.addCleanup(binding.detach)
        def external(instance): return 'external'
        self.game.Open = external
        self.assertIsNone(bootstrap.install(self.game, lambda *args: self.events.append(args)))
        self.assertIs(self.game.Open, external)
        self.assertEqual(self.events, [(None, 'startup_conflict')])

    def test_diagnostic_sink_failure_does_not_escape_startup(self):
        bootstrap, _ = self.startup([addon()])
        def failed(*args): raise ValueError('private sink detail')
        self.assertIsNone(bootstrap.install(object, failed))


if __name__ == '__main__':
    unittest.main()
