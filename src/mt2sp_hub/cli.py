"""CLI for packages, synthetic sandboxes and reviewed local game installations."""
import argparse
import json
from pathlib import Path

from .authoring import create
from .core.packages import Package, build, pack
from .core.validation import MAX_PACKAGES, MAX_SELECTED_ARCHIVES
from .errors import HubError, require
from .installation.manager import Manager, initialize
from .installation.probe import describe, probe


def parser():
    root = argparse.ArgumentParser(prog="mt2sp-hub", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    desktop = commands.add_parser('gui', help='Open the local desktop installation and recovery interface')
    desktop.add_argument('--root', type=Path, help='Start with a selected game or existing practice sandbox')
    inspect_game = commands.add_parser("probe", help="Inspect a selected game layout without changing it")
    inspect_game.add_argument("root", type=Path)
    inspect_game.add_argument("--json", action="store_true", help="Return a report without local paths or raw metadata")
    inspect_game.add_argument("--runtime", action="store_true", help="Also read local Docker status; never starts or changes containers")
    inspect_game.add_argument("--build", action="store_true", help="Compare build inputs with the reviewed official reference, offline")
    starter = commands.add_parser("new", help="Create a sandbox or experimental game source starter")
    starter.add_argument("source", type=Path)
    starter.add_argument("--id", required=True, help="Public namespaced ID, for example example.hello")
    starter.add_argument("--kind", choices=("client", "server", "combined"), default="combined")
    starter.add_argument("--profile", choices=("sandbox", "game"), default="sandbox",
                         help="Game creates experimental Python/quest sources for the reviewed game adapter")
    starter.add_argument("--json", action="store_true", help="Return structured output")
    for name, description in (("build", "Build an author's source and compute payload checksums"),
                              ("pack", "Pack source while verifying its existing checksums")):
        command = commands.add_parser(name, help=description)
        command.add_argument("source", type=Path)
        command.add_argument("output", type=Path)
        if name == "build":
            command.add_argument("--json", action="store_true", help="Return structured output")
    for name in ("validate", "inspect"):
        command = commands.add_parser(name, help="Read a package without executing its payload")
        command.add_argument("archive", type=Path)
    init = commands.add_parser("sandbox-init", help="Initialize an empty, disposable synthetic target")
    init.add_argument("root", type=Path)
    attach_game = commands.add_parser("attach", help="Attach a reviewed game installation with recoverable ownership")
    attach_game.add_argument("root", type=Path)
    attach_game.add_argument("--yes", action="store_true", help="Confirm creating Hub ownership and a world-specific image reference")
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
    if args.command == "probe":
        return probe(args.root, runtime=args.runtime, build=args.build)
    if args.command == "new":
        manifest = create(args.source, args.id, args.kind, profile=args.profile)
        return {"id": manifest["id"], "version": manifest["version"],
                "components": sorted(manifest["components"]),
                "kind": "synthetic" if args.profile == "sandbox" else "game_preview"}
    if args.command in ("pack", "build"):
        # Keep artifacts outside the source; otherwise the next build would
        # correctly refuse the archive as an undeclared input file.
        require(not args.output.resolve().is_relative_to(args.source.resolve()),
                "output_in_source", "Put the output archive outside the source folder.")
        package = (build if args.command == "build" else pack)(args.source)
        try:
            with args.output.open("xb") as stream:
                stream.write(package.raw)
        except FileExistsError as exc:
            raise HubError("output_exists", "Output already exists. Choose a new archive filename.") from exc
        result = {"sha256": package.sha256, "bytes": len(package.raw)}
        if args.command == "build":
            manifest = package.manifest
            result.update(id=manifest["id"], version=manifest["version"],
                          components=sorted(manifest["components"]))
        return result
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
    if args.command == "attach":
        require(args.yes, "confirmation_required", "Pass --yes to attach this reviewed game installation.")
        from .installation.game_manager import attach
        return attach(args.root)
    # A synthetic marker selects only the synthetic writer. Otherwise a game
    # must have the matching fixed world/client claims; layout alone is never
    # permission to write to it.
    from .installation.probe import _record, locate
    if (args.root / '.mt2sp-hub/identity.json').is_file() and _record(args.root.resolve(), 'identity.json').get('kind') == 'synthetic':
        manager = Manager(args.root)
    else:
        from .installation.game_manager import GameManager, attach
        binding = locate(args.root)
        try:
            identity = _record(binding.world, 'identity.json')
        except FileNotFoundError:
            raise HubError('game_not_attached', 'Run attach for this game folder before planning installation.') from None
        if identity.get('attachment') == 'pending':
            if args.command == 'recover':
                require(args.yes, 'confirmation_required', 'Pass --yes to recover the pending attachment.')
                return attach(args.root)
            require(args.command == 'status', 'recovery_required', 'Recover the pending attachment first.')
            return {'kind': 'metin2sp', 'attachment': 'pending', 'recovery_required': True}
        manager = GameManager(args.root)
    if args.command == "status":
        return manager.status()
    if args.command == "plan":
        require(len(args.add) <= MAX_PACKAGES, "package_limit", "Too many package additions.")
        packages, total = [], 0
        for path in args.add:
            package = Package.load(path)
            total += len(package.raw)
            require(total <= MAX_SELECTED_ARCHIVES, "selection_limit", "Package additions exceed their combined size limit.")
            packages.append(package)
        return manager.plan(packages, args.remove, args.enable, args.disable)
    require(args.yes, "confirmation_required", "Review the operation and pass --yes to confirm.")
    if args.command == "apply":
        return manager.apply(args.plan)
    return manager.recover()


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'gui':
        from .desktop import launch
        return launch(args.root)
    try:
        result = run(args)
        if args.command == "probe" and not args.json:
            describe(result)
        elif args.command in ("new", "build") and not args.json:
            verb = "Created" if args.command == "new" else "Built"
            print(f"{verb} {result['id']} {result['version']} ({', '.join(result['components'])}).")
            if args.command == "new":
                print("Edit addon.json and the files under payload/, then run build.")
                if args.profile == "sandbox":
                    print("This starter contains sandbox text files, not a working game add-on.")
                else:
                    print("Experimental game source created. Real installation and native compatibility remain unverified.")
            else:
                print("Checksums generated. Source files unchanged. Installation requires matching target capabilities.")
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except HubError as exc:
        code, message = exc.code, str(exc)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Raw OS exceptions can contain personal paths or credential-bearing text.
        code = "io_error" if isinstance(exc, OSError) else "invalid_record"
        message = "Operation failed; preserve local state and inspect recovery status."
        if args.command in ("new", "build"):
            message = "Could not read or write the project. Check folder permissions and free disk space."
            if isinstance(exc, FileNotFoundError):
                message = "An input file or output parent folder is missing. Check the project and folder names."
        elif args.command == "probe":
            message = "Could not inspect the selected folder. Check that it exists and is readable."
    if args.command in ("new", "build", "probe") and not args.json:
        print(f"Error [{code}]: {message}")
    else:
        print(json.dumps({"error": code, "message": message}))
    return 2
