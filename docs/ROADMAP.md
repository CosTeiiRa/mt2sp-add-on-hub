# Foundation roadmap

Status: 30 October 2026. The M1 package/synthetic-installation acceptance checks are implemented, and the minimal real-adapter boundary is defined. [Foundation implementation](FOUNDATION.md) records the limits, measurements and recovery evidence. M2/M3 real-game implementation and the public alpha gates remain unfulfilled; this is not gameplay certification.

Build a reliable standalone extension platform before growing the add-on catalog. The first usable Hub release includes client modules, server modules and combined modules. Internal milestones are engineering checkpoints, not separate client-only product releases.

## Product commitments

- Hub works without Studio, a private repository, a hosted account or a running catalog service.
- Initial support is Windows and a local Metin2SP Docker world. Remote servers, VPS administration and multiple administrators are later work.
- The Hub repository owns the platform, SDK and small synthetic examples. Usable add-ons will live in the future `mt2sp-add-on-library` with independent releases.
- Official game updates remain available independently. Unsupported modules are reported and kept inactive where the integration permits; Hub does not pin users to an old game build.
- Client and server changes use one reviewed operation, explicit ownership and durable recovery records.
- Public source, fixtures, diagnostics and artifacts contain no personal installation data or game distribution files.
- Keep authoring to a small manifest and module files; tools generate checksums and packaging details. Add a new abstraction only when a working module demonstrates the need.
- Judge ease of use by independent users completing real tasks, not by how many platform features exist.

## Next practical steps

1. **Make the creator loop usable now.** Implemented: `new`, edit, `build`, then reviewed sandbox installation for synthetic files. [Creator guide](CREATING_ADDONS.md). Experimental [`--profile game` starters](GAME_CREATORS.md) now generate a client window, a server greeting quest or both; these build but cannot yet install. All starters share one format; no manual checksum maintenance.
2. **Keep the M1 checks as regression gates.** Completed: actual 2,048-file/128-package lifecycles, exact byte boundaries, full-size measurements and interrupted-write recovery; see [foundation evidence](FOUNDATION.md). All limits apply together, including disabled packages in the selected-cache budget.
3. **Implement and prove small real examples.** Follow the [minimal integration decision](MINIMAL_GAME_INTEGRATION.md): one built-in game adapter, a client module and a server quest, followed by a combined example. Read-only layout/ownership inspection and optional local Docker folder/state/health checks are implemented. The client runtime passes synthetic tests and an isolated native UI/session harness. [Quest source/artifact ownership checks](QUEST_STAGING.md) now pass against original compiled examples. Normal client game-phase integration, a tested build/compiler profile with authoritative inventories, persistent-world identity and active deployment receipts remain next, followed by recoverable attachment, compilation orchestration and journaled activation. A creator must not edit game bootstrap code or Docker build scripts for each add-on. Document missing game hooks in the [developer proposal](METIN2SP_INTEGRATION_PROPOSAL.md).
4. **Make installation understandable.** Build a small interface around the same engine: select installation, import package, review, install; then enable/disable/remove and a clear recovery action. Prove one complete journey before expanding screens.
5. **Let other people try it.** A new creator follows public documentation to build and update an add-on; a new user installs and removes it without a terminal. Record where they need help and simplify those steps before the public alpha and library work.

The current snapshot is an engineering preview. The creator loop is tested with text fixtures, not game behaviour; ordinary-user usability and independent creator acceptance are not yet demonstrated. These steps refine the milestones below rather than adding another framework or release track.

## Milestones

| Milestone | Result | Depends on | Exit gate |
| --- | --- | --- | --- |
| M0 Publication and design | Public boundaries, license decision and reviewed contracts | This planning set | Source export rules and architectural decisions agreed; no private build dependencies |
| M1 Package and installation core | Validator, resolver, state store, locking and synthetic adapter | M0 | Deterministic plans, conflict rejection and crash recovery pass using invented data |
| M2 Client adapter and runtime | Standalone client module lifecycle | M1 | Two independent modules coexist, update and uninstall; native and gameplay evidence recorded separately |
| M3 Server adapter | General quest, configuration and supported content modules | M1 | An original server module installs, persists across restart, updates, disables and removes without Studio |
| M4 Combined operations | Coordinated client and server activation | M2 and M3 | Failure at each deployment boundary produces a recoverable state and no falsely successful mixed version |
| M5 Standalone experience and migration | Usable Hub, creator tooling and existing-state handover | M4 | Fresh installation and migration both work; old and new managers cannot write concurrently |
| M6 First public alpha | Reviewed release supporting all three module types | M5 | Independent creator, gameplay, update and recovery trials pass; release contents pass privacy review |
| M7 Library integration | Independent add-on collection and catalog | M6 and creation of the library repository | Each library add-on releases independently and uses the same SDK as external creators |

