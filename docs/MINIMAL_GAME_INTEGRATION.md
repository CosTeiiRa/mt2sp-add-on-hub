# Minimal client/server integration

Status: implementation decision for the next real-adapter work, 30 October 2026. This document defines the boundary; it does **not** enable installation into a game. The current installation commands still accept only synthetic sandboxes. Capability names and runtime calls below must be implemented and tested before they become a supported SDK.

The initial `probe` command reads a selected game layout and existing ownership metadata without mutation. Optional `--runtime` checks a local Docker container's folder association, state and health. [Its scope and statuses](FOUNDATION.md#read-only-game-probe) are narrower than the full adapter probe below: verified builds, persistent-world identity, active deployment receipts and real attachment are not implemented yet.

## What an author supplies

Keep the existing format-2 package and `new` / edit / `build` workflow. A first real add-on supplies its manifest and either a Python module, a quest, or both:

```text
package/
  addon.json
  payload/
    client/main.py
    server/example_hello_greeting.quest
```

| Component | First supported resource | Author responsibility | Hub responsibility |
| --- | --- | --- | --- |
| Client | One module with a `main.py` entry and optional local Python helpers | Implement `register(context)` and the feature | Namespaced loading, shared game hooks, window cleanup and pack composition |
| Server | Quest source, one named quest per file | Write the quest and keep its name stable across updates | Claim quest names, compile, assemble deployment, restart and verify |
| Combined | Both resources in the same package | Supply both components under one ID/version | One review, one installation record and coordinated recovery |

No author-supplied installer, Dockerfile patch, shell command, SQL migration or executable repair belongs in this first contract. Typed configuration, content tables and extra UI/resource APIs follow a concrete add-on that needs them. Existing engine-specific repairs remain separate compatibility work.

The component declaration uses existing fields. The experimental `new --profile game` starter now generates this **real-client capability requirement**, without granting installation support:

```json
{
  "api": ">=1.0.0 <2.0.0",
  "capabilities": ["client.module"],
  "files": [
    {"source": "client/main.py", "target": "example.hello/main.py"}
  ]
}
```

The server counterpart requires `server.quest`, with a source such as `server/example_hello_greeting.quest` and target `example.hello/quests/example_hello_greeting.quest`. These are logical component-relative destinations. The adapter maps them into approved game resources; authors never specify physical game paths. Every real-component target must start with its package ID. The builder continues generating archive hashes. The synthetic adapter rejects these real-game capabilities.

The entry path is a convention, so this first slice needs no new manifest field or package format. [Game-source starters](GAME_CREATORS.md) implement this creator contract. Adapter/API selection belongs to Hub's reviewed build profile, not a package-selected plug-in or script. Capability `fixture.files` remains exclusively for the synthetic adapter. The game profile must reject fixture-only components rather than interpreting them as real resources.

## Small client runtime

The standalone lifecycle runtime is implemented and tested using invented widgets under host Python. It also passed a local native UI/session harness in an owned client copy under embedded Python 2.7.6. Normal game-phase/bootstrap integration, connected gameplay and a supported game profile remain outstanding. The behavior below is the experimental runtime contract, not a stable SDK compatibility promise.

Use one host-owned bootstrap. At client startup it reads the verified enabled-package list and loads each module's `main.py` in its own namespace. Imports between a module's helper files go through `context.module(name)`; an author need not construct private loader paths. Loading one add-on must not replace another add-on's module in the interpreter cache.

Start with the existing runtime concepts and this small public surface, now exercised by the original greeting-window starter. Verify it natively and publish a matching editor stub before calling the SDK stable. Keep the host Python version separate from the game's embedded Python syntax and libraries.

| Call | Contract |
| --- | --- |
| `register(context)` | Called once per module at client startup; register callbacks/windows, without needing an active character |
| `context.on(event, callback)` | Initially `game.open` and `game.close`; call `callback(game)` on the game UI thread after gameplay setup or before its teardown |
| `context.register_window(name, factory)` | Namespaced by add-on ID; return a handle with `open()` and `toggle()`. Call `factory(game)` lazily for each gameplay session |
| Window returned by `factory(game)` | Provides `Open()`, `Close()`, `IsShow()` and `Destroy()`; runtime calls `Destroy()` during cleanup |
| `context.module(name)` | Load a declared local Python helper inside this add-on's namespace; reject traversal and cross-module lookup |
| `context.log(message)` | Attribute diagnostics to the module; support reports omit private paths and local credentials |

