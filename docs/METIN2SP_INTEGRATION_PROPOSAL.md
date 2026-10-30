# Metin2SP extension integration proposal

Status: discussion proposal, prepared for a future conversation after the Hub foundation demonstration. These requests have not been agreed with the Metin2SP team. Suggested field names describe contracts, not existing APIs.

Hub will maintain the package manager, creator SDK, client runtime integration, local deployment adapters and documentation. Metin2SP remains authoritative for gameplay and official distribution. The objective is a small supported extension boundary that reduces per-build integration repairs without requiring the game team to operate a catalog or disclose the full engine source.

## When to discuss this proposal

After roadmap M4, demonstrate one client module, one server quest/configuration module and one combined module on a disposable supported installation. Bring a short compatibility report and a recovery demonstration. Ask the developers to review the smallest useful contracts first, then sequence deeper hooks separately.

There is no requirement to wait for every request before building the foundation. Synthetic adapters, the package engine and exact-build integrations can proceed independently. Unsupported engine capabilities stay unavailable until a reliable interface exists.

## Request priorities

The [minimal game integration decision](MINIMAL_GAME_INTEGRATION.md) is the concrete first slice behind these requests: one Python module entry, one quest resource type and one coordinated local deployment. It keeps author-facing package fields unchanged. For the first discussion, bring these acceptance questions:

| Request | Smallest useful developer deliverable | Demonstration |
| --- | --- | --- |
| U01/U02 | Build/compiler identifiers and supported module directories with documented update behaviour | An official update preserves module source/data and exposes its new build identity |
| U03 | One client loader entry and documented open/close/window lifecycle | Two small modules register and clean up without each patching startup code |
| U04 | A quest include/compile path with names and artifact inventory | A new quest compiles independently; duplicate names and compile errors leave the old deployment usable |
| U05/U06 | Shared update exclusion plus status showing the active deployment revision | Hub cannot overlap an update and can distinguish a running old revision from the newly requested one |

These are discussion targets, not claims that the official game already exposes these APIs. Hub can own the supported-build adapter and generated registration files; the team does not need to implement the package manager or catalog.

For the first conversation, the creator-facing outcome is simple: one documented place for a client module, one documented way to register a server quest/configuration module, and enough build/update information to keep them compatible. U01-U05 describe the small contracts that enable this. Ask the team to demonstrate a minimal module through each path; an add-on author should not need to patch the client bootstrap or a central Dockerfile. Deeper hooks remain feature-driven requests, not prerequisites for every add-on.

| ID | Request | Priority | Hub milestone helped | Can Hub proceed without it? |
| --- | --- | --- | --- | --- |
| U01 | Build and capability descriptor | First discussion | M1 to M6 | Yes, with a finite tested adapter/build matrix |
| U02 | Preserved extension directories and data ownership | First discussion | M2 to M6 | Yes, with guarded composition and explicit update review |
| U03 | Client loader and lifecycle hooks | First discussion | M2 and M4 | Yes on supported clients; each changed integration requires review |
| U04 | Server quest/configuration/content entry points | First discussion | M3 and M4 | Only for resources a tested fallback can deploy reliably |
| U05 | Updater coordination and shared exclusion | First discussion | M4 to M6 | Yes with idle-tool preconditions; no guarantee against external concurrent writers |
| U06 | Deployment command and runtime health receipt | Next discussion | M3 to M6 | Yes, using versioned launcher/container adapters |
| U07 | Structured reference-data export | Next discussion | M5 | Yes, using bounded readers with provenance limitations |
| U08 | Module persistence and migrations | When a module requires it | Extended server support | Initial quest/config modules can use existing state mechanisms |
| U09 | Namespaced client/server messages | When a live combined feature requires it | Extended combined support | Static/local UI and quest modules can work without a new live channel |
| U10 | Targeted gameplay hooks and supported settings | Later, feature driven | Library capabilities | The affected deep engine features must wait or remain explicit compatibility work |
| U11 | Developer compatibility/testing process | Before broad adoption | M6 onward | Yes, with slower independent validation |
| U12 | Distribution and support boundaries | Before ecosystem publication | M0 licensing and M7 library | Original platform planning can proceed; clarify game-related distribution scope |

## U01 Build and capability descriptor

**Request:** provide a documented, machine-readable descriptor for the installed client/server and the actually running server. A local JSON file plus a structured status command would be sufficient.

**Contract:** separate distribution version, client build ID, server build ID, data/schema revision, quest compiler version, supported scripting/API versions and named extension capabilities. Identify a pending restart or deployment when installed and running revisions differ. Use stable machine values with a descriptor schema version. Exclude credentials, account data and device identifiers.

