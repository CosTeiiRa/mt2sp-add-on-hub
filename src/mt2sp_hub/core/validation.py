"""Bounded JSON and portable paths, adapted from the original MIT Hub."""
from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from pathlib import Path

from ..errors import HubError, require

MAX_JSON = 256 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 2048
ID = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+")
SHA = re.compile(r"[0-9a-f]{64}")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def parse_json(raw: bytes, limit=MAX_JSON):
    require(len(raw) <= limit, "json_limit", "JSON exceeds its size limit.")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "json_duplicate", "Duplicate JSON key.")
            result[key] = value
        return result

    def constant(_):
        raise HubError("json_number", "JSON numbers must be finite.")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
        pending = [(value, 0)]
        while pending:
            node, depth = pending.pop()
            require(depth <= 32, "json_depth", "JSON nesting exceeds its limit.")
            if isinstance(node, dict):
                pending.extend((v, depth + 1) for v in node.values())
                pending.extend((k, depth + 1) for k in node)
            elif isinstance(node, list):
                pending.extend((v, depth + 1) for v in node)
            elif isinstance(node, str):
                node.encode("utf-8")
            elif isinstance(node, float):
                require(math.isfinite(node), "json_number", "JSON numbers must be finite.")
        return value
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise HubError("json_invalid", "Invalid UTF-8 JSON.") from exc


def identifier(value):
    require(isinstance(value, str) and len(value) <= 128 and ID.fullmatch(value),
            "package_id", "Invalid namespaced package ID.")
    return value


def logical_path(value):
    require(isinstance(value, str) and 0 < len(value) <= 220
            and re.fullmatch(r"[A-Za-z0-9_./-]+", value),
            "path_invalid", "Paths must use portable relative ASCII names.")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    parts = value.split("/")
    require(all(p not in ("", ".", "..") and not p.endswith(".")
                and p.split(".")[0].upper() not in reserved for p in parts),
            "path_invalid", "Unsafe or reserved path segment.")
    return value


def path_set(paths):
    """Reject duplicates, directory casing differences and ancestor files."""
    exact, prefixes = set(), {}
    for path in paths:
        logical_path(path)
        require(path.casefold() not in exact, "path_collision", "Duplicate or case-colliding path.")
        exact.add(path.casefold())
        parts = path.split("/")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            folded = prefix.casefold()
            require(folded not in prefixes or prefixes[folded] == prefix,
                    "path_collision", "Inconsistent directory casing.")
            prefixes[folded] = prefix
    for path in exact:
        require(not any("/".join(path.split("/")[:i]) in exact
                        for i in range(1, len(path.split("/")))),
                "path_collision", "A file cannot also be a directory.")


def confined(root: Path, relative: str) -> Path:
    """Check every segment, including Windows junctions/reparse points."""
    logical_path(relative)
    current = root
    for part in ("", *relative.split("/")):
        if part:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0) & 0x400,
                "path_link", "Links and reparse points are unsupported.")
        if current != root / relative:
            require(stat.S_ISDIR(info.st_mode), "path_collision", "A parent path is not a directory.")
    return current


def read_bounded(path: Path, limit: int) -> bytes:
    require(stat.S_ISREG(path.stat().st_mode), "file_type", "A regular file is required.")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "file_limit", "File exceeds its size limit.")
    return raw
