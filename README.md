# MT2SP Add-on Hub

A standalone platform under development for managing client, server and combined add-ons for Metin2 Singleplayer.

**Status: experimental foundation.** The offline Python core validates component packages and manages reviewed file transactions in explicitly initialized synthetic sandboxes. It includes installation state, dependency/ownership checks, process locking and interruption recovery. An experimental real client/quest coordinator and a local browser interface are available for one reviewed build. A standalone installer, independent usability acceptance and a stable public SDK remain future milestones.

The first usable release must support all three module types. It will target Windows with a local Metin2SP Docker installation. The game remains responsible for gameplay, its launcher and official updates. Installed modules should work with Hub closed.

## Open the browser preview

With Python 3.11+, install from this checkout once:

```powershell
python -m pip install -e ".[game]"
mt2sp-hub serve
```

Hub opens in your browser. Paste a game folder path, choose an add-on ZIP, review
the changes and confirm. Keep the local launcher running while using the page.
Enable, disable, removal and interruption recovery use the same page and the
same engine as the CLI. See the [browser guide](docs/BROWSER.md). This preview
still needs Python setup; a self-contained Windows installer is future work.

## Create a first example

Use Python 3.11 or newer. The package core uses the standard library. Game pack tests and installation additionally use the optional `[game]` dependency.

```powershell
$env:PYTHONPATH = "src"
python -m mt2sp_hub new scratch/hello --id example.hello --kind combined
python -m mt2sp_hub build scratch/hello scratch/hello-0.1.0.zip
```

Follow [Create your first sandbox add-on](docs/CREATING_ADDONS.md) to edit, install, update and remove it. Choose `client`, `server` or `combined`; the builder handles checksums. These starters contain original text fixtures, not playable game features. The synthetic adapter accepts only its own sandbox marker. Real games use the separate reviewed attachment path.

For engineering details and tests, see the [foundation contracts](docs/FOUNDATION.md). MIT license and source attribution are in [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

For integration development, [`new --profile game`](docs/GAME_CREATORS.md) creates an original client window, a server greeting quest, or both. It uses the same manifest and builder. [Client startup/safe mode](docs/CLIENT_STARTUP.md) and [isolated quest preparation](docs/QUEST_COMPILATION.md) have synthetic tests and local native demonstrations. Use the [experimental game installation guide](docs/GAME_INSTALLATION.md) for attachment, combined install/update/removal and recovery. General build compatibility and public-alpha gameplay acceptance remain separate gates.

## Inspect a game folder

The first game-integration command is read-only:

```powershell
$env:PYTHONPATH = "src"
python -m mt2sp_hub probe "path/to/Metin2 Singleplayer"
```

It accepts the game folder, `Klient`, `Serwer` or the client's `pack` folder. It checks expected files and existing Hub ownership records without running Docker or creating state. Add `--json` for a report that omits local paths. A detected layout is **not** a supported-build check; the probe alone never authorizes installation. See [probe scope and ownership states](docs/FOUNDATION.md#read-only-game-probe).

To also check whether a local Docker server belongs to that folder:

```powershell
python -m mt2sp_hub probe "path/to/Metin2 Singleplayer" --runtime
```

This optional check reports container state and Docker health. It does not start, stop or repair anything. It accepts a local Windows Docker Desktop endpoint and a single standard Compose file; remote endpoints and ambiguous configurations remain unverified. A healthy container is not proof that the intended add-ons are loaded. [Runtime check details](docs/FOUNDATION.md#optional-docker-runtime-check).

Add `--build` to compare actual files with the [reviewed official build reference](docs/GAME_BASELINE.md). It checks client 2.0.135 / server 2.2.134 inputs, including the complete server build tree. Unknown builds and changed inputs are reported without repair. A reference match is only one attachment prerequisite. The [game coordinator](docs/GAME_INSTALLATION.md) additionally checks persistent-world identity, runtime inventory and ownership before installation.

## Project boundaries

| Project | Responsibility |
| --- | --- |
| MT2SP Add-on Hub | Package engine, standalone management interface, client runtime, server adapters, creator tools, schemas and synthetic conformance examples |
| Add-on library | Usable add-ons, their source, documentation, independent releases and catalog entries |
| Studio | Separate authoring and world-management application that consumes the public SDK and exports standard packages |
| Metin2SP | Authoritative game distribution, gameplay engine, launcher and update process |

Hub must build and work without Studio or access to any private repository. The library is a package source, not a prerequisite for operating Hub.

## Planning documents

- [Curated roadmap](docs/ROADMAP.md): milestones, dependencies, acceptance gates and the first implementation tasks.
- [Foundation implementation](docs/FOUNDATION.md): current commands, format 2, state protocol, evidence and limitations.
- [Foundation architecture](docs/ARCHITECTURE.md): ownership, package contracts, installation state and deployment recovery.
- [Minimal game integration](docs/MINIMAL_GAME_INTEGRATION.md): the first client/quest creator contract and the experimental adapter boundary.
- [Extraction and migration](docs/EXTRACTION_AND_MIGRATION.md): reuse existing work without importing private state or breaking installed modules.
- [Public information and privacy](docs/PUBLICATION_AND_PRIVACY.md): publication rules for source, Git history, diagnostics and release artifacts.
- [Metin2SP integration proposal](docs/METIN2SP_INTEGRATION_PROPOSAL.md): developer requests, precise outcomes, fallbacks and a future discussion brief.

Catalog polish and a large add-on collection follow a working foundation. No official Metin2SP partnership or API commitment is implied. Report reproducible defects with invented data through the repository's issues; keep raw installation state and private information out of reports.