**Acceptance:** after an official update and restart, Hub can identify the exact active combination and required capabilities without inspecting arbitrary binary offsets. Partial updates are distinguishable from completed ones. Missing or unknown fields fail conservatively.

**Fallback:** known-build fingerprints and adapter probes. API capability claims must never override a failed adapter-integrity check.

## U02 Preserved directories and ownership

**Request:** designate supported client/server extension directories and separate mutable module data from module code. Describe updater behaviour for each location.

**Contract:** define path restrictions, namespace rules, load order, precedence, supported encodings and whether a core resource can be extended or overridden. Preserve module settings/data during game updates. Keep official files authoritative; preservation must not silently activate incompatible code.

**Acceptance:** an official update leaves an installed extension's source/config/data intact, refreshes the game core, and allows compatibility to be rechecked before loading the extension. Removing one module cannot remove another's resources.

**Fallback:** compose supported resources over a captured current baseline and invalidate plans after external edits. Ask for directory preservation separately from granting arbitrary override access.

## U03 Client loader and lifecycle hooks

**Request:** load approved local module entry points through a single official client bootstrap with a small documented callback surface.

**Contract:** start with game open/close, window lifecycle and an external safe-launch switch that skips third-party code before import. Document callback arguments, call order, UI-thread ownership, cleanup, interpreter version and re-entrancy. Add map/atlas events and shortcuts when a concrete module needs them; native input/chat/IME bindings take priority. Hub can own namespaced module loading and window registrations.

