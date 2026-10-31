"""Validate an explicitly selected graph; never download or silently upgrade."""
from ..errors import require
from .validation import MAX_FILES, MAX_PACKAGES, MAX_TOTAL, path_set
from .versions import satisfies


def resolve(packages, apis=None, capabilities=None):
    apis = {"client": "1.0.0", "server": "1.0.0"} if apis is None else apis
    capabilities = capabilities if capabilities is not None else {"fixture.files"}
    selected, outputs, owners = {}, {}, {}
    total = 0
    for package in packages:
        require(len(selected) < MAX_PACKAGES, "package_limit", "Too many selected packages.")
        manifest, files = package.unpack()
        ident = manifest["id"]
        require(ident not in selected, "duplicate_package", "Duplicate selected package ID.")
        selected[ident] = manifest
        for kind, component in manifest["components"].items():
            require(kind in apis and satisfies(apis[kind], component["api"]),
                    "api_incompatible", "Required adapter API is unavailable.")
            require(set(component["capabilities"]) <= capabilities,
                    "capability_missing", "Required adapter capability is unavailable.")
        for path, raw in files.items():
            require(path not in owners, "ownership_conflict", "Two packages claim the same resource.")
            owners[path], outputs[path] = ident, raw
            total += len(raw)
            require(total <= MAX_TOTAL and len(outputs) <= MAX_FILES,
                    "selection_limit", "Selected outputs exceed installation limits.")
    path_set(outputs)
    for ident, manifest in selected.items():
        require(not set(manifest["conflicts"]) & selected.keys(),
                "package_conflict", "Selected packages declare a conflict.")
        for dep, constraint in manifest["requires"].items():
            require(dep in selected and satisfies(selected[dep]["version"], constraint),
                    "dependency_missing", "A required package/version is unavailable or disabled.")
    ordered, visiting, visited = [], set(), set()

    def visit(ident):
        require(ident not in visiting, "dependency_cycle", "Package dependencies contain a cycle.")
        if ident in visited:
            return
        visiting.add(ident)
        for dep in sorted(selected[ident]["requires"]):
            visit(dep)
        visiting.remove(ident)
        visited.add(ident)
        ordered.append(ident)

    for ident in sorted(selected):
        visit(ident)
    return ordered, outputs, owners


def selection_changes(before, after):
    """Describe the actual prepared selection for CLI and interface review."""
    return [{'id': ident, 'before': before.get(ident), 'after': after.get(ident)}
            for ident in sorted(set(before) | set(after)) if before.get(ident) != after.get(ident)]
