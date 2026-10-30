# Experimental package and recovery foundation

This is the M1 package and synthetic installation foundation. It provides an offline package engine and an explicitly initialized synthetic filesystem target. Client/server labels identify separate fixture directories; no game code, quest compilation, Docker deployment or native client runtime is invoked. The [minimal real-game integration](MINIMAL_GAME_INTEGRATION.md) is defined for the next implementation stage.

## Implemented scope

- Component format 2 for client, server and combined packages, with strict JSON/ZIP validation and declared SHA-256 payloads.
- Semantic version requirements, deterministic dependency ordering, explicit conflicts, adapter API/capability checks and exclusive file ownership.
- Client/server/combined starter creation, automatic build checksums, deterministic source packing and inspect/validate commands that never execute payloads.
- Installation identity, generation checks, immutable cached package/backup objects, release history and per-target process locking.
- Reviewed install/update, enable/disable and remove plans. Installed operations use cached objects and work with source archives removed.
- Journal-before-mutation apply, state commit, receipts and recovery. External changes block restoration.
- Synthetic process-crash tests and a public-source allowlist/privacy audit.

## Sandbox walkthrough

Run in a checkout with Python 3.11 or newer. PowerShell examples use ignored `scratch` directories and invent all content. Use fresh paths for each new walkthrough.

```powershell
$env:PYTHONPATH = "src"
python -m mt2sp_hub new scratch/example --id example.sandbox --kind combined
python -m mt2sp_hub build scratch/example scratch/example.m2addon.zip
python -m mt2sp_hub inspect scratch/example.m2addon.zip
python -m mt2sp_hub sandbox-init scratch/sandbox
python -m mt2sp_hub plan --root scratch/sandbox --add scratch/example.m2addon.zip
```

The last command prints a `plan` ID and the relative files/digests it proposes to change. It writes only the private cache and plan records, leaving the synthetic client/server target files unchanged. Replace `PLAN_ID_FROM_REVIEW` below with the returned ID after reviewing it.

```powershell
python -m mt2sp_hub apply --root scratch/sandbox --plan PLAN_ID_FROM_REVIEW --yes
python -m mt2sp_hub status --root scratch/sandbox
python -m mt2sp_hub plan --root scratch/sandbox --disable example.sandbox
```

Apply the new plan ID to disable the example. `--enable example.sandbox` and `--remove example.sandbox` use the same plan/apply flow. Updating uses `--add` with a new version of the same ID. Each ID may have one action in a plan; updating a disabled package preserves its disabled state.

To inspect and recover an interrupted operation:

```powershell
python -m mt2sp_hub status --root scratch/sandbox
python -m mt2sp_hub recover --root scratch/sandbox --yes
```

Do not remove journals or edit their checksums to dismiss a recovery conflict. Preserve the sandbox/control directory for local inspection. A recovered plan is consumed; make a fresh plan before retrying.

The `new` command also accepts `--kind client` and `--kind server`. Its text payloads are original conformance examples, not usable game add-ons. It replaces the initial `tools/make_example.py` helper. Follow the [creator guide](CREATING_ADDONS.md) for editing and updates. The future library remains a separate project.

## Package format 2

The archive has a root `addon.json` and exactly its declared files under `payload/`. Unknown fields and undeclared source/archive files are rejected. The editor schemas distinguish [author source](../sdk/schemas/addon-source-v2.schema.json) and [distributed archives](../sdk/schemas/addon-v2.schema.json); the Python validator additionally checks paths, hashes, archive structure and cross-field constraints.

Author source uses the same fields, but may omit each file's `sha256`. `build` computes every checksum from current payload bytes in memory, leaving source unchanged. Existing well-formed source hashes are refreshed; malformed hash fields remain errors. The lower-level `pack` retains strict existing-hash verification. Archives always require and verify hashes; installation never refreshes them. Both commands build deterministic archives without executing payload code and refuse outputs inside the source folder or existing output files.

| Field | Contract |
| --- | --- |
| `format_version` | Integer `2`; legacy format 1 is not silently reinterpreted |
| `id` | Lowercase namespaced ID, up to 128 characters |
| `version` | SemVer 2, including prerelease/build identifiers |
| `name`, `license` | Nonempty display/license text, up to 200 characters |
| `requires` | Map of package ID to a version requirement |
| `conflicts` | Unique package IDs that cannot be active together |
| `components` | `client`, `server` or both; each declares `api`, `capabilities` and `files` |
| Component file | `source` under payload, relative `target` under that component, and lowercase `sha256` |

Version requirements are whitespace-separated exact, `=`, `>`, `>=`, `<` or `<=` SemVer comparators, up to eight. Caret, tilde, wildcard and OR syntax are rejected. Comparisons follow SemVer precedence, including prereleases; there is no implicit npm-style prerelease exclusion. Build metadata does not change precedence. Package release identity still uses the exact ID/version string plus archive digest.