M2 and M3 can be developed as separate workstreams after M1, but M4 and the first release require both. Milestone acceptance, rather than a calendar date, determines readiness.

## M0 Publication and design

MIT has been selected for the foundation. The reviewed source provenance is in [NOTICE.md](../NOTICE.md), and an exact [public file allowlist](../config/public-files.txt) is checked before publication. Preserve applicable notices and review each future dependency separately.

Agree the package lifecycle, supported resource types, state ownership and adapter interfaces in [Architecture](ARCHITECTURE.md). Record decisions before treating draft interfaces as stable SDK promises. Establish public support/reporting routes and a license inventory for extracted code.

**Deliverables:** approved scope, source export allowlist, license decision, package-contract fixtures and a decision record for the installation coordinator.

**Gate:** a clean checkout contains only reviewed source/docs and synthetic fixtures; local state and personal metadata are absent. No executable is advertised yet.

## M1 Package and installation core

Extract validation, immutable package storage, version/dependency resolution, ownership and journal logic behind neutral interfaces. The engine must not import Studio. Start with a fake filesystem/server adapter so destructive-failure behaviour is testable without game assets.

Use one installation record for a world and its client targets, separate from application settings. Serialize competing operations across processes and state-directory choices. Treat paths as local references, not portable world identities. Define relocation and clone handling explicitly.

Build the CLI entry points for inspect, validate, plan, apply, status and recover before UI polish. These names are proposed operations; actual commands are defined with the implementation.

**Acceptance:** reject malformed/oversized archives, path traversal, symbolic-link escapes, duplicate/case-colliding Windows paths, undeclared files, bad hashes, dependency cycles, incompatible API requirements and ownership collisions. A changed target invalidates an old plan. Terminating an operation after every write boundary must leave enough information to resume or restore safely. Local package validation and installed-module operations work offline.

## M2 Client adapter and runtime

Extract the existing client runtime and pack integration. Prefer an official loader when available; retain a guarded adapter only for explicitly supported builds. Host Python and embedded game Python are separate execution environments and require separate compatibility checks.

Support registration, lifecycle callbacks, windows, shortcuts and bounded preferences. One module owns its own resources; the host coordinates shared hooks. Exception isolation does not promise a security sandbox or protection from blocking/native code.

**Acceptance:** two synthetic modules coexist without replacing each other's hooks; disabling one preserves the other; removing the last module restores the current managed baseline. Test login, logout, map changes, focused text input, display scaling, callback failures and long sessions. Record measured frame-time/memory overhead and set a release budget from those measurements.

## M3 Server adapter

Generalize quest compilation and deployment around module declarations, not a hard-coded package ID. Support namespaced quests, typed configuration and a deliberately small set of content resources with explicit merge rules. Unsupported resource types fail validation.

Deployment must discover the selected local server, validate inputs, stage compilation/build output, stop/restart only when necessary and verify the resulting server. The adapter exposes structured progress and receipts independently of Studio's deployment UI.

Use existing quest-state facilities for the first server example where sufficient. General arbitrary SQL and native engine plug-ins are outside the initial adapter. If a module needs new persistent tables, it waits for a defined migration provider with checksums, backup policy and failure handling; do not silently execute package-supplied shell scripts or unrestricted SQL.

**Acceptance:** a creator installs an original quest/configuration module through the public CLI and Hub without Studio. Quest identity and progress survive update/restart. Compilation failure keeps the previous usable deployment. Duplicate quest/content IDs, external edits and unsupported builds are rejected. Disable/remove handles outstanding effects and preserves persistent data unless a separate purge is requested.

## M4 Combined operations

Use one package with client/server components, one dependency solution and one reviewed operation receipt. Stage and validate both components before changing either. Each adapter declares activation order, downtime and whether a previous version can be restored safely.

Implement a durable step journal and compensating recovery. Files, Docker images and database changes are not one atomic transaction. If an irreversible step prevents automatic restoration, retain backups and report the exact manual recovery required. Never label a partially applied package healthy.

**Acceptance:** inject failure before/after server stop, compilation, migration where supported, pack replacement, restart and health verification. Recovery remains available with the catalog offline. A combined reference module works during connected gameplay, and mismatched required components remain unavailable. Optional client-only interfaces are identified separately from required protocol components.

## M5 Standalone experience and migration

