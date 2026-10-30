"""Small standalone client lifecycle host; no game imports or filesystem reads.

Keep this file compatible with Python 2.7 syntax for the embedded interpreter.
The host supplies verified source bytes and calls game_open/game_close on the
game UI thread. Add-ons are trusted Python code, not sandboxed code.
"""
import re
import types

try:
    _TEXT = (basestring,)
except NameError:
    _TEXT = (str,)


def _matches(pattern, value):
    return isinstance(value, _TEXT) and re.match(pattern + r'\Z', value) is not None


class WindowHandle(object):
    def __init__(self, context, factory):
        self._context = context
        self._factory = factory
        self._window = None
        self._failed = False

    def open(self):
        return self._show(False)

    def toggle(self):
        return self._show(True)

    def _show(self, toggle):
        context = self._context
        host = context._host
        if not context._active or host._game is None or host._closing or self._failed:
            return False
        try:
            if self._window is None:
                self._window = self._factory(host._game)
                if not all(callable(getattr(self._window, name, None))
                           for name in ('Open', 'Close', 'IsShow', 'Destroy')):
                    raise ValueError('Window does not implement the client contract.')
            if self._window.IsShow():
                if toggle:
                    self._window.Close()
            else:
                self._window.Open()
            return True
        except Exception:
            self._failed = True
            self._dispose()
            host._diagnose(context.id, 'window_failed')
            return False

    def _dispose(self):
        window, self._window = self._window, None
        if window is not None:
            try:
                window.Destroy()
            except Exception:
                self._context._host._diagnose(self._context.id, 'window_cleanup_failed')


class Context(object):
    def __init__(self, host, ident, sources):
        self.id = ident
        self._host = host
        self._sources = dict(sources)
        self._modules = {}
        self._callbacks = {'game.open': [], 'game.close': []}
        self._windows = {}
        self._active = True
        self._registering = True

    def _registration(self):
        if not self._active or not self._registering:
            raise ValueError('Register callbacks and windows inside register(context).')

    def on(self, event, callback):
        self._registration()
        if event not in self._callbacks or not callable(callback):
            raise ValueError('Unsupported event or callback.')
        self._callbacks[event].append(callback)

    def register_window(self, name, factory):
        self._registration()
        if not _matches(r'[a-z][a-z0-9_-]{0,63}', name) or not callable(factory):
            raise ValueError('Invalid window registration.')
        if name in self._windows:
            raise ValueError('Window is already registered by this add-on.')
        handle = WindowHandle(self, factory)
        self._windows[name] = handle
        return handle

    def module(self, name):
        if not self._active or not _matches(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', name):
            raise ValueError('Invalid local helper name.')
        path = name.replace('.', '/') + '.py'
        if path not in self._sources:
            raise ValueError('Helper is not in this add-on\'s declared sources.')
        if name in self._modules:
            return self._modules[name]
        # Hex encoding preserves identity even for IDs differing only by dot,
        # hyphen or underscore. Cache stays local: never replace sys.modules.
        namespace = '_mt2sp_' + ''.join('%02x' % ord(char) for char in self.id)
        module = types.ModuleType(namespace + '.' + name)
        module.__file__ = self.id + '/' + path
        module.__package__ = ''
        self._modules[name] = module
        try:
            eval(compile(self._sources[path], module.__file__, 'exec'), module.__dict__)
        except Exception:
            self._modules.pop(name, None)
            raise
        return module

    def log(self, message):
        if self._active:
            # Free-form author messages go only to an optional private local
            # sink. They never enter the fixed-code diagnostic callback.
            try:
                if self._host._log is not None:
                    self._host._log(self.id, message)
            except Exception:
                pass

    def _emit(self, event, game):
        for callback in list(self._callbacks[event]):
            try:
                callback(game)
            except Exception:
                self._callbacks[event] = [item for item in self._callbacks[event] if item is not callback]
                self._host._diagnose(self.id, 'callback_failed')

    def _dispose_windows(self):
        for name in sorted(self._windows):
            self._windows[name]._dispose()

    def _discard(self):
        self._active = False
        self._registering = False
        self._callbacks = {'game.open': [], 'game.close': []}
        self._dispose_windows()
        self._windows.clear()
        self._modules.clear()
        self._sources.clear()


class Runtime(object):
    def __init__(self, safe_mode=False, diagnostic=None, local_log=None):
        self._safe_mode = bool(safe_mode)
        self._diagnostic = diagnostic
        self._log = local_log
        self._contexts = []
        self._game = None
        self._closing = False
        self._closed = False

    def _diagnose(self, ident, code):
        try:
            if self._diagnostic is not None:
                self._diagnostic(ident, code)
        except Exception:
            pass

    def load(self, ident, sources):
        """Load one verified enabled add-on, in the host's dependency order.

        sources maps declared component-relative .py paths to immutable source
        bytes. No disk fallback, package download or game patch happens here.
        """
        if self._safe_mode:
            return False  # Do not even enumerate sources during safe launch.
        if self._closed or self._game is not None:
            raise ValueError('Load add-ons before gameplay starts.')
        if not _matches(r'[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+', ident) or len(ident) > 128:
            raise ValueError('Invalid add-on ID.')
        if any(context.id == ident for context in self._contexts):
            raise ValueError('Add-on is already loaded.')
        if not isinstance(sources, dict) or 'main.py' not in sources:
            raise ValueError('Declared sources require main.py.')
        for path, source in sources.items():
            if (not _matches(r'(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py', path)
                    or not isinstance(source, _TEXT + (bytes,))):
                raise ValueError('Invalid declared Python source.')
        context = Context(self, ident, sources)
        try:
            context.module('main').register(context)
        except Exception:
            context._discard()
            self._diagnose(ident, 'registration_failed')
            return False
        context._registering = False
        self._contexts.append(context)
        return True

    def game_open(self, game):
        if self._closed or self._safe_mode or game is None or self._game is game:
            return
        if self._game is not None:
            self.game_close(self._game)
        self._game = game
        for context in self._contexts:
            context._emit('game.open', game)

    def game_close(self, game):
        if self._game is None or self._game is not game or self._closing:
            return
        self._closing = True
        try:
            for context in self._contexts:
                context._emit('game.close', game)
            for context in self._contexts:
                context._dispose_windows()
        finally:
            self._game = None
            self._closing = False

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.game_close(self._game)
        for context in self._contexts:
            context._discard()
        self._contexts = []
