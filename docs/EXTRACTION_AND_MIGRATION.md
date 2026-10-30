# Extraction and installation migration

Status: proposed implementation procedure. No source extraction or installation migration is performed by this planning change.

Reuse the maintained integrated add-on implementation, with a fresh public boundary. An earlier standalone prototype can inform the UI and original contracts, but it should not replace newer validation, runtime, repository and recovery work.

## Source extraction

Import a reviewed file allowlist into the new repository's history. Do not mirror an application directory or transplant its Git history. Inspect every candidate file for license notices, private imports, embedded paths, test evidence and generated material before publishing it.

| Existing responsibility | New boundary | Required change |
| --- | --- | --- |
| Manifest/archive validation, SemVer and dependency checks | Package core and SDK | Remove application imports and preserve stricter validation rules |
| Package object store, baselines, ownership and journal | Installation subsystem | Introduce stable installation identity and cross-process coordination |
| Repository providers, download jobs and release selection | Source providers | Keep download/install separation and immutable release digests |
| Client pack adapter and embedded runtime | Client adapter/runtime | Separate host/game interpreter compatibility and current baseline ownership |
| Atlas/reference data builders | World data reader | Replace Studio object access with explicit read-only source interfaces |
| General quest compilation and deployment | Server adapter | Extract staging/build/restart/health operations from editor workflows |
| Special-case gameplay integration | Explicit compatibility adapter or later library module | Remove hard-coded package dispatch from the generic engine; keep exact-build repairs separate |
| Add-on browser interface | Standalone Hub UI | Replace navigation/session coupling with the public local service |
| Creator CLI, manifest/schema docs | SDK | Update all three module templates and eliminate private checkout assumptions |
| Editor drafts, world editors and authoring history | Studio | Keep independent; export packages through the public SDK |

The first extraction checkpoint must build and run synthetic tests with the source application absent. A convenience import from Studio is an extraction defect, including indirect imports for filesystem utilities or catalog readers.

Public fixtures use invented IDs, paths and data. Exact installed-build profiles and evidence require a separate review: distinguish redistributable metadata from game-derived payloads and private traces. Publish no binaries, keys or extracted game assets. Preserve copyright and third-party notices in copied source.

The first Hub release may support a finite list of source-state versions. Unsupported states are reported without mutation; do not infer a migration from loosely similar directory contents.

## Migration inventory

Before handover, capture a local inventory of:

- World/installation identity and every managed client target.
- Package IDs, versions, hashes, desired/actual enablement and settings.
- Installed immutable payloads, file ownership and logical/physical baselines.
- Transaction journals, incomplete operations and backup references.
- Server deployment receipts and pending server/client changes.
- In-game preferences and their existing world/add-on scope.
- Source subscriptions and local selections, excluding credentials from any export.

This inventory and its path mapping remain local. A migration receipt shown publicly contains only reviewed aggregate evidence. Do not upload the inventory as a bug report.

## Handover sequence

1. Identify a supported state version, check hashes and identify unresolved operations. Recover or explicitly resolve these before normal handover.
2. Stop mutation-capable legacy services. Acquire target locks and recheck both live files and source state.
3. Create a verified backup of the managed state. Back up the world separately when the migration includes persistent server data.
4. Copy required immutable objects and records into a staged Hub state store. Preserve source provenance and historical timestamps; do not rewrite old operations as newly verified deployments.
5. Reconcile the recorded owned files with the actual current game installation. A replaced official pack becomes an update review, not a reason to restore an old baseline.
6. Validate all references, journal paths, ownership and package digests. Rebind local paths explicitly when the installation moved.
7. Switch the installation's management registration to Hub and record the handover. A transition Studio build must stop its old add-on writer and use the public coordinator.
8. Reopen Hub, verify installed state, then exercise an innocuous reviewed operation and recovery on a disposable migration fixture before real-world acceptance.

The old state stays archived until the user chooses to remove it. It must not remain a second active writer. Older Studio versions that do not respect the handover are unsupported for concurrent mutation; detect a running instance where possible and explain the required upgrade/closure.

## Preferences and IDs

Keep package IDs stable. A new display name or repository does not justify losing preferences or treating an installed add-on as unrelated. Define aliases only for reviewed identity transitions. A library move changes distribution location, not ownership of local settings.

World relocation preserves identity when explicitly confirmed; copying a world creates a new identity unless the user chooses a documented restore flow. Do not derive identity solely from a username, absolute path, server version or executable hash.

## Rollback and recovery

Before ownership handover, discard the staged destination only when it is verified to be Hub-owned and the source remains intact. After handover, recovery uses the Hub journal and retained source archive. Downgrading the manager is supported only for declared state-schema versions; never point an old executable at a newer state store and hope it understands it.

Reverting migration must reconcile any operations performed after handover. Restoring yesterday's state database over today's modified game files is not a safe rollback. Keep receipts and report external drift instead of forcing restoration.

## Acceptance cases

Test a clean existing installation, disabled packages, multiple client targets, offline sources, pending recovery, stale baselines after a game update, relocated paths, copied worlds, corrupt/missing objects, low disk space and an attempted concurrent legacy write. Verify settings and progress retention, exact ownership records and the ability to recover with Studio absent.

After the Hub release passes migration acceptance, Studio can consume a pinned public SDK release. Future library packages must be buildable by creators with no Studio access. The source application's repository visibility is an independent owner-managed action.
