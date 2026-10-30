# MT2SP Add-on Hub

A standalone platform under development for managing client, server and combined add-ons for Metin2 Singleplayer.

**Status: experimental foundation.** The offline Python core validates component packages and manages reviewed file transactions in explicitly initialized synthetic sandboxes. It includes installation state, dependency/ownership checks, process locking and interruption recovery. Real game adapters, the management UI and a stable SDK remain future milestones.

The first usable release must support all three module types. It will target Windows with a local Metin2SP Docker installation. The game remains responsible for gameplay, its launcher and official updates. Installed modules should work with Hub closed.

## Create a first example

Use Python 3.11 or newer. The core and tests need no third-party runtime packages.

```powershell
$env:PYTHONPATH = "src"
python -m mt2sp_hub new scratch/hello --id example.hello --kind combined
python -m mt2sp_hub build scratch/hello scratch/hello-0.1.0.zip
```

Follow [Create your first sandbox add-on](docs/CREATING_ADDONS.md) to edit, install, update and remove it. Choose `client`, `server` or `combined`; the builder handles checksums. These starters contain original text fixtures, not playable game features. The current adapter accepts only its own synthetic sandbox marker; it has no game installation path.

For engineering details and tests, see the [foundation contracts](docs/FOUNDATION.md). MIT license and source attribution are in [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

## Project boundaries

| Project | Responsibility |
| --- | --- |
| MT2SP Add-on Hub | Package engine, standalone management interface, client runtime, server adapters, creator tools, schemas and synthetic conformance examples |
| Future `mt2sp-add-on-library` | Usable add-ons, their source, documentation, independent releases and catalog entries |
| Studio | Separate authoring and world-management application that consumes the public SDK and exports standard packages |
| Metin2SP | Authoritative game distribution, gameplay engine, launcher and update process |

Hub must build and work without Studio or access to any private repository. The future library is a package source, not a prerequisite for operating Hub.

## Planning documents

- [Curated roadmap](docs/ROADMAP.md): milestones, dependencies, acceptance gates and the first implementation tasks.
- [Foundation implementation](docs/FOUNDATION.md): current commands, format 2, state protocol, evidence and limitations.
- [Foundation architecture](docs/ARCHITECTURE.md): ownership, package contracts, installation state and deployment recovery.
- [Extraction and migration](docs/EXTRACTION_AND_MIGRATION.md): reuse existing work without importing private state or breaking installed modules.
- [Public information and privacy](docs/PUBLICATION_AND_PRIVACY.md): publication rules for source, Git history, diagnostics and release artifacts.
- [Metin2SP integration proposal](docs/METIN2SP_INTEGRATION_PROPOSAL.md): developer requests, precise outcomes, fallbacks and a future discussion brief.

Catalog polish and a large add-on collection follow a working foundation. No official Metin2SP partnership or API commitment is implied. Report reproducible defects with invented data through the repository's issues; keep raw installation state and private information out of reports.
