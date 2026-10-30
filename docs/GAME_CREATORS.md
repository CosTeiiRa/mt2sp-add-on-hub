# Create experimental game add-on sources

This preview creates original client Python and server quest sources using the same format-2 manifest and builder as sandbox projects. It is for developing the integration, not a supported game release. Hub still refuses to install these packages. The [sandbox guide](CREATING_ADDONS.md) remains the way to exercise installation and recovery today.

## Create, edit, build

In PowerShell from the Hub checkout:

```powershell
$env:PYTHONPATH = "src"
python -m mt2sp_hub new scratch/hello-game --id example.hello --kind combined --profile game
python -m mt2sp_hub build scratch/hello-game scratch/hello-game-0.1.0.zip
```

Choose `client`, `server` or `combined`. Omitting `--profile game` keeps the existing sandbox starter. The combined source contains:

```text
hello-game/
  addon.json
  payload/
    client/main.py
    client/window.py
    server/example_hello_greeting.quest
```

Edit the window's title/message or the quest's greeting, then build again. Increase the package version when publishing changed bytes. The builder generates hashes, verifies the archive and leaves source unchanged. It does not execute Python or compile quests; a valid archive is not proof of valid gameplay code. Keep your README, tests, Git directory and output ZIP outside the package source folder.

The manifest requires `client.module`, `server.quest`, or both. Targets stay under the package ID, with server quests beneath `quests/`. These capability requirements intentionally prevent the synthetic installer from treating game sources as ordinary fixture files. There is no new package format, installer script or author-supplied Docker command.

## Client: one registration function

The entry file is `main.py`:

```python
def register(context):
    window = context.module('window')
    greeting = context.register_window('greeting', window.Greeting)
    context.on('game.open', lambda game: greeting.open())
```

Register callbacks and windows inside `register(context)`. `context.module('window')` loads the declared local `window.py`; dotted names select declared nested helpers. The runtime keeps each add-on's module cache separate. Helpers are not imported through another add-on's ID or physical game paths.

The generated window implements `Open`, `Close`, `IsShow` and `Destroy`. It appears when gameplay opens, can be closed normally, and is destroyed when the session closes. The next session receives a fresh window. The example changes no game classes, keys, player data or gameplay rules. Authors can replace the window's contents without adding installation code.

| Call | Current runtime behavior |
| --- | --- |
| `context.on('game.open', callback)` | Calls `callback(game)` after the host signals an open gameplay session |
| `context.on('game.close', callback)` | Calls it before the host tears down that session; cleanup follows even if a callback fails |
| `context.register_window(name, factory)` | Registers a package-local name and returns a handle; factory receives the current game object lazily |
| `handle.open()` / `handle.toggle()` | Operates that window; returns false outside gameplay or after its failure/removal |
| `context.module(name)` | Loads/caches only a declared local Python helper |
| `context.log(message)` | Optional private local log sink; free-form text is excluded from public diagnostics |

Use the game's embedded Python syntax and libraries. The starter is ASCII and uses Python 2.7-compatible syntax. Modern host Python features are not automatically available in the game. The current runtime and two original greeting windows passed an isolated native UI harness using the selected client's embedded Python 2.7.6. That is evidence for this local test, not a general supported-build promise.

## Server: one quest per source file

The greeting quest sends a chat message on login. It awards nothing, changes no database schema and introduces no persistent quest flags. Its declared quest name matches its filename. The starter converts dots/hyphens in the package ID to underscores and appends `_greeting`; names over 64 characters are refused by this starter.

Keep the quest name stable: real quests may use it to identify saved progress. Prefix conversion is not a uniqueness guarantee. The [quest-staging helpers](QUEST_STAGING.md) now check names and compiled artifact ownership against supplied official/selected inventories; wiring them to a verified compiler recipe and authoritative game inventory remains adapter work. Do not install by editing the official quest list or Dockerfile manually.

A local, isolated compiler check accepted two generated greeting quests, produced their four expected state/login artifacts without changing the first quest's output, and rejected malformed source. The test used an already installed compiler and function list mounted read-only, with temporary container storage and no network or world-data mounts. No compiler binaries, function lists, private build fingerprints or container details are published here. This confirms only that local compiler experiment, not deployment, loading or compatibility with another build.

## Runtime boundary and remaining work

The [standalone runtime](../src/mt2sp_hub/client_runtime.py) has no Studio imports, game-class patching, physical source lookup or installation logic. The new [startup bundle](CLIENT_STARTUP.md) prepares verified enabled-package source maps and loads them in dependency order before gameplay. The separate [shared lifecycle bridge](CLIENT_HOOKS.md) connects a verified game class's `Open`/`Close` to runtime notifications on the UI thread. Authors do not install these hooks. `shutdown()` disposes registrations and windows. The bootstrap's environment safe-mode switch bypasses payload/runtime imports entirely; a normal launcher control and recoverable pack installation are still future work.

Registration failure removes that module's registrations; startup skips its client dependents while allowing unrelated modules to load. Callback failure disables only that callback. Window failure disables that window for the client run; other modules remain active. Add-on diagnostics contain a validated package ID and a fixed failure code, without exception text or stack traces; bootstrap host failures use `None` instead of a package ID. This handles ordinary Python exceptions; trusted add-ons can still block or mutate the process and are not security-sandboxed.

Automated tests exercise multiple modules, same-named helpers/windows, successive sessions, failed registration/callbacks/windows, cleanup and the generated UI through invented widgets. These public CI tests run under host Python. Local tests in owned client copies passed native registration, safe mode, two independent windows/helpers, toggling and cleanup. The bridge also passed native fixture sessions and bound/restored the shipped game class without invoking its gameplay methods. No login was attempted; original source packs were verified unchanged and temporary startup replacements were restored in the copies. These tests did not verify production startup or connected gameplay. Client copies, pack tooling inputs and raw native reports remain local. Creator ease of use still needs an independent user's trial.

The generated startup bundle also passed a local game-module import insertion and a separate native safe launch with missing runtime members and a deliberately broken payload. [The startup evidence](CLIENT_STARTUP.md#evidence-and-remaining-work) records that narrower test. Before real installation: verify normal launcher startup/safe launch and connected game-phase behavior on a disposable supported build, integrate the quest staging checks with an exact compiler profile and official inventory, prove the active deployment receipt, then implement recoverable attachment and coordinated deployment. The [minimal integration decision](MINIMAL_GAME_INTEGRATION.md) and [developer requests](METIN2SP_INTEGRATION_PROPOSAL.md) keep those contracts separate from this source-authoring preview.
