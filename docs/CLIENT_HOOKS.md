# Shared client lifecycle bridge

The experimental [bridge](../src/mt2sp_hub/client_hooks.py) connects the [standalone runtime](../src/mt2sp_hub/client_runtime.py) to a verified client class's ordinary `Open` and `Close` methods. This is adapter code. Add-on authors keep using `register(context)` and the [creator API](GAME_CREATORS.md); they do not patch game classes.

## Host sequence

1. Select a reviewed build and startup point. The bridge checks method shape and ownership only; it cannot establish build compatibility or detect another tool's unmarked patches.
2. Decide safe launch before reading or importing add-on sources. Construct `Runtime(safe_mode=...)`; load verified enabled source maps in dependency order only during normal launch.
3. On the UI thread, before the first gameplay session, call `client_hooks.install(GameWindow, runtime, diagnostic=...)`. The return value is a binding. During safe launch it returns `None` without inspecting or modifying the game class.
4. Let the game's own calls drive the lifecycle. At host teardown call `binding.detach()` if a binding exists. This shuts down the runtime and restores owned methods. It is not hot reload or a disk/package uninstall.

An official startup entry plus direct lifecycle notifications can call `Runtime.game_open(game)` and `game_close(game)` without this method bridge. Prefer that path when the game provides it. Do not install both paths for the same runtime.

## Ordering and failure behavior

| Situation | Behavior |
| --- | --- |
| Game `Open` returns normally | Preserve its result, then notify add-ons |
| Game `Open` raises | Preserve its exception; do not notify an opened session |
| Game `Close` is called | Notify add-ons and dispose their windows before the game's teardown; preserve its result or exception |
| Repeated setup with the same host | Return the existing binding without stacking wrappers |
| Second host, inherited binding, unknown marker or changed methods | Refuse installation; require a clean client restart |
| Add-on callback/window fails | Use the runtime's existing per-add-on failure isolation |
| Unexpected runtime error | Disable the bridge for this run, attempt runtime shutdown, and continue the game's method |
| Another tool changes a bound method | Detach restores only methods still owned by this binding; it preserves the external method and makes any captured Hub wrapper inert |

`detach()` returns `True` when both methods and the ownership marker were restored. `False` means ownership changed; restart the client before rebinding. Repeated detach has no effect, including after a new binding has been installed. Window cleanup is attempted even when ownership changed. The optional host diagnostic callback receives only `hook_failed` or `hook_cleanup_failed`; exceptions from that callback are contained. No exception text, file paths or stack traces are emitted by the bridge.

The bridge accepts methods defined directly as Python functions on the selected class. It deliberately does not guess at inherited methods, descriptors, native functions, input hooks or arbitrary events. Runtime loading, game build verification, pack composition, launcher safe mode and installation recovery remain separate host responsibilities. Add-ons are trusted Python; ordinary exception handling cannot contain blocking or native code.

## Evidence and remaining gates

Public tests use invented game classes and exercise ordering, arguments/results, original exceptions, successive sessions, duplicate installation, ownership conflicts, cleanup and host/add-on failures.

A local test in an owned client copy passed under embedded Python 2.7.6. It bound and restored the shipped `GameWindow` class without invoking its gameplay methods. It also drove two original greeting windows through the bridge using an invented native UI game fixture, including failed open/close, repeated setup, stale close and external-hook preservation. Old-style Python classes and safe launch passed. No server connection was attempted; original source packs were verified unchanged, and the temporary startup replacement was restored in the copy.

This proves native bridge execution and shipped-class binding, not connected gameplay or the production startup insertion. Before real installation, verify that insertion and safe-launch path against an exact build, then test login, logout, map transitions and shutdown on a disposable installation. Raw reports, game copies, pack inputs and private build fingerprints stay local. The current CLI still refuses real game installation.

The subsequent [startup-bundle work](CLIENT_STARTUP.md) now verifies a local game-module import insertion and an environment safe-mode switch in owned copies. Normal launcher integration, build support and connected gameplay remain separate gates.
