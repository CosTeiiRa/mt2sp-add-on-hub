"""Component packages; validation never imports or executes payload code."""
from __future__ import annotations

import io
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from ..errors import HubError, require
from .validation import (MAX_FILE, MAX_FILES, MAX_JSON, MAX_TOTAL, SHA, confined,
                         digest, encode, identifier, logical_path, parse_json,
                         path_set, read_bounded)
from .versions import Version, satisfies

MAX_ARCHIVE = MAX_TOTAL + 2 * 1024 * 1024


def version_range(value):
    # Parse every comparator even when an earlier comparator does not match.
    require(isinstance(value, str) and 0 < len(value) <= 256
            and 0 < len(value.split()) <= 8, "version_range", "Invalid version requirement.")
    try:
        for token in value.split():
            satisfies("1.0.0", token)
    except ValueError as exc:
        raise HubError("version_range", "Unsupported version requirement.") from exc
    return value


def fields(value, required):
    require(isinstance(value, dict) and set(value) == set(required),
            "manifest_fields", "Missing or unsupported manifest fields.")


def validate_manifest(value, *, source=False):
    """Source manifests may omit hashes; distributed packages must include them."""
    fields(value, ("format_version", "id", "version", "name", "license", "requires",
                   "conflicts", "components"))
    require(type(value["format_version"]) is int and value["format_version"] == 2,
            "manifest_version", "Only the experimental component format 2 is supported.")
    identifier(value["id"])
    try:
        Version(value["version"])
    except ValueError as exc:
        raise HubError("package_version", "Invalid package semantic version.") from exc
    for key in ("name", "license"):
        text = value[key]
        require(isinstance(text, str) and 0 < len(text) <= 200
                and all(ord(c) >= 32 for c in text), "manifest_text", "Invalid package metadata.")
    require(isinstance(value["requires"], dict) and len(value["requires"]) <= 64,
            "dependency", "Invalid dependency map.")
    for dep, constraint in value["requires"].items():
        identifier(dep)
        version_range(constraint)
        require(dep != value["id"], "dependency", "A package cannot depend on itself.")
    conflicts = value["conflicts"]
    require(isinstance(conflicts, list) and len(conflicts) <= 64,
            "conflict", "Invalid conflict list.")
    for ident in conflicts:
        identifier(ident)
    require(len(set(conflicts)) == len(conflicts) and value["id"] not in conflicts,
            "conflict", "Duplicate or self conflict.")
    components = value["components"]
    require(isinstance(components, dict) and bool(components)
            and set(components) <= {"client", "server"},
            "component", "Declare client, server or both components.")
    sources, targets = [], []
    for kind, component in components.items():
        fields(component, ("api", "capabilities", "files"))
        version_range(component["api"])
        caps = component["capabilities"]
        require(isinstance(caps, list) and len(caps) <= 32,
                "capability", "Invalid capability list.")
        for cap in caps:
            identifier(cap)
        require(len(caps) == len(set(caps)), "capability", "Duplicate capability.")
        files = component["files"]
        require(isinstance(files, list) and 0 < len(files) <= MAX_FILES,
                "manifest_files", "Components require bounded file lists.")
        for row in files:
            keys = ("source", "target", "sha256")
            if source and isinstance(row, dict) and "sha256" not in row:
                keys = ("source", "target")
            fields(row, keys)
            sources.append("payload/" + logical_path(row["source"]))
            targets.append(kind + "/" + logical_path(row["target"]))
            if "sha256" in row:
                require(isinstance(row["sha256"], str) and SHA.fullmatch(row["sha256"]),
                        "file_hash", "Invalid payload digest.")
    require(len(sources) <= MAX_FILES, "manifest_files", "Too many payload files.")
    path_set(sources)
    path_set(targets)
    return value


@dataclass(frozen=True)
class Package:
    raw: bytes

    @property
    def sha256(self):
        return digest(self.raw)

    def unpack(self):
        return unpack(self.raw)

    @property
    def manifest(self):
        return self.unpack()[0]

    @classmethod
    def load(cls, path):
        raw = read_bounded(Path(path), MAX_ARCHIVE)
        unpack(raw)
        return cls(raw)