The runtime owns registrations. It disposes a session's windows when gameplay closes and recreates them through their factories on the next session. Registration failure removes that module's registrations; callback failure disables the failing callback and identifies its module. This is exception handling, not a security sandbox or protection against blocking/native code. A safe-launch switch must bypass third-party imports entirely.

For the first release, close the client before installing, updating, disabling or removing modules. Enablement takes effect at the next launch. Hot reload, global key interception and broad reference-data exports are not prerequisites for the first window. A creator should not patch the game's classes or startup script independently.

## Small server integration

The [quest-staging helpers](QUEST_STAGING.md) implement source identity/collision checks and read-only compiler artifact validation. Local original quests passed those checks using actual compiler output. The exact compiler profile, authoritative official inventories, compilation orchestration and deployment remain unimplemented.

Accept one named quest per `.quest` file under the package namespace. The declared quest name must match the filename. The starter will generate a readable prefixed name such as `example_hello_greeting`; the adapter checks the actual name against both official quests and every selected add-on. Package dependencies do not permit duplicate quest names. Prefix conversion alone is not a uniqueness guarantee.

The adapter validates names, compiler-compatible encoding and supported syntax, then compiles in an isolated staging directory using the supported game's compiler recipe. Verify the resulting artifact inventory against the declared quest names; reject unexpected outputs and multiple declarations. Do not rely on a regex alone as proof of quest ownership. Do not rewrite quest identifiers silently: they can identify saved progress.

Hub owns a single generated registration/include set for its enabled quests. It composes that set with a verified official baseline, rather than having each add-on edit a central quest list or Docker build script. Prefer an official include directory when available. A fallback must be limited to a reviewed build and must reject external edits or an unknown compiler/layout before deployment.

Compile before stopping the running server. A compiler failure leaves the current deployment running. A successful deployment records the exact compiled-content revision and verifies that the intended server revision is running. A live process or open port alone is insufficient evidence. If the adapter cannot establish that evidence, report deployment as unverified and do not advertise the profile as supported.

Keep the first server profile narrow: its preflight requires a running server with a verifiable active revision. A stopped/unavailable server is a blocker with instructions to start it through the normal game launcher. Client-only changes do not require a server restart. Support for deliberately leaving a newly deployed server stopped can follow a demonstrated need.

Disable/remove excludes the owned quest artifacts while retaining player quest state. No automatic data purge or database rollback is offered. First examples must have reversible activation without rewards, new items, schema changes or persistent effects needing a cleanup quest. Broader gameplay effects require a separate tested lifecycle policy.

## One game adapter, five operations

Use one built-in adapter for the supported local Windows/Docker installation, with client and server helpers inside it. Do not introduce a provider registry, third-party adapter loading or another service. The existing engine continues to own package selection, content objects, ownership, locking, plans, journals and receipts.

| Operation | Inputs and output | Allowed effects |
| --- | --- | --- |
| `probe(binding)` | Read local target identity, client/server/compiler builds, capabilities, fingerprints and busy state; return a snapshot | Read only; no repair or deployment |
| `prepare(snapshot, selection, staging)` | Return staged artifacts, input fingerprints, owned file/quest claims, required downtime and previous/desired deployment identities | Write only private staging/cache; run only the adapter's fixed compiler/build recipe |
| `activate(prepared, journal)` | Perform the fixed deployment sequence below and return per-component deployment receipts | Mutate only reviewed resources; journal each step before it starts |
| `verify(prepared)` | Compare installed artifacts and the active server deployment with the expected revision; return structured evidence | Read only; never start a service as a side effect |
| `recover(prepared, journal)` | Inspect actual before/after evidence, restore the previous deployment or finish a committed operation | Use retained local artifacts and the same fixed steps; preserve conflicting external edits |

`prepared` is serializable data, not callbacks or arbitrary command strings: operation/installation ID, adapter revision, input digests, component/package versions, owned resources, before/after object references, and expected deployment revisions. Large bytes stay in the existing object store. The journal records the phase, intended transition and observed receipt. Recovery cannot depend on an in-memory Python object or the original download.

A component receipt identifies its adapter revision, target/build, artifact digest and deployment evidence. Distinguish **deployed**, **runtime confirmation pending** and **verified**. A closed client can have its pack and enabled list verified while native module loading remains pending until launch. Server health must identify the running deployment. Installed-state success must never imply that native gameplay testing happened.

