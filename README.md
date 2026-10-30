# MT2SP Add-on Hub

A planned standalone platform for managing client, server and combined add-ons for Metin2 Singleplayer.

**Status: foundation planning.** This repository currently contains the design and delivery plan. It does not yet provide an installable Hub, a supported game integration or a released SDK.

The first usable release must support all three module types. It will target Windows with a local Metin2SP Docker installation. The game remains responsible for gameplay, its launcher and official updates. Installed modules should work with Hub closed.

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
- [Foundation architecture](docs/ARCHITECTURE.md): ownership, package contracts, installation state and deployment recovery.
- [Extraction and migration](docs/EXTRACTION_AND_MIGRATION.md): reuse existing work without importing private state or breaking installed modules.
- [Public information and privacy](docs/PUBLICATION_AND_PRIVACY.md): publication rules for source, Git history, diagnostics and release artifacts.
- [Metin2SP integration proposal](docs/METIN2SP_INTEGRATION_PROPOSAL.md): developer requests, precise outcomes, fallbacks and a future discussion brief.

Implementation starts with the package contract and installation coordinator. Catalog polish and a large add-on collection follow a working foundation. No official Metin2SP partnership or API commitment is implied.