**Current demonstration:** the [original greeting window and standalone runtime](GAME_CREATORS.md#client-one-registration-function), plus the [shared lifecycle bridge](CLIENT_HOOKS.md), pass synthetic tests and isolated native UI/session harnesses in owned client copies. The bridge binds and restores the shipped game class; its gameplay methods have not been invoked in this test. The smallest missing official hook is one startup entry plus a UI-thread notification after successful gameplay setup and before teardown, with safe launch decided before importing any add-on. An official notification path would let Hub remove the method wrappers. Authors already need no per-module patches; production startup and connected gameplay validation remain outstanding.

**Startup progress:** the [generated client bundle](CLIENT_STARTUP.md) now loads original packages through one game-module import insertion in an owned copy. Dependency failures stay isolated, and a separate native process proved that the environment safe-mode switch bypasses missing runtime files and a deliberately broken payload. Please expose that switch through the official launcher before module import, retain a base-game launch path, and document the startup callback's timing. The switch cannot repair a damaged bootstrap or game pack; Hub still needs verified composition/recovery. Normal launcher navigation and connected gameplay have not yet been validated.

**Acceptance:** two original modules coexist without replacing each other's shared hooks. Logout/map transitions dispose resources correctly. A callback exception is identified in diagnostics and its callback/window can be disabled. Safe launch works even if a module crashes during import. Blocking or native-code faults remain outside an exception-only isolation guarantee.

**Fallback:** a host-owned integration into known client packs with strict fingerprints. Every changed bootstrap structure requires adapter review; module authors do not each patch core lifecycle functions.

## U04 Server extension entry points

**Request:** provide a supported module directory for quests, configuration and selected content resources, with a documented compilation/registration path.

**Contract:** define quest names, entry registration, compiler invocation/version, compile order, errors and progress retention. Document which configuration keys support inclusion and which content resources have composable merge rules. Define content-ID allocation/conflict detection, duplicate handlers, reloadable resources and those requiring restart. Avoid requiring every add-on to modify the central Dockerfile or build scripts.

**Acceptance:** a new quest/configuration module installs through a documented path, survives restart/update, preserves quest state and can be disabled/removed. Duplicate IDs/quest names fail before activation. Compilation failure retains the previous usable server build. Invalid modules have a documented boot behaviour.

**Fallback:** a finite adapter for existing supported quest/configuration mechanisms. Resources without a verified composition/deployment path are unavailable. This request is the main enabler for broad server modules; it does not require native dynamic libraries in the first release.

**Current demonstration:** the [fixed isolated compiler](QUEST_COMPILATION.md) verifies pinned inputs and captures validated artifacts plus a preparation receipt. Native login/dialog/timer fixtures produced 11 artifacts; malformed source and timeout fixtures were rejected, cleanup was verified, and no host/world-data mount or live restart was used. The missing contract is a versioned compiler/input recipe with an authoritative artifact/quest inventory and one supported include path. Please also provide structured error fields such as quest name, source line and error code, so creators can fix syntax errors without exposing raw logs or local paths. Compilation alone does not demonstrate loading, removal or update compatibility.

## U05 Updater cooperation

**Request:** agree on a local mutation lock and a completed-update receipt shared by the official launcher, Hub and participating authoring tools.

**Contract:** identify installations consistently; hold exclusion across affected client/server files; define lock ownership, process-crash handling and retry behaviour. Describe pre-update/post-update state and updated component revisions. Preserve desired module state while allowing incompatible modules to remain disabled. Notifications are data or fixed commands, not automatic execution of arbitrary add-on installers.

**Acceptance:** starting an update while Hub applies a module results in a visible wait/refusal, never competing writes. A crashed process does not leave a permanent lock. An interrupted update is distinguishable from a completed one. Official updating and safe game launch remain possible without the Hub service running.

**Fallback:** close other mutation tools, inspect process state and recheck fingerprints. Document the remaining race with tools that ignore the lock. Hub must not claim coordination solely because it owns its own state-folder lock.

## U06 Deployment and health interface

**Request:** expose a documented local command interface for status, validation, quest compilation/build, controlled stop/start and health inspection. An authenticated local API is optional; a CLI with JSON output is enough.

**Contract:** stable exit codes, operation IDs, progress, timeouts, cancellation boundaries and the installation target. Return active build/content revision and module/quest load failures. Separate read-only status from mutations. The game retains responsibility for its service layout and required startup sequence.

**Acceptance:** Hub can distinguish a failed build, a failed restart and a running-but-wrong revision. A failed preflight does not stop a healthy server. After restart, health proves that the requested deployment is active rather than merely reporting an open process/port.

**Fallback:** versioned launcher/container adapters with bounded commands and explicit health limitations. Never accept an arbitrary shell command from a package manifest.

### Minimal build and status receipt

The current Hub probe can associate one Docker game container with a selected folder and observe its state/health. It cannot establish the persistent world or prove that a particular quest deployment is active. This is the concrete gap behind U01 and U06, not a request for a new hosted service.

Propose two small interfaces: a read-only build descriptor shipped with the game, and a read-only `status --json` operation supplied by the launcher/server. Names below are discussion examples, not existing commands or supported SDK fields.

| Field | Where | Required meaning |
| --- | --- | --- |
| `schema` | Both | Explicit descriptor version; unknown schemas are unsupported |
| `client_build`, `server_build`, `quest_compiler_build` | Build descriptor | Stable exact-build identifiers with a documented compatibility policy |
| `extension_api` and capabilities | Build descriptor | Only interfaces actually available in that build |
| `world_id` | Local status | Stable identity of the persistent world; define clone/reset behaviour; never a public diagnostic field |
| `server_build` | Local status | Build actually running, rather than the version file on disk |
| `deployment_revision` | Local status | Digest of the effective loaded code/quest inventory, including supported add-ons; not a mutable image tag |
| `phase` and failure codes | Local status | Starting, ready or failed; code/quest-load failures prevent ready status |

Hub compares the active build and deployment revision with the reviewed plan. Missing, stale or mismatched evidence keeps verification pending and blocks a successful installation claim. The status response must exclude credentials, player records, raw logs and environment variables. Hub keeps world identity private and exports only sanitized outcomes.

Acceptance demonstration: start the previous deployment and verify that Hub rejects it as confirmation for a new plan; then load the requested revision and confirm it. A quest-load failure must remain distinguishable from a healthy container. Repeat against a second world to prove that a matching build alone cannot select the wrong save. Until this contract or an equivalent tested adapter exists, container health remains an observation only.

## U07 Structured reference data

**Request:** provide read-only exports for item/mob definitions, maps, recipes, refinements and supported drop relationships.

**Contract:** version the schema; distinguish saved configuration from applied/live/effective values; include build/content revision and generation time. Specify stable IDs, localization lookup, units and unknown values. Mark approximate or configuration-only results. Keep accounts, inventories, credentials and personal gameplay records out of this public-reference interface. A local export file is sufficient.

**Acceptance:** Atlas/Wiki and creator tools read the same documented structure across compatible game updates. A recipe/drop rule unavailable from the engine remains unknown rather than being reconstructed as an asserted probability. Cached exports can be identified as stale.

**Fallback:** local file parsers and bounded read-only queries, with source labels and no claims of live telemetry. Game assets are read locally rather than redistributed in packages.

## U08 Module persistence and migrations

**Request:** define supported namespaced persistence for server modules, starting with the quest-state facilities already available and expanding only when needed.

**Contract:** module identity, scoped data access, schema revision, migration ordering/checksums, failure reporting, backup integration and uninstall retention. Define whether any DDL is transactional. Provide a policy for cleanup of effects and referenced content, including offline characters. Credentials remain server-local.

**Acceptance:** retrying an interrupted supported migration does not duplicate rows or lose progress. A failed migration cannot be reported as healthy. Disable/uninstall retains data by default; purge is explicit. Backups include required module state and can be restored consistently with its code revision.

**Fallback:** limit first-release examples to existing quest/configuration state. Defer packages needing unsupported table migrations instead of running ad hoc SQL.

## U09 Namespaced client and server messaging

**Request:** when a feature needs live interaction, provide a versioned extension message channel with per-module routing.

**Contract:** negotiate component/protocol versions, bound message size/rate, validate payloads and apply server-side authorization. Define disconnect/error behaviour and whether a client component is mandatory or optional. Never treat a client declaration as authority to award items, change stats or invoke administration operations.

**Acceptance:** unknown/mismatched modules and malformed or excessive messages are rejected without crashing the game. A combined feature stays unavailable when required component versions disagree. Optional UI extensions do not block unrelated gameplay.

**Fallback:** static snapshots and existing documented gameplay paths. Do not invent packets or use a privileged local management API as the in-game protocol.

## U10 Targeted gameplay hooks and settings

**Request:** add small hooks or configuration settings driven by concrete module use cases. Early candidates are mount activation/bonuses, supported mounted-combat behaviour and explicit combat-bonus limits. Later candidates can include rewards, loot, NPC interactions, events and bot behaviour.

**Contract:** specify event timing, arguments, read/write permissions, ordering, cancellation semantics, recursion/thread rules and cost limits. Distinguish an observation event from a hook that changes authoritative calculations. Publish defaults and how multiple handlers compose.

**Acceptance:** a reference module achieves the agreed feature through a documented hook/setting on two supported builds, with deterministic behaviour and acceptable measured cost. Disabling it restores documented defaults without binary repair.

**Fallback:** keep unsupported native changes out of the normal SDK. Existing exact-build repairs, if retained, remain separately labelled compatibility work with their own evidence and removal rules. Prefer upstream bug fixes where the requested behaviour belongs in the base game.

## U11 Compatibility and developer process

**Request:** designate a technical contact or proposal route, publish extension-related changes and provide an optional pre-release validation opportunity.

**Contract:** document API versioning/deprecation, supported-build policy, a minimal original example and a way to report extension failures separately from base-game failures. Agree what synthetic fixtures and aggregate test evidence may be shared. A development build or harness is useful only within permitted distribution terms.

**Acceptance:** a breaking change names the affected contract and migration path. The Hub team can run a small conformance suite and report a reproducible failure without uploading a user's installation or credentials.

**Fallback:** public release notes and independent tests after each release. Report unverified compatibility honestly rather than asserting support from version strings alone.

## U12 Distribution and support boundaries

**Request:** clarify the intended scope for a public SDK, original module source/packages, a GitHub library/index and links from Discord. Agree naming/attribution and whether any collaboration is official.

The project's published README describes a protected server distribution and mentions add-on sharing through Discord. That does not settle every proposed catalog or SDK distribution detail; ask the team for a clear project statement. [Metin2SP project guidance](https://github.com/TieruYT/metin2-playerbots/blob/main/README_EN.md#-licence).

**Contract:** identify material creators may distribute, required attribution, acceptable hosting/discovery, support ownership and how to report a harmful/broken module. Game binaries, pack keys, extracted assets and user state are excluded from Hub packages unless separately authorized and deliberately reviewed.

**Acceptance:** publish a concise agreed boundary before opening the library to submissions. The Hub team can tell users where a base-game issue, platform issue and module issue belongs. Do not imply approval or partnership before it exists.

**Fallback:** publish only reviewed original platform material and synthetic examples while clarifying the remaining scope. Do not redistribute the game to make an example convenient.

## Proposed discussion brief

> We are building a standalone extension platform for Metin2SP with client, server and combined modules. It will manage packages, compatibility, deployment and recovery independently of our authoring tools.
>
> Once our foundation demonstration is ready, we would like to agree on a small supported integration boundary: build/capability metadata, preserved module directories, a client loader, a server quest/configuration path, and updater coordination.
>
> We can maintain the Hub, public SDK, examples and library. Your team would retain control of gameplay, the launcher and official updates. A local descriptor and documented commands are enough for several of the first requests; a large web API is unnecessary.
>
> We would also like to clarify public GitHub distribution of original modules and the SDK, attribution and support boundaries. We can bring concrete examples and failure/recovery tests so the discussion stays focused on the smallest useful changes.

## Discussion outcomes to record

For each request, record accepted/deferred/declined status, the agreed contract owner, target API/build version, test example and migration policy. Keep private discussions and contact details out of the repository. Publish agreed technical outcomes only with permission to share them. Update fallbacks when official interfaces become available; do not leave two competing deployment paths active for the same resource.
