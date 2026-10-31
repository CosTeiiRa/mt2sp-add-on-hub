# Isolated quest compilation

The experimental [compiler helper](../src/mt2sp_hub/installation/compiler.py) prepares one quest without deploying it. Creators continue to supply the same manifest and quest source. There are no package-supplied commands, Dockerfiles or compiler settings, and ordinary `build` still validates/packages source without invoking Docker.

## Host contract

`compile_quest(quest, profile=..., compiler=..., functions=..., occupied_paths=...)` returns captured artifact bytes and a private preparation receipt. The caller supplies:

- A normalized `QuestSource` from [source preflight](QUEST_STAGING.md), checked against the complete official and selected quest inventory.
- A reviewed `CompilerProfile` containing an exact local image ID and SHA-256 pins for the compiler and function-list bytes. These fields belong to the adapter, never to an add-on manifest.
- Immutable captured compiler/function-list bytes, plus the complete occupied artifact inventory. Known state-file collisions are refused before starting Docker.

The helper verifies those pins before execution. It does not establish whether a profile is supported: deriving expected hashes from whatever files happen to be installed would defeat that review. The experimental coordinator now supplies the [reviewed official build profile](GAME_BASELINE.md). Full dependency/selection validation, authoritative inventories and live deployment verification remain coordinator responsibilities.

Inputs are bounded to 32 MiB for the compiler and the existing 16 MiB file limit for the function list and source. Source normalization and identity are rechecked; CRLF in the function list is normalized after validating its original digest. Only three fixed regular files enter the container through stdin. The host does not mount their physical locations or reread installed inputs during compilation.

## One fixed recipe

The helper accepts only a local Windows Docker Desktop named-pipe endpoint and pins that endpoint for all daemon calls. It requires the exact image already present locally; it never pulls or builds an image. The image must be Linux and declare either no volumes or only the known `/opt/metin2/var` location. Other layouts are refused.

The compiler runs as an unprivileged user, with no network, a read-only image filesystem, dropped capabilities, no new privileges, and limits of one CPU, 256 MiB memory with no additional swap, and 64 processes. `/work` is a 128 MiB temporary memory mount; the image's known data-volume location is overridden with a separate 1 MiB temporary mount. There are no bind mounts, world-data mounts or package-selected mount paths. Docker documents these controls in [container run](https://docs.docker.com/reference/cli/docker/container/run/) and [tmpfs mounts](https://docs.docker.com/engine/storage/tmpfs/).

An in-container 30-second [GNU timeout](https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html) covers input transfer, compilation and output. The host separately bounds the CLI to 45 seconds and limits retained output. Compiler logs stay in bounded temporary storage and are discarded. Friendly source-line diagnostics still need a reviewed compiler error format before a creator-facing compile command is introduced.

The container uses automatic removal. The host also checks cleanup using the operation's exact random name and ownership label, then removes only the matching container ID if necessary. This handles a CLI timeout without assuming that killing the CLI also killed its container. If cleanup cannot be confirmed, no prepared result is returned. A host-process crash still leaves the in-container deadline and auto-removal in place; a lost Docker connection is reported as unconfirmed cleanup rather than success.

## Output and evidence

Only a successful compiler exit can produce a prepared result. The bounded, uncompressed output archive is read without extracting paths to disk. Links, special files, traversal, duplicate/case-colliding entries, unsupported metadata, unused directories and excess output are refused. The same [artifact ownership validator](QUEST_STAGING.md#inspect-each-compiler-output-independently) checks captured bytes and directory-based output. The existing 2,048-file, 16 MiB/file and 64 MiB total artifact limits still apply; wire framing adds a bounded 8 MiB allowance.

The preparation receipt identifies its schema/recipe, package/quest, exact source/compiler/function-list/image inputs, each artifact's digest/size, and the aggregate artifact-inventory digest. Keep it private with staging evidence. It is explicitly a `quest-preparation` receipt, not proof that a deployment is installed or running. The coordinator must retain the captured bytes and recheck their digests before activation.

Public tests use invented bytes and mocked Docker responses, plus real bounded subprocess tests. A local native experiment compiled two original quests into 11 owned artifacts, rejected malformed source, exercised both host and container deadlines, inspected the running fixture's temporary-only mounts, and confirmed all five owned test containers were absent afterward. The experiment pinned local inputs only for that demonstration; it did not certify a supported game build or change/restart a live world. Compiler binaries, function lists, private fingerprints and raw reports remain local.

The [game coordinator](GAME_INSTALLATION.md) now retains these preparation receipts, deploys validated artifacts through the existing stock object directory, and verifies persistent-world/image/inventory identity before committing. No per-add-on quest-list or Dockerfile patch is needed. The [developer proposal](METIN2SP_INTEGRATION_PROPOSAL.md#u04-server-extension-entry-points) describes the upstream contracts that would simplify this guarded fallback.
