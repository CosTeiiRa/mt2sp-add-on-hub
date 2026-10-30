"""Host-owned Open/Close bridge for a separately verified client build.

Python 2.7 compatible. No game imports, source loading or disk changes. Call on
the UI thread before gameplay; add-on authors never install their own hooks.
"""
import types


_MARKER = '_mt2sp_hub_hooks'
_MISSING = object()


class _Binding(object):
    def __init__(self, game_class, runtime, diagnostic):
        self._class = game_class
        self._runtime = runtime
        self._diagnostic = diagnostic
        self._active = True
        self._detached = None
        self._originals = dict((name, game_class.__dict__[name])
                               for name in ('Open', 'Close'))

        def opened(instance, *args, **kwargs):
            result = self._originals['Open'](instance, *args, **kwargs)
            self._event('game_open', instance)
            return result

        def closed(instance, *args, **kwargs):
            self._event('game_close', instance)
            return self._originals['Close'](instance, *args, **kwargs)

        self._wrappers = {'Open': opened, 'Close': closed}

    def _report(self, code):
        try:
            if self._diagnostic is not None:
                self._diagnostic(code)
        except Exception:
            pass

    def _stop(self):
        self._active = False
        try:
            self._runtime.shutdown()
        except Exception:
            self._report('hook_cleanup_failed')

    def _event(self, name, instance):
        if self._active:
            try:
                getattr(self._runtime, name)(instance)
            except Exception:
                # An unexpected host error must not skip the game's Close or
                # turn a successful Open into a game failure. Disable this run.
                self._stop()
                self._report('hook_failed')

    def detach(self):
        """Shut down this runtime and restore only methods we still own.

        False means another tool changed a hook: its method stays untouched,
        our captured wrapper becomes inert, and the marker blocks rebinding
        until a clean client restart. Calling detach again has no effect.
        """
        if self._detached is not None:
            return self._detached
        self._stop()
        complete = True
        for name, wrapper in self._wrappers.items():
            if self._class.__dict__.get(name) is wrapper:
                setattr(self._class, name, self._originals[name])
            else:
                complete = False
        if self._class.__dict__.get(_MARKER) is self and complete:
            delattr(self._class, _MARKER)
        else:
            complete = False
        self._detached = complete
        return complete


def install(game_class, runtime, diagnostic=None):
    """Bind one loaded Runtime to a verified class's ordinary Open/Close.

    Returns a binding, or None during safe launch without inspecting the class.
    Repeating the same binding is harmless; a second owner or changed hook is
    refused. diagnostic(code) receives fixed host codes, never exception text.
    This shape check does not verify a game build or discover its startup point.
    """
    if runtime._safe_mode:
        return None
    existing = getattr(game_class, _MARKER, _MISSING)
    if existing is not _MISSING:
        if (isinstance(existing, _Binding) and existing._class is game_class
                and existing._runtime is runtime and existing._active
                and all(game_class.__dict__.get(name) is wrapper
                        for name, wrapper in existing._wrappers.items())):
            return existing
        raise ValueError('Client hooks already owned or changed; restart the client.')
    if runtime._closed or runtime._game is not None:
        raise ValueError('Install client hooks before gameplay starts.')
    if not all(isinstance(game_class.__dict__.get(name), types.FunctionType)
               for name in ('Open', 'Close')):
        raise ValueError('Client class must define ordinary Open and Close methods.')
    binding = _Binding(game_class, runtime, diagnostic)
    try:
        for name, wrapper in binding._wrappers.items():
            setattr(game_class, name, wrapper)
        setattr(game_class, _MARKER, binding)
    except Exception:
        # Leave no half-installed bridge if class assignment is refused.
        binding.detach()
        raise
    return binding
