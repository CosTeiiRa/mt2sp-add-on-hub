import unittest

from mt2sp_hub.client_hooks import install
from mt2sp_hub.client_runtime import Runtime
from test_client_runtime import Game, MAIN


class ClientHookTests(unittest.TestCase):
    def setUp(self):
        class Client(Game):
            def Open(self, value=None, *, fail=False):
                self.events.append(('game_open', value))
                if fail:
                    raise ValueError('game open failed')
                return value

            def Close(self, value=None, *, fail=False):
                self.events.append(('game_close', value))
                if fail:
                    raise ValueError('game close failed')
                return value

            def OnKeyDown(self, key):
                return key

        self.client = Client
        self.originals = dict(Client.__dict__)
        self.host = Runtime()
        self.assertTrue(self.host.load('example.one', {'main.py': MAIN, 'helper.py': ''}))
        self.codes = []

    def bind(self):
        binding = install(self.client, self.host, self.codes.append)
        self.addCleanup(binding.detach)
        return binding

    def test_game_methods_keep_arguments_results_and_cleanup_order(self):
        binding = self.bind()
        game, result = self.client(), object()
        self.assertIs(game.Open(result), result)
        self.assertEqual(len(game.windows), 1)
        self.assertTrue(game.windows[0].visible)
        self.assertIs(game.Close(result), result)
        self.assertEqual(game.events, [('game_open', result), ('close', 'example.one'),
                                       ('destroy', 'example.one'), ('game_close', result)])
        self.assertIs(self.client.__dict__['OnKeyDown'], self.originals['OnKeyDown'])
        self.assertTrue(binding.detach())
        self.assertTrue(binding.detach())
        for name in ('Open', 'Close'):
            self.assertIs(self.client.__dict__[name], self.originals[name])

    def test_failed_game_open_keeps_exception_and_never_opens_addons(self):
        self.bind()
        game = self.client()
        with self.assertRaisesRegex(ValueError, 'game open failed'):
            game.Open(fail=True)
        self.assertEqual(game.windows, [])
        self.assertIsNone(self.host._game)

    def test_failed_game_close_keeps_exception_after_addon_cleanup(self):
        self.bind()
        game = self.client()
        game.Open()
        with self.assertRaisesRegex(ValueError, 'game close failed'):
            game.Close(fail=True)
        self.assertEqual(game.windows[0].destroyed, 1)
        self.assertIsNone(self.host._game)

    def test_repeated_binding_and_session_events_do_not_duplicate_addons(self):
        binding = self.bind()
        game = self.client()
        game.Open()
        self.assertIs(install(self.client, self.host), binding)
        game.Open()
        self.assertEqual(len(game.windows), 1)
        game.Close()
        game.Close()
        self.assertEqual(game.windows[0].destroyed, 1)
        game.Open()
        self.assertEqual(len(game.windows), 2)
        binding.detach()
        self.assertEqual(game.windows[1].destroyed, 1)
        self.assertFalse(game.handles['example.one'].open())

    def test_new_session_and_stale_close_use_runtime_identity(self):
        self.bind()
        first, second = self.client(), self.client()
        first.Open()
        second.Open()
        self.assertEqual(first.windows[0].destroyed, 1)
        first.Close()
        self.assertTrue(second.windows[0].visible)
        second.Close()
        self.assertEqual(second.windows[0].destroyed, 1)

    def test_safe_launch_does_not_inspect_or_patch_game_class(self):
        class Unreadable:
            def __getattribute__(self, name):
                raise AssertionError('Safe launch touched the game class')

        host = Runtime(safe_mode=True)
        self.assertFalse(host.load('ignored', None))
        self.assertIsNone(install(Unreadable(), host))
        self.assertEqual(dict(self.client.__dict__), self.originals)

    def test_second_runtime_or_inherited_binding_is_refused(self):
        self.bind()
        with self.assertRaises(ValueError):
            install(self.client, Runtime())
        class Derived(self.client):
            pass
        with self.assertRaises(ValueError):
            install(Derived, self.host)

    def test_closed_or_active_host_cannot_install_new_hooks(self):
        for state in ('closed', 'active'):
            host = Runtime()
            if state == 'closed':
                host.shutdown()
            else:
                host.game_open(object())
            with self.assertRaises(ValueError):
                install(self.client, host)
            self.assertEqual(dict(self.client.__dict__), self.originals)

    def test_only_direct_ordinary_methods_are_accepted(self):
        class Inherited(self.client):
            pass
        class Static:
            Open = staticmethod(lambda: None)
            def Close(self): pass
        class Missing:
            def Open(self): pass
        for cls in (Inherited, Static, Missing):
            before = dict(cls.__dict__)
            with self.assertRaises(ValueError):
                install(cls, self.host)
            self.assertEqual(dict(cls.__dict__), before)

    def test_changed_wrapper_stays_untouched_and_retained_bridge_is_inert(self):
        binding = self.bind()
        game = self.client()
        game.Open()
        captured = self.client.Open
        def external(instance, *args, **kwargs):
            instance.events.append(('external', None))
            return captured(instance, *args, **kwargs)
        self.client.Open = external
        with self.assertRaises(ValueError):
            install(self.client, self.host)
        self.assertFalse(binding.detach())
        self.assertIs(self.client.Open, external)
        self.assertIs(self.client.Close, self.originals['Close'])
        self.assertEqual(game.windows[0].destroyed, 1)
        result = object()
        self.assertIs(game.Open(result), result)
        self.assertEqual(len(game.windows), 1)
        with self.assertRaises(ValueError):
            install(self.client, Runtime())

    def test_old_detach_does_not_remove_a_new_binding(self):
        old = self.bind()
        self.assertTrue(old.detach())
        replacement = install(self.client, Runtime())
        self.addCleanup(replacement.detach)
        self.assertTrue(old.detach())
        self.assertIs(install(self.client, replacement._runtime), replacement)

    def test_unknown_marker_is_not_overwritten_even_when_empty(self):
        self.client._mt2sp_hub_hooks = None
        before = dict(self.client.__dict__)
        with self.assertRaises(ValueError):
            install(self.client, self.host)
        self.assertEqual(dict(self.client.__dict__), before)

    def test_replaced_marker_is_preserved_during_detach(self):
        binding = self.bind()
        external = object()
        self.client._mt2sp_hub_hooks = external
        self.assertFalse(binding.detach())
        self.assertIs(self.client._mt2sp_hub_hooks, external)
        for name in ('Open', 'Close'):
            self.assertIs(self.client.__dict__[name], self.originals[name])

    def test_addon_failures_leave_other_windows_and_original_close_working(self):
        self.host.load('example.bad', {'main.py': '''
def register(context):
    def fail(game): raise ValueError('private fixture error')
    context.on('game.open', fail)
    context.on('game.close', fail)
'''})
        self.bind()
        game = self.client()
        game.Open()
        self.assertTrue(game.windows[0].visible)
        game.Close('closed')
        self.assertEqual(game.windows[0].destroyed, 1)
        self.assertEqual(game.events[-1], ('game_close', 'closed'))
        self.assertEqual(self.codes, [])

    def assert_host_failure_is_contained(self, method):
        binding = self.bind()
        game = self.client()
        if method == 'game_close':
            game.Open()
        original = getattr(self.host, method)
        def failed(instance):
            original(instance)
            raise ValueError('private host error')
        setattr(self.host, method, failed)
        if method == 'game_open':
            self.assertEqual(game.Open('opened'), 'opened')
        else:
            self.assertEqual(game.Close('closed'), 'closed')
        self.assertIn('hook_failed', self.codes)
        self.assertTrue(all(code in ('hook_failed', 'hook_cleanup_failed') for code in self.codes))
        self.assertEqual(game.windows[0].destroyed, 1)
        self.assertEqual(game.Close('still works'), 'still works')
        self.assertFalse(binding._active)

    def test_unexpected_open_host_error_disables_bridge_without_breaking_game(self):
        self.assert_host_failure_is_contained('game_open')

    def test_unexpected_close_host_error_disables_bridge_without_breaking_game(self):
        self.assert_host_failure_is_contained('game_close')

    def test_failed_diagnostic_sink_does_not_skip_game_close(self):
        def failed(*args):
            raise ValueError('private fixture error')
        binding = install(self.client, self.host, failed)
        self.addCleanup(binding.detach)
        self.host.game_close = failed
        self.host.shutdown = failed
        self.assertEqual(self.client().Close('closed'), 'closed')

    def test_assignment_failure_rolls_back_partial_install(self):
        class RejectClose(type):
            def __setattr__(cls, name, value):
                if name == 'Close':
                    raise TypeError('fixture assignment denied')
                super().__setattr__(name, value)
        class Client(metaclass=RejectClose):
            def Open(self): pass
            def Close(self): pass
        original = dict(Client.__dict__)
        with self.assertRaises(TypeError):
            install(Client, self.host)
        self.assertEqual(dict(Client.__dict__), original)


if __name__ == '__main__':
    unittest.main()