Provide connection setup, Installed, Sources, Review and apply, Activity and Recovery. Share the same engine between UI and CLI. Catalog browsing, importing and downloading do not execute or install code.

Extract world-data readers for generated reference data; retain provenance and distinguish saved configuration from applied/live state. Select one supported host runtime and packaging approach, then prove a fresh machine can install without developer tools. Do not introduce a new web framework merely to relocate the existing interface.

Migrate through an explicit inventory/backup/verification/handover flow described in [Extraction and migration](EXTRACTION_AND_MIGRATION.md). Provide synthetic SDK examples for all three module types. Example modules prove contracts and stay small; gameplay features belong in the future library.

**Acceptance:** a fresh user completes setup using only public documentation. An existing user retains installed packages, settings, preferences and recovery history. A creator builds, updates and removes all three example types using public tools only. The Hub runs with no Studio process or private source checkout.

## M6 First public alpha

Publish a precise supported-build matrix with evidence levels: manifest/fixture, real-pack, native runtime and connected gameplay. A publisher claim and a successful automated import are not gameplay certification.

Complete a disposable official-update rehearsal, an independent creator trial and independent installation/recovery trials. Test busy clients, a stopped Docker service, disk-full/permission failures, interrupted downloads, multiple Hub processes and offline removal. Confirm game launch after disabling all supported extensions; report adapter limitations honestly.

Build from an explicit release allowlist. Audit the archive, commit identities, workflow logs, dependency notices and support report output. Document uninstall, backup retention, state-format compatibility and supported recovery. Publish original code only; users supply their own game installation.

**Gate:** client, server and combined examples all pass their required checks; no open data-loss or concurrent-write defect; no unresolved private dependency. Record remaining limitations in release notes rather than claiming universal Metin2SP compatibility.

## M7 Library integration

After the library repository exists, adopt a collection layout with one manifest, README, changelog and immutable release artifact per add-on. Package IDs remain stable and releases are independent of the Hub version. Index entries point to exact artifacts and include version, digest, compatibility and source identity.

Keep local ZIP import and custom repositories as equal installation paths. Hub can show an optional default library source, but an unavailable or withdrawn listing must not prevent local recovery or uninstall. A withdrawal blocks new use after metadata refresh and retains installed state; it is not a remote kill switch.

Begin with a small set of maintained add-ons after foundation acceptance. Library creation, catalog population and new gameplay features are later tasks, not part of this planning change.

## First implementation queue

| Order | Task | Completion evidence |
| --- | --- | --- |
| 1 | Confirm license, extraction inventory and public release allowlist | Reviewed ownership/notices and synthetic-only public fixtures |
| 2 | Specify manifest evolution and compatibility states | Valid/invalid fixtures including client, server and combined packages |
| 3 | Define installation identity, coordinator, locking and ownership | Two processes targeting the same installation cannot both mutate it |
| 4 | Extract validator/resolver/store with no Studio imports | Clean public checkout passes offline core checks |
| 5 | Implement journaled apply against synthetic adapters | Failure-injection recovery results at every mutation boundary |
| 6 | Implement client and general server adapters | Independent standalone lifecycle evidence for each |
| 7 | Coordinate combined deployment | Partial-failure and connected-gameplay evidence |
| 8 | Add standalone setup/UI, SDK examples and migration | Fresh-user and existing-user acceptance records |

## Decisions still to resolve

| Decision | Recommendation | Resolve by |
| --- | --- | --- |
| Hub license | Decided: MIT, with original Hub attribution preserved | Recorded in LICENSE and NOTICE.md |
| Runtime packaging | Pin one tested host Python/toolchain; ship a self-contained Windows distribution if practical | Before M5 acceptance |
| Manifest evolution | Experimental format 2 implemented; legacy format 1 is rejected until an explicit migration reader is built | Legacy support before M5 migration |
| Game support policy | Publish a finite tested adapter/build matrix and capability requirements | M2 and M3 |
| Persistent table support | Start with quest/config state; add a migration provider only when a reference module needs it | Before accepting such modules |
| Upstream cooperation | Prepare and test fallback contracts now; discuss official hooks after the foundation demonstration | After M4 |

## Deferred work

Remote/VPS management, multi-admin access, arbitrary native plug-ins, general SQL execution, automatic module updates, live boss telemetry, accounts, ratings and marketplace commerce are outside the first release. Mandatory signing and publisher identity infrastructure are separate design decisions; hashes alone are not authenticity guarantees.

If an adapter cannot establish a reliable extension point, report that module capability unavailable. Preserve the client-and-server release requirement rather than silently replacing it with a client-only release.