The synthetic adapter reports API `1.0.0` for both components and only capability `fixture.files`. These are fixture contracts, not Metin2SP API versions. Any missing required capability/API blocks planning. Selected versions are explicit: the resolver validates the requested graph and never downloads or chooses upgrades automatically. Disabled packages do not satisfy active dependencies.

Paths use portable relative ASCII names. Traversal, absolute paths, alternate data streams, device names, symlinks/junctions, case collisions and file/parent collisions are rejected. File targets are relative to the synthetic `client` or `server` directory. A real adapter will restrict its own resource types and namespaces before game writes are introduced.

Limits: 256 KiB manifest, 16 MiB per payload file, 64 MiB payload per package, 66 MiB archive, 2,048 payload files, 128 installed packages, 128 MiB selected archive bytes and 64 MiB/2,048 active output files. Stored or Deflate ZIPs are accepted; encrypted/special-entry archives are rejected. Packing uses stored entries with fixed ordering, timestamps and modes for reproducible bytes.

Settings schemas, semantic quest/content-ID ownership, persistent-data migrations, source subscriptions and format-1 conversion are later increments. Filesystem checks and hashes are not a sandbox or publisher-authenticity mechanism.

## Installation state and locking

`sandbox-init` accepts only an empty directory and creates `.mt2sp-hub`. A random installation ID is independent of the local path. A separate canonical-root binding detects copied/relocated sandbox state and refuses it; explicit relocation/clone support remains future work.

State is deliberately colocated with the sandbox in this increment. There is no alternate state-directory parameter that could create a second active owner. All managers resolving to the same target use the same OS file lock. Windows uses nonblocking byte-range locking; POSIX uses `flock`. The lock releases when the owning process exits. The lock file is never deleted as a stale-PID repair.

The control directory contains:

| Record | Purpose |
| --- | --- |
| `identity.json` | Synthetic kind, state format, installation ID and local root binding |
| `state.json` | Current generation, selected packages/enablement and managed file ownership/baselines |
| `objects/` | SHA-addressed archives, desired bytes and original byte backups |
| `releases/` | Permanent ID/version-to-artifact binding, retained after uninstall |
| `plans/` | Checksummed before/after generations and target fingerprints |
| `active.json` | Durable in-flight operation journal |
| `receipts/` | Applied or rolled-back outcome and the completed plan |

These records are private local data. An installation inspection returns package versions, enablement, generation and recovery status; raw absolute paths and OS exception details are omitted from CLI errors. Plans intentionally display relative target paths and content digests for local review.

The first managed overwrite captures an existing synthetic file as its baseline. Updates retain that baseline; disable/remove restores it or removes a newly created file. Unmanaged files are preserved. Empty parent directories may remain. This adapter manages file bytes, not ACLs, timestamps or hard-link topology.

## Commit and recovery protocol

Apply verifies the plan checksum, identity, state generation, backup objects and current file fingerprints while holding the target lock. It persists the full before/after journal before the first target write. Each file replacement is staged beside its destination, checked for a complete write, flushed and replaced; successful writes are verified. Only after all outputs match does the engine atomically replace `state.json`, then write a receipt and clear the active journal.

| Interrupted state | Recovery action |
| --- | --- |
| State still equals the before generation; each file matches its before or after digest | Restore all before bytes, verify them and write a rolled-back receipt |
| State equals the after generation and every output matches | Retain committed outputs, finish the receipt and clear the journal |
| State, backup objects or target files disagree with the recorded possibilities | Stop and retain all evidence; do not overwrite the discrepancy |

Recovery itself is restartable. A crash after a restoration step leaves a mixture of valid before/after bytes that the next recovery can recognize. Every new mutation/plan is blocked while a journal remains active. Reusing a completed/recovered plan is rejected so its receipt is not overwritten.

Short writes and failures during temporary-file writing, flush or file synchronization abort before replacement, preserving the previous destination. Cleanup removes only a temporary file created by that attempt; a failed exclusive creation cannot delete a pre-existing file. A directory synchronization error after replacement may leave the new complete bytes visible. Recovery uses the persisted state generation and file hashes to decide the outcome rather than assuming every reported error means nothing changed.

Abrupt process exit can leave `.hub-*.tmp` files beside records or targets. They are never treated as committed state or promoted during recovery. Recovery does not sweep files just because their names match that pattern. They may consume disk space until inspected locally; preserve them with other evidence when investigating an interruption. Automatic cleanup and recovery from hardware power loss are not claimed.

The tests exercise process interruption, not a power-loss/storage-fault certification. File data is flushed, and POSIX directory entries are synchronized. Windows hardware/storage durability and races with non-cooperating writers need further platform validation. The code checks for drift at boundaries but cannot exclude another tool that ignores its lock. The official updater cooperation request remains relevant.

## Validation and next increment

