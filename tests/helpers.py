import io
import zipfile

from mt2sp_hub.core.packages import Package
from mt2sp_hub.core.validation import digest, encode


def example(ident="example.one", version="1.0.0", files=None, requires=None, conflicts=None):
    files = files if files is not None else {"client/message.txt": b"invented client data", "server/quest.txt": b"invented server data"}
    manifest = {"format_version": 2, "id": ident, "version": version, "name": "Synthetic example",
                "license": "MIT", "requires": requires or {}, "conflicts": conflicts or [], "components": {}}
    members = {}
    for index, (target, raw) in enumerate(files.items()):
        kind, relative = target.split("/", 1)
        component = manifest["components"].setdefault(kind, {"api": ">=1.0.0 <2.0.0", "capabilities": ["fixture.files"], "files": []})
        source = f"file{index}.txt"
        component["files"].append({"source": source, "target": relative, "sha256": digest(raw)})
        members["payload/" + source] = raw
    return manifest, members


def archive(manifest, members, extra=()):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as writer:
        writer.writestr(zipfile.ZipInfo("addon.json", (2026, 1, 1, 0, 0, 0)), encode(manifest))
        for name, raw in list(members.items()) + list(extra):
            writer.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), raw)
    return Package(output.getvalue())


def package(*args, **kwargs):
    return archive(*example(*args, **kwargs))
