"""Small, original sandbox starters for package authors; no game integration."""
import json
from pathlib import Path

from .core.packages import validate_manifest
from .errors import HubError, require


def create(directory: Path, ident: str, kind: str):
    require(kind in ("client", "server", "combined"), "component",
            "Choose client, server or combined.")
    kinds = ("client", "server") if kind == "combined" else (kind,)
    manifest = {"format_version": 2, "id": ident, "version": "0.1.0",
                "name": "My sandbox add-on", "license": "MIT",
                "requires": {}, "conflicts": [], "components": {}}
    for component in kinds:
        manifest["components"][component] = {
            "api": ">=1.0.0 <2.0.0", "capabilities": ["fixture.files"],
            "files": [{"source": component + ".txt", "target": ident + "/message.txt"}]}
    validate_manifest(manifest, source=True)
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HubError("project_exists", "Starter folder already exists. Choose a new folder.") from exc
    (directory / "payload").mkdir()
    for component in kinds:
        (directory / "payload" / (component + ".txt")).write_bytes(
            ("Original synthetic " + component + " content.\n").encode("ascii"))
    (directory / "addon.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