Run `python -m unittest discover -s tests -v` with `PYTHONPATH=src`. Tests generate their own temporary data, including archive attacks, dependency conflicts, offline lifecycle operations, baseline restoration, state/backup corruption, competing processes and abrupt `os._exit` at journal/file/state/receipt boundaries. Symlink tests skip only when the host refuses link creation; a real Windows junction test and Linux CI cover the respective link paths.

Storage tests additionally inject partial/short writes, flush errors, file-sync errors and directory-sync errors at journal, client, server, state and receipt writes. Subprocesses exit midway through a temporary write, after file synchronization and immediately after replacement at those same destinations. Separate cases cover interrupted rollback, failed cache import, removal and journal cleanup. After reopening, each case must preserve complete before/after bytes and reach the correct installed or rolled-back state. These faults live in test helpers; production does not need an additional recovery framework.

Run `python tools/check_public_tree.py` after staging the intended files. It compares the Git index to [public-files.txt](../config/public-files.txt), checks selected privacy patterns and validates relative document links. Local review can add `--private-term` and `--base` to inspect private terms and outgoing commit metadata. It is a review aid, not a guarantee that every secret or personal identifier is detected.

## Package-limit evidence

All limits apply together; reaching one does not waive another. For example, long filenames can exhaust the 256 KiB manifest budget before reaching 2,048 files. Installed-but-disabled packages still count toward the package-count and selected-archive budgets. Historical backups, old releases and receipts are retained separately; the 128 MiB selected-archive limit is not a lifetime disk-cache quota.

| Boundary | Evidence |
| --- | --- |
| 256 KiB manifest | Exact boundary parses; one extra byte is rejected |
| 16 MiB file, 64 MiB expanded package, 66 MiB archive | Exact/one-over comparisons with small byte budgets in CI; real full-size payloads in the measurement profiles |
| 2,048 payload files | Actual single-package archive accepted; one extra file rejected; count also enforced across client/server components |
| 2,048 active files and 64 MiB active bytes | Count enforced across packages; exact/one-over aggregate-byte tests; real 64 MiB/2,048-file measurements |
| 128 installed packages | Actual installation with 128 combined packages and 2,048 files; package 129 refused even after disabling all existing packages; offline removal succeeds |
| Dependency depth at package limit | A 128-package chain resolves in dependency order; package 129 refused |
| 128 MiB selected archives | Exact/one-over budget checks include disabled packages; rejection leaves installed state unchanged; near-limit real archive selection completes install/disable/remove |

Run `python tools/measure_foundation.py --profile all` with `PYTHONPATH=src` to repeat the full-size measurements. Individual profiles are `large` (the default), `files`, `packages` and `cached`. Each creates original disposable data, completes installation/removal and emits one JSON line after cleanup. Output excludes local paths and machine identity. Repeating all profiles can take several minutes because each file is durably written and verified.

One Windows/Python 3.13.7 run on 30 October 2026 observed the following. Timings are sample observations, not promises. Peak values are traced Python allocations, not total process memory or a proof of a universal worst case. Tracing includes retained package objects from earlier measured stages, but excludes fixture generation and interpreter startup.

| Profile | Packages / files | Payload | Build / apply install / apply remove seconds | Largest stage peak MiB | Largest JSON record bytes |
| --- | --- | --- | --- | ---: | ---: |
| `large` | 1 / 4 | 64 MiB active | 0.199 / 0.323 / 0.190 | 192.09 | 1,598 |
| `files` | 1 / 2,048 | 64 MiB active | 17.275 / 67.290 / 31.399 | 197.82 | 498,082 |
| `packages` | 128 / 2,048 | 64 MiB active | 25.558 / 82.641 / 31.291 | 197.55 | 518,998 |
| `cached` | 2 / 8 total | One near-64 MiB package active; the other disabled | 0.423 / 0.314 / 0.188 | 274.02 | 1,859 |

The cached profile selects 134,203,878 archive bytes, below the 134,217,728-byte ceiling. Enabling both packages exceeds the active-payload limit and is rejected. Its installation timing refers to the second package; JSON output also records the first install and disable stages. All measured records fit within the independent 8 MiB record limit.

The high-file-count measurements show why installation needs progress and a clear recovery state. Keep the current synchronous writer and conservative limits for now; these results do not justify a parallel writer, background service or a larger limit. Backup/history retention and a disk-space preflight remain part of real deployment work. These tests model software failures and controlled process exits, not hardware power loss.

M1's package/synthetic-installation acceptance checks are now covered. The next work is the [defined real adapter and ownership boundary](MINIMAL_GAME_INTEGRATION.md): implement attachment/probing, stage an original client module and quest, and add deployment recovery evidence. The first usable Hub release still requires both real components and connected gameplay acceptance; this development snapshot is not that release.

## Implementation references

The locking, atomic replacement and archive checks use the Python standard library contracts: [Windows byte-range locks](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking), [file replacement](https://docs.python.org/3/library/os.html#os.replace), and [ZIP extraction pitfalls](https://docs.python.org/3/library/zipfile.html#decompression-pitfalls).