The existing synthetic `Manager` is not yet a general game coordinator. Introduce this boundary while implementing the first real adapter; do not pass a game directory into the synthetic filesystem writer. Keep the small package engine free of Docker, game imports and Studio objects.

## One local owner, no registry service

Initially bind one selected client to one local world. Keep authoritative state in the world's fixed `.mt2sp-hub` directory. Do not offer a second writable state-directory setting. A user-interface list of recent installations is only a convenience; it is not ownership authority.

Both canonical roots use a fixed `.mt2sp-hub/lock`. The client also holds a private claim naming the installation ID and coordinator binding. Attaching acquires both locks in canonical path order (one lock when roots coincide), checks existing claims and uses exclusive claim creation. A second world cannot claim the same client. The server probe must also verify the expected local Docker project and persistent-world identity; an ambiguous/shared deployment is rejected.

The future attach operation is recoverable: persist a pending attachment record before creating claims, then mark it ready only after both roots and the server identity verify. A crash leaves an explicit pending attachment; retry must inspect it rather than create another owner. Release or repair only claims proven to belong to that operation. Moved/copied roots remain refused until an explicit relocation/clone flow is implemented. Local paths and Docker details stay private.

The experimental ownership reader recognizes checksummed envelopes using the existing `sha256`/`data` record convention. World `identity.json` data has exact fields `schema: 1`, `kind: "metin2sp"`, a 32-character lowercase hexadecimal `id`, canonical normalized `world_root` and `client_root`, and `attachment: "pending"` or `"ready"`. Client `claim.json` has `schema: 1`, `kind: "metin2sp-client"`, the matching `installation` ID and the same two root bindings. Records are limited to 64 KiB. These are private internal records, not creator manifests. Do not hand-create them to enable installation: the current reader never grants write access, and no real attachment writer exists yet.

Studio and cooperating tools must use the same coordinator and locks. An official updater that ignores those locks remains a known race; require it idle and recheck inputs. Do not claim that Hub's lock controls unrelated tools.

## Fixed activation and recovery sequence

1. Planning probes and prepares both components under the target locks, writing only staging/cache. Verify compilation and capture exact staged-artifact digests. Review shows owned resources, build compatibility, client-close requirement, expected restart and retained player data.
2. Apply reacquires both locks, rechecks target identities/fingerprints and refuses pending recovery or a running client. Changed build inputs invalidate the plan; do not silently recompile different outputs after review.
3. Verify the reviewed staged artifacts, ownership claims and disk-space preflight. Store backups and the full planned before/after deployment before mutation.
4. For server changes, journal intent and stop the server once. Record the completed stop. Client-only changes do not stop it.
5. While it is stopped, journal and replace the reviewed server artifacts and client pack outputs, then verify them. Each step has a fixed adapter-owned name and an idempotent before/after check.
6. Start the intended server deployment when required and verify its revision. Record component receipts, then commit installation state and clear the journal.

On interruption before state commit, inspect the journal and actual deployment, then restore the prior client/server artifacts and prior running server revision when safe. Keep the operation pending if restoration or health verification fails. After state commit, verify the desired artifacts and complete the receipt. Never call a mixed deployment healthy or restore an old backup over an official game update.

The first real profile accepts only transitions with a verified restoration path. The fixed stop/replace/start steps live in adapter code; this is not a package-authored workflow language. Failure tests must cover each intent/completion boundary, including a crash during recovery.

## Acceptance before enabling real installs

- **Creator:** a person using only public tools creates one client window, one harmless greeting quest and a combined package. Both modules are original; the combined example needs no new network protocol.
- **Coexistence:** two client modules and two quests work independently. Namespace/quest collisions are rejected before downtime. A module failure does not remove another module's registrations.
- **Lifecycle:** install, update, disable, enable and remove all three package types on a disposable supported game copy; retained quest state and unrelated resources survive.
- **Ownership:** simultaneous attach/apply from two processes and attempts to claim the same client/world are refused; interrupted attachment is recoverable.
- **Failure:** compiler failure leaves the server running; every stop/write/restart/state boundary can be interrupted and recovered without a falsely healthy mixed revision.
- **Evidence:** verify actual compiler/runtime compatibility and connected gameplay separately from package/fixture tests. Unknown builds, running clients, updater activity and insufficient health evidence block support.

The relevant developer requests are [U01-U06 in the integration proposal](METIN2SP_INTEGRATION_PROPOSAL.md). Ask for the small loader/include/status/lock contracts first. This design requires neither engine source disclosure nor a game-team-operated add-on catalog.
