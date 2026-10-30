import sys
import types
import unittest
from unittest.mock import patch

from mt2sp_hub.authoring import CLIENT_MAIN, CLIENT_WINDOW
from mt2sp_hub.client_runtime import Runtime


MAIN = '''
def register(context):
    helper = context.module('helper')
    handle = context.register_window('greeting', lambda game: game.make(context.id, helper))
    def opened(game):
        game.handles[context.id] = handle
        handle.open()
    context.on('game.open', opened)
    context.on('game.close', lambda game: game.events.append(('close', context.id)))
'''


class Window:
    def __init__(self, game, ident, helper):
        self.game, self.ident, self.helper = game, ident, helper
        self.visible = False
        self.destroyed = 0

    def Open(self):
        self.visible = True

    def Close(self):
        self.visible = False

    def IsShow(self):
        return self.visible

    def Destroy(self):
        self.destroyed += 1
        self.visible = False
        self.game.events.append(('destroy', self.ident))


class Game:
    def __init__(self):
        self.windows, self.events, self.handles = [], [], {}

    def make(self, ident, helper):
        window = Window(self, ident, helper)
        self.windows.append(window)
        return window


class ClientRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.diagnostics = []
        self.runtime = Runtime(diagnostic=lambda *args: self.diagnostics.append(args))
        self.addCleanup(self.runtime.shutdown)

    def load(self, ident='example.one', main=MAIN, helper='counter = 0'):
        return self.runtime.load(ident, {'main.py': main, 'helper.py': helper})

    def test_two_addons_share_events_and_window_names_without_sharing_modules(self):
        existing = dict(sys.modules)
        self.assertTrue(self.load('example.a-b'))
        self.assertTrue(self.load('example.a_b'))
        game = Game()
        self.runtime.game_open(game)
        self.assertEqual([window.ident for window in game.windows], ['example.a-b', 'example.a_b'])
        first, second = game.windows
        self.assertIsNot(first.helper, second.helper)
        self.assertNotEqual(first.helper.__name__, second.helper.__name__)
        first.helper.counter = 4
        self.assertEqual(second.helper.counter, 0)
        self.assertEqual(existing, sys.modules)

    def test_session_lifecycle_recreates_windows_and_ignores_stale_close(self):
        self.load()
        first, second = Game(), Game()
        self.assertEqual(first.windows, [])
        self.runtime.game_open(first)
        self.runtime.game_open(first)
        self.assertEqual(len(first.windows), 1)
        self.runtime.game_open(second)
        self.assertEqual(first.events, [('close', 'example.one'), ('destroy', 'example.one')])
        self.assertEqual(first.windows[0].destroyed, 1)
        self.assertEqual(len(second.windows), 1)
        self.assertIsNot(first.windows[0], second.windows[0])
        self.runtime.game_close(first)
        self.assertTrue(second.windows[0].visible)
        self.runtime.game_close(second)
        self.assertEqual(second.windows[0].destroyed, 1)
        self.assertFalse(second.handles['example.one'].open())
        self.runtime.game_close(second)
        self.assertEqual(second.windows[0].destroyed, 1)

    def test_window_toggle_is_local_and_lazy_factory_runs_once_per_session(self):
        self.load('example.one')
        self.load('example.two')
        game = Game()
        self.runtime.game_open(game)
        handle = game.handles['example.one']
        self.assertTrue(handle.toggle())
        self.assertFalse(game.windows[0].visible)
        self.assertTrue(game.windows[1].visible)
        self.assertTrue(handle.open())
        self.assertTrue(game.windows[0].visible)
        self.assertTrue(handle.open())
        self.assertEqual(len(game.windows), 2)

    def test_failed_registration_discards_its_callbacks_and_windows(self):
        self.assertFalse(self.load(main=MAIN + '\noriginal = register\ndef register(context):\n    original(context)\n    raise ValueError("private-path-sentinel")\n'))
        self.assertTrue(self.load('example.two'))
        game = Game()
        self.runtime.game_open(game)
        self.assertEqual([window.ident for window in game.windows], ['example.two'])
        self.assertEqual(self.diagnostics, [('example.one', 'registration_failed')])

    def test_callback_failure_disables_only_that_callback(self):
        source = '''
def register(context):
    def broken(game):
        game.events.append('broken')
        raise ValueError('private-path-sentinel')
    context.on('game.open', broken)
    context.on('game.open', lambda game: game.events.append('working'))
'''
        self.load(main=source)
        first, second = Game(), Game()
        self.runtime.game_open(first)
        self.runtime.game_close(first)
        self.runtime.game_open(second)
        self.assertEqual(first.events, ['broken', 'working'])
        self.assertEqual(second.events, ['working'])
        self.assertEqual(self.diagnostics, [('example.one', 'callback_failed')])

    def test_failed_close_callback_still_destroys_every_window(self):
        source = MAIN + '\noriginal = register\ndef register(context):\n    original(context)\n    context.on("game.close", lambda game: 1 / 0)\n'
        self.load(main=source)
        self.load('example.two')
        game = Game()
        self.runtime.game_open(game)
        self.runtime.game_close(game)
        self.assertEqual([window.destroyed for window in game.windows], [1, 1])

    def test_window_failure_disables_one_window_and_cleans_partial_instance(self):
        self.load()
        self.load('example.two')
        game = Game()
        make = game.make

        def create(ident, helper):
            window = make(ident, helper)
            if ident == 'example.one':
                window.Open = lambda: (_ for _ in ()).throw(ValueError('private-detail'))
            return window

        game.make = create
        self.runtime.game_open(game)
        self.assertEqual(game.windows[0].destroyed, 1)
        self.assertTrue(game.windows[1].visible)
        self.assertFalse(game.handles['example.one'].open())
        self.assertEqual(len(game.windows), 2)
        self.assertEqual(self.diagnostics, [('example.one', 'window_failed')])

    def test_cleanup_failure_does_not_prevent_other_window_cleanup(self):
        self.load()
        self.load('example.two')
        game = Game()
        self.runtime.game_open(game)
        game.windows[0].Destroy = lambda: (_ for _ in ()).throw(ValueError('private-detail'))
        self.runtime.game_close(game)
        self.assertEqual(game.windows[1].destroyed, 1)
        self.assertEqual(self.diagnostics, [('example.one', 'window_cleanup_failed')])
        self.runtime.game_open(Game())

    def test_shutdown_is_idempotent_and_old_handles_cannot_reopen(self):
        self.load()
        game = Game()
        self.runtime.game_open(game)
        self.runtime.shutdown()
        self.runtime.shutdown()
        self.assertEqual(game.windows[0].destroyed, 1)
        self.assertFalse(game.handles['example.one'].open())
        with self.assertRaises(ValueError):
            self.load('example.two')

    def test_safe_launch_does_not_touch_any_addon_source(self):
        class Unreadable:
            def __iter__(self):
                raise AssertionError('Must not inspect sources')
        runtime = Runtime(safe_mode=True)
        self.assertFalse(runtime.load('ignored', Unreadable()))
        runtime.game_open(Game())
        runtime.shutdown()

    def test_duplicate_load_and_mid_session_load_preserve_existing_addon(self):
        self.load()
        with self.assertRaises(ValueError):
            self.load()
        game = Game()
        self.runtime.game_open(game)
        with self.assertRaises(ValueError):
            self.load('example.two')
        self.assertTrue(game.windows[0].visible)

    def test_only_declared_local_python_helpers_are_loadable(self):
        for name in ('../secret', '/secret', 'helper.py', 'other.package', 'helper\n'):
            source = 'def register(context):\n    context.module(' + repr(name) + ')\n'
            self.assertFalse(self.load(main=source))
        for path in ('../secret.py', '/secret.py', 'folder/../secret.py', 'data.txt'):
            with self.assertRaises(ValueError):
                self.runtime.load('example.one', {'main.py': MAIN, path: b'raise AssertionError()'})

    def test_module_sources_keep_caller_mutations_out(self):
        source = '''
def register(context):
    def opened(game):
        game.events.append(context.module('helper').value)
    context.on('game.open', opened)
'''
        sources = {'main.py': source, 'helper.py': 'value = 1'}
        self.assertTrue(self.runtime.load('example.one', sources))
        sources['helper.py'] = 'value = 2'
        game = Game()
        self.runtime.game_open(game)
        self.assertEqual(game.events, [1])

    def test_failed_helper_is_not_left_as_a_partially_loaded_module(self):
        source = '''
def register(context):
    for attempt in range(2):
        try:
            context.module('helper')
        except ValueError:
            continue
        raise AssertionError('Failed helper was incorrectly cached')
'''
        self.assertTrue(self.load(main=source, helper='raise ValueError("private-detail")'))

    def test_bad_syntax_and_duplicate_window_registration_can_retry_cleanly(self):
        self.assertFalse(self.load(main='invalid python syntax!'))
        self.assertFalse(self.load(main='def register(context):\n    context.register_window("one", lambda game: None)\n    context.register_window("one", lambda game: None)\n'))
        self.assertTrue(self.load())
        game = Game()
        self.runtime.game_open(game)
        self.assertEqual(len(game.windows), 1)

    def test_registration_is_closed_after_startup_and_during_cleanup(self):
        source = '''
def register(context):
    context.on('game.open', lambda game: context.register_window('late', lambda value: None))
'''
        self.load(main=source)
        self.runtime.game_open(Game())
        self.assertEqual(self.diagnostics, [('example.one', 'callback_failed')])

    def test_raw_author_logs_and_failures_do_not_mix_with_public_diagnostics(self):
        private, diagnostics = [], []
        runtime = Runtime(local_log=lambda *args: private.append(args), diagnostic=lambda *args: diagnostics.append(args))
        source = 'def register(context):\n    context.log("private-message-sentinel")\n    raise ValueError("private-error-sentinel")\n'
        self.assertFalse(runtime.load('example.one', {'main.py': source}))
        self.assertEqual(private, [('example.one', 'private-message-sentinel')])
        self.assertEqual(diagnostics, [('example.one', 'registration_failed')])

    def test_generated_client_starter_opens_and_releases_its_ui(self):
        boards, labels = [], []

        class Widget:
            def __init__(self):
                self.visible = False
                self.close = None
            def Show(self): self.visible = True
            def Hide(self): self.visible = False
            def IsShow(self): return self.visible
            def SetSize(self, *args): pass
            def SetPosition(self, *args): pass
            def SetTitleName(self, *args): pass
            def SetText(self, *args): pass
            def SetParent(self, *args): pass
            def AddFlag(self, *args): pass
            def SetCloseEvent(self, callback): self.close = callback

        def widget(collection):
            value = Widget()
            collection.append(value)
            return value

        ui = types.ModuleType('ui')
        ui.BoardWithTitleBar = lambda: widget(boards)
        ui.TextLine = lambda: widget(labels)
        with patch.dict(sys.modules, {'ui': ui}):
            self.assertTrue(self.runtime.load('example.hello', {'main.py': CLIENT_MAIN, 'window.py': CLIENT_WINDOW}))
            game = Game()
            self.runtime.game_open(game)
            self.assertTrue(boards[0].visible)
            boards[0].close()
            self.assertFalse(boards[0].visible)
            self.runtime.game_close(game)
            self.assertIsNone(boards[0].close)
            self.assertFalse(labels[0].visible)
            self.runtime.game_open(Game())
            self.assertEqual(len(boards), 2)
        self.assertEqual(self.diagnostics, [])
