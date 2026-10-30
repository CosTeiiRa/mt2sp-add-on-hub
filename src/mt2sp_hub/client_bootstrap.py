"""Single experimental client startup entry; keep Python 2.7 compatibility.

The adapter supplies the three adjacent, verified Hub modules. The launcher
sets MT2SP_HUB_SAFE_MODE to any nonempty value to skip add-ons for this run.
"""
import os


_attempted = False
_binding = None


def install(game_class, diagnostic=None):
    """Start once, before gameplay on the UI thread; return a binding or None.

    diagnostic(package_id_or_None, code) receives fixed codes only. None marks
    host failures. This entry never reads physical package paths or downloads.
    """
    global _attempted, _binding

    def report(ident, code):
        try:
            if diagnostic is not None:
                diagnostic(ident, code)
        except Exception:
            pass

    if _attempted:
        if _binding is None:
            return None
        if _binding._class is not game_class:
            report(None, 'startup_conflict')
            return None
        try:
            from mt2sp_hub_hooks import install as bind
            return bind(game_class, _binding._runtime)
        except Exception:
            report(None, 'startup_conflict')
            return None
    _attempted = True
    # Check before importing the payload or runtime, including during a broken
    # installation. Clearing this variable later is not an in-process restart.
    if os.environ.get('MT2SP_HUB_SAFE_MODE'):
        return None
    runtime = None
    payload = None
    try:
        import sys
        if any(name in sys.modules for name in ('mt2sp_hub_runtime', 'mt2sp_hub_hooks', 'mt2sp_hub_payload')):
            raise ValueError('Hub startup namespace already occupied.')
        import base64
        from mt2sp_hub_runtime import Runtime
        from mt2sp_hub_hooks import install as bind
        import mt2sp_hub_payload as payload
        runtime = Runtime(diagnostic=report)
        loaded = set()
        for ident, dependencies, encoded in payload.ADDONS:
            if any(dependency not in loaded for dependency in dependencies):
                report(ident, 'dependency_failed')
                continue
            sources = dict((path, base64.b64decode(raw)) for path, raw in encoded.items())
            if runtime.load(ident, sources):
                loaded.add(ident)
        _binding = bind(game_class, runtime, diagnostic=lambda code: report(None, code))
        return _binding
    except Exception:
        if runtime is not None:
            try:
                runtime.shutdown()
            except Exception:
                report(None, 'startup_cleanup_failed')
        report(None, 'startup_failed')
        return None
    finally:
        if payload is not None:
            # Source maps now belong to their runtime contexts. Do not retain
            # another base64 copy for the whole client session.
            payload.ADDONS = ()
