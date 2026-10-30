# Source provenance

The platform uses the MIT license in [LICENSE](LICENSE).

`src/mt2sp_hub/core/versions.py` is reused from the original Metin2 Add-on Hub implementation. JSON/path validation and bounded archive handling are adapted from that implementation, with revised component contracts and stricter portable paths. The original copyright notice, **Copyright (c) 2026 Metin2 Add-on Hub contributors**, is preserved in the license.

The installation coordinator, sandbox transaction engine, CLI and synthetic tests in this increment are new platform code. No source-application Git history, installed game material, executable profiles or personal state was imported. Runtime dependencies are limited to the Python standard library. Setuptools is a build-time dependency when installing the Python project.

Future extractions must add their applicable notices here before publication.

The standalone client lifecycle runtime adapts the loading, callback and window-lifecycle concepts of the original MIT-licensed Metin2 Studio extension host. Its **Copyright (c) 2026 Metin2 Studio contributors** notice is retained in [LICENSE](LICENSE). This smaller implementation removes application imports, atlas services, preferences, physical source lookup and game-class patching. The generated greeting window and quest are original Hub examples; they contain no game distribution source or assets.