def unpack(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_ARCHIVE,
            "archive_limit", "Archive exceeds its size limit.")
    files, directories, total = {}, [], 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) <= MAX_FILES * 3 + 1, "archive_limit", "Too many archive entries.")
            names = []
            for entry in entries:
                require(entry.orig_filename == entry.filename, "archive_path", "Altered archive path.")
                name = entry.filename[:-1] if entry.is_dir() else entry.filename
                logical_path(name)
                names.append(name)
                mode = stat.S_IFMT(entry.external_attr >> 16)
                require(mode in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG),
                        "archive_link", "Links and special archive entries are unsupported.")
                require(not entry.flag_bits & 1 and entry.compress_type in
                        (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                        "archive_encoding", "Unsupported archive encryption or compression.")
                if entry.is_dir():
                    directories.append(name)
                    continue
                limit = MAX_JSON if name == "addon.json" else MAX_FILE
                total += entry.file_size if name != "addon.json" else 0
                require(entry.file_size <= limit and total <= MAX_TOTAL,
                        "archive_limit", "Expanded archive exceeds its size limit.")
                with archive.open(entry) as stream:
                    content = stream.read(limit + 1)
                require(len(content) == entry.file_size and len(content) <= limit,
                        "archive_limit", "Invalid expanded member size.")
                files[name] = content
            # Directories may be parents, but never duplicate/case-collide.
            require(len({n.casefold() for n in names}) == len(names),
                    "path_collision", "Duplicate or case-colliding archive entry.")
            path_set(files)
            for directory in directories:
                require(directory.casefold() not in {n.casefold() for n in files},
                        "path_collision", "File and directory collide.")
                require(any(n.startswith(directory + "/") for n in files),
                        "archive_members", "Undeclared or inconsistently cased directory.")
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise HubError("archive_invalid", "Invalid package archive.") from exc
    require("addon.json" in files, "manifest_missing", "Archive requires a root addon.json.")
    manifest = validate_manifest(parse_json(files["addon.json"]))
    outputs, expected = {}, {"addon.json"}
    for kind, component in manifest["components"].items():
        for row in component["files"]:
            source = "payload/" + row["source"]
            expected.add(source)
            require(source in files and digest(files[source]) == row["sha256"],
                    "payload_integrity", "Missing or mismatched payload bytes.")
            outputs[kind + "/" + row["target"]] = files[source]
    require(set(files) == expected, "archive_members", "Archive contains undeclared files.")
    return manifest, outputs


def pack(directory: Path) -> Package:
    """Pack a source with existing hashes, verifying every declared digest."""
    return _pack(directory, refresh_hashes=False)


def build(directory: Path) -> Package:
    """Compute hashes from author-owned source without changing its manifest."""
    return _pack(directory, refresh_hashes=True)


def _pack(directory: Path, *, refresh_hashes: bool) -> Package:
    directory = Path(directory).resolve()
    manifest = validate_manifest(parse_json(read_bounded(confined(directory, "addon.json"), MAX_JSON)),
                                 source=refresh_hashes)
    members = {}
    total = 0
    for component in manifest["components"].values():
        for row in component["files"]:
            source = "payload/" + row["source"]
            members[source] = read_bounded(confined(directory, source), MAX_FILE)
            total += len(members[source])
            require(total <= MAX_TOTAL, "archive_limit", "Source payload exceeds its size limit.")
            if refresh_hashes:
                row["sha256"] = digest(members[source])
    members["addon.json"] = encode(manifest)
    # Refuse undeclared input files rather than silently excluding secrets.
    actual = set()
    for path in directory.rglob("*"):
        relative = path.relative_to(directory).as_posix()
        confined(directory, relative)
        if path.is_file():
            actual.add(relative)
    require(actual == set(members), "archive_members", "Source contains undeclared files.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    raw = buffer.getvalue()
    unpack(raw)
    return Package(raw)
