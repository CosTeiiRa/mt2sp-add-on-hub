# Client bundle and startup

The experimental host can now prepare validated client packages for one shared startup entry. Creators still use [new, edit, build](GAME_CREATORS.md). They do not supply loader code, modify game scripts or manage checksums.

This is preparation and runtime code, not an installer. The CLI still refuses real game installation. A supported build, verified startup insertion, pack composition and recoverable deployment remain adapter responsibilities.

## Prepare enabled packages

[`prepare_client(packages, occupied_paths=...)`](../src/mt2sp_hub/installation/client.py) returns four original pack members: the bootstrap, runtime, lifecycle bridge and generated payload. It writes nothing and executes no add-on code. The generated payload contains base64 source bytes and dependency metadata, rather than executable author statements. Encoding is for transport, not secrecy or authenticity.

The caller supplies the explicitly enabled package selection and the complete reviewed pack inventory. Preparation validates package hashes, dependency versions/order, conflicts, APIs, component capabilities and aggregate package limits. Each client component must request only `client.module`, contain `PACKAGE_ID/main.py`, and place Python helpers beneath the same package ID. A server component must request `server.quest`; its quest contents and deployment must be checked separately. Host Python does not pretend to validate the embedded interpreter's syntax.

The four reserved `mt2sp_hub_*` module names cannot collide with the baseline, including case/path aliases, bytecode/native module variants or package directories. The coordinator may exclude previous Hub members from that inventory only after proving their ownership and unchanged bytes. Preparation never guesses that an existing file belongs to Hub.

An empty or server-only selection returns no client members. Removing the final client module will therefore require the coordinator to restore its owned startup change and remove the previous members; that disk operation is not implemented here.

Existing limits still apply: 128 packages, 2,048 original files, 64 MiB original output and 128 MiB selected archives. Generated members have a separate 128 MiB ceiling to accommodate encoding and host sources. That ceiling is a preparation bound, not evidence that the embedded client can comfortably load a maximum-size bundle; native memory/startup budgets still need measurement before release.

## One host startup call

The reviewed game adapter will insert one call to `mt2sp_hub_bootstrap.install(GameWindow)` after the class exists and before gameplay, on the UI thread. The [bootstrap](../src/mt2sp_hub/client_bootstrap.py) loads the generated bundle and installs the [shared bridge](CLIENT_HOOKS.md). An official startup/lifecycle interface could replace this pack insertion. Add-on authors should not perform it themselves.

The launcher sets `MT2SP_HUB_SAFE_MODE=1` in the child client's environment for safe launch. **Any nonempty value, including `0`, disables add-ons**; clear or unset it for normal launch. The bootstrap checks this before importing the runtime, bridge or payload. Safe launch therefore bypasses even missing runtime files or a broken payload, provided the bootstrap entry itself remains intact. A launcher button and recovery for damaged bootstrap/game files still need implementation.

Startup runs once per client process. Repeated calls with the same unchanged binding return that binding; another class, changed hooks, detached state or a failed first startup cannot silently create a second host. Clear failures with a fresh client launch, not an in-process retry. The bootstrap also refuses an already occupied runtime/payload module cache.

Client modules register in dependency order. If registration fails, their client dependents are skipped, including dependencies reached through server-only packages. Unrelated modules can still load. This does not confirm that any required server component is running: the future coordinator must verify that deployment before enabling the selection. Encoded payload copies are released after startup; each runtime context retains the source bytes it needs for lazy helpers.

The return value is the shared binding, or `None` after safe launch/startup failure. Host teardown calls `binding.detach()` when present. Optional `diagnostic(package_id_or_None, code)` receives the runtime's fixed codes plus `dependency_failed`, `startup_failed`, `startup_conflict` or `startup_cleanup_failed`; `None` identifies a host failure. Raw exception text, paths and tracebacks are excluded. Ordinary Python exception handling is not a security sandbox for trusted add-on code.

## Evidence and remaining work

Public synthetic tests cover deterministic preparation, source preservation, dependency order/failure, capability/path checks, baseline collisions, bounded selections, repeated startup, cleanup, diagnostic privacy and safe launch without runtime/payload imports.

A local test built four original creator packages and inserted the generated members plus the single startup call into an owned client copy. Importing the shipped game module registered two working modules, skipped a broken module and its dependent, and attached the shared bridge. Two native windows opened through simulated session notifications and cleaned up correctly. A second client process with safe mode passed with the runtime/bridge members deliberately absent and a payload that would raise if imported. Both ran under embedded Python 2.7.6, attempted no server connections and left original source packs unchanged; the temporary pack changes were restored in the copies.

This validates the local game-module import insertion and environment switch, not normal launcher navigation, login, map transitions or connected gameplay. Before enabling real installation, review the exact client build and startup/pack baseline, integrate the launcher switch, verify the server compiler/inventory and active deployment receipt, and implement coordinated attachment/deployment recovery. Private game files, tooling inputs and raw reports remain local.
