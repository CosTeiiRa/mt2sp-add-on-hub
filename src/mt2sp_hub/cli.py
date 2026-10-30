"""Offline CLI for the experimental package and sandbox foundation."""
import argparse
import json
from pathlib import Path

from .core.packages import Package, pack
from .core.validation import MAX_TOTAL
from .errors import HubError, require
from .installation.manager import Manager, initialize


def parser():
    root = argparse.ArgumentParser(prog="mt2sp-hub", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("pack", help="Validate a source directory and create a deterministic ZIP")
    build.add_argument("source", type=Path)
    build.add_argument("output", type=Path)
    for name in ("validate", "inspect"):
        command = commands.add_parser(name, help="Read a package without executing its payload")
        command.add_argument("archive", type=Path)
    init = commands.add_parser("sandbox-init", help="Initialize an empty, disposable synthetic target")
    init.add_argument("root", type=Path)
    for name in ("status", "plan", "apply", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        if name == "plan":
            command.add_argument("--add", type=Path, action="append", default=[])
            for action in ("remove", "enable", "disable"):
                command.add_argument("--" + action, action="append", default=[])
        if name == "apply":
            command.add_argument("--plan", required=True)
        if name in ("apply", "recover"):
            command.add_argument("--yes", action="store_true", help="Confirm the reviewed operation")
    return root


def run(args):
    if args.command == "pack":
        package = pack(args.source)
        with args.output.open("xb") as stream:
            stream.write(package.raw)
        return {"sha256": package.sha256, "bytes": len(package.raw)}
    if args.command in ("inspect", "validate"):
        package = Package.load(args.archive)
        manifest = package.manifest
        result = {"id": manifest["id"], "version": manifest["version"],
                  "components": sorted(manifest["components"]), "sha256": package.sha256}
        if args.command == "inspect":
            result["manifest"] = manifest
        return result
    if args.command == "sandbox-init":
        return initialize(args.root)
    manager = Manager(args.root)
    if args.command == "status":
        return manager.status()
    if args.command == "plan":
        require(len(args.add) <= 128, "package_limit", "Too many package additions.")
        packages, total = [], 0
        for path in args.add:
            package = Package.load(path)
            total += len(package.raw)
            require(total <= 2 * MAX_TOTAL, "selection_limit", "Package additions exceed their combined size limit.")
            packages.append(package)
        return manager.plan(packages, args.remove, args.enable, args.disable)
    require(args.yes, "confirmation_required", "Review the operation and pass --yes to confirm.")
    if args.command == "apply":
        return manager.apply(args.plan)
    return manager.recover()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = run(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except HubError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}))
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Raw OS exceptions can contain personal paths or credential-bearing text.
        code = "io_error" if isinstance(exc, OSError) else "invalid_record"
        print(json.dumps({"error": code, "message": "Operation failed; preserve local state and inspect recovery status."}))
        return 2
