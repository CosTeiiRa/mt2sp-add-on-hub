"""Reviewed file transactions for explicitly initialized synthetic sandboxes.

No client packs, Docker services or databases are touched by this adapter.
"""
from __future__ import annotations

import copy
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from ..errors import require
from ..core.packages import Package
from ..core.resolver import resolve
from ..core.validation import (MAX_FILE, MAX_FILES, MAX_PACKAGES, MAX_SELECTED_ARCHIVES, MAX_TOTAL, confined, digest,
                               identifier, path_set, read_bounded)
from .locking import exclusive
from .storage import Store, atomic_write, unlink

CONTROL = ".mt2sp-hub"


def _token(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value),
            "plan_id", "Invalid operation ID.")
    return value


def initialize(root):
    """Create a disposable sandbox, refusing any existing nonempty directory."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    require(not any(root.iterdir()), "sandbox_not_empty", "Sandbox initialization requires an empty directory.")
    control = root / CONTROL
    control.mkdir()  # Exclusive creation arbitrates concurrent initialization.
    store = Store(control)
    identity = {"schema": 1, "kind": "synthetic", "id": uuid.uuid4().hex,
                "canonical_root": os.path.normcase(str(root))}
    store.envelope("identity.json", identity)
    store.envelope("state.json", {"schema": 1, "installation": identity["id"],
                                 "generation": 0, "installed": {}, "managed": {}})
    return {"installation": identity["id"], "kind": "synthetic"}


class Manager:
    def __init__(self, root, checkpoint=None):
        self.root = Path(root).resolve()
        control = confined(self.root, CONTROL)
        require(control.is_dir(), "sandbox_required", "An explicitly initialized synthetic sandbox is required.")
        self.store = Store(control)
        self.checkpoint = checkpoint or (lambda stage: None)
        self.identity = self.store.verified("identity.json")
        require(isinstance(self.identity, dict), "installation_identity", "Invalid installation identity.")
        self._identity_check()

    def _identity_check(self):
        identity = self.store.verified("identity.json")
        require(isinstance(identity, dict) and identity.get("schema") == 1
                and identity.get("kind") == "synthetic"
                and identity.get("id") == self.identity.get("id")
                and identity.get("canonical_root") == os.path.normcase(str(self.root)),
                "installation_identity", "Installation identity changed or the sandbox was moved/copied.")
        _token(identity["id"])

    @contextmanager
    def locked(self):
        with exclusive(self.store.path("lock")):
            self._identity_check()
            yield

    def _state(self):
        state = self.store.verified("state.json")
        self._validate_state(state)
        return state

    def _validate_state(self, state):
        require(isinstance(state, dict) and set(state) ==
                {"schema", "installation", "generation", "installed", "managed"}
                and state["schema"] == 1 and state["installation"] == self.identity["id"]
                and type(state["generation"]) is int and state["generation"] >= 0
                and isinstance(state["installed"], dict) and len(state["installed"]) <= MAX_PACKAGES
                and isinstance(state["managed"], dict) and len(state["managed"]) <= MAX_FILES,
                "state_schema", "Unsupported or invalid installation state.")
        path_set(state["managed"])
        for path, row in state["managed"].items():
            self._target(path)
            require(isinstance(row, dict) and set(row) == {"owner", "sha256", "baseline"}
                    and row["owner"] in state["installed"], "state_schema", "Invalid ownership record.")
            for key in ("sha256", "baseline"):
                require((key == "baseline" and row[key] is None) or isinstance(row[key], str)
                        and re.fullmatch(r"[0-9a-f]{64}", row[key]),
                        "state_schema", "Invalid state object reference.")
        for ident, row in state["installed"].items():
            identifier(ident)
            require(isinstance(row, dict) and set(row) == {"archive", "version", "enabled"}
                    and type(row["enabled"]) is bool and isinstance(row["version"], str)
                    and isinstance(row["archive"], str) and re.fullmatch(r"[0-9a-f]{64}", row["archive"]),
                    "state_schema", "Invalid installed package record.")

    def _clear(self):
        require(not self.store.path("active.json").exists(), "recovery_required",
                "An interrupted transaction must be recovered first.")

    def _target(self, relative):
        require(isinstance(relative, str) and relative.split("/")[0] in {"client", "server"}
                and "/" in relative, "target_invalid", "Only synthetic client/server resources are supported.")
        return confined(self.root, relative)

    def _bytes(self, path):
        target = self._target(path)
        if not target.exists():
            return None
        require(target.is_file(), "target_invalid", "A target resource is not a regular file.")
        return read_bounded(target, MAX_FILE)

    def _hash(self, path):
        raw = self._bytes(path)
        return digest(raw) if raw is not None else None

    def _import(self, package):
        manifest, _ = package.unpack()
        archive = self.store.put(package.raw)
        # A permanent release ledger prevents changed bytes after uninstall.
        release = "releases/" + manifest["id"] + "/" + digest(manifest["version"].encode()) + ".json"
        if self.store.path(release).exists():
            require(self.store.verified(release) == {"archive": archive}, "release_changed",
                    "Published package ID/version already has different bytes; use a new version.")
        else:
            self.store.envelope(release, {"archive": archive})
        return manifest, archive

    def plan(self, additions=(), remove=(), enable=(), disable=()):
        """Persist a reviewed candidate without changing synthetic target files."""
        with self.locked():
            self._clear()
            before = self._state()
            desired = copy.deepcopy(before["installed"])
            touched = set()
            require(len(additions) <= MAX_PACKAGES, "package_limit", "Too many package additions.")
            require(sum(len(p.raw) for p in additions) <= MAX_SELECTED_ARCHIVES,
                    "selection_limit", "Package additions exceed their combined size limit.")
            for package in additions:
                manifest, archive = self._import(package)
                ident = manifest["id"]
                require(ident not in touched, "duplicate_package", "A package was selected twice.")
                touched.add(ident)
                desired[ident] = {"archive": archive, "version": manifest["version"],
                                  "enabled": desired.get(ident, {}).get("enabled", True)}
            for action, ids in (("remove", remove), ("enable", enable), ("disable", disable)):
                for ident in ids:
                    identifier(ident)
                    require(ident not in touched and ident in desired, "package_selection",
                            "Conflicting selection or package is not installed.")
                    touched.add(ident)
                    if action == "remove":
                        del desired[ident]
                    else:
                        desired[ident]["enabled"] = action == "enable"
            require(bool(touched), "empty_plan", "Select at least one package operation.")
            require(len(desired) <= MAX_PACKAGES, "package_limit", "Too many installed packages.")
            packages = []
            total_archives = 0
            for ident, row in sorted(desired.items()):
                raw = self.store.get(row["archive"])
                total_archives += len(raw)
                require(total_archives <= MAX_SELECTED_ARCHIVES, "selection_limit", "Selected package cache exceeds its limit.")
                package = Package(raw)
                manifest = package.manifest
                require(manifest["id"] == ident and manifest["version"] == row["version"],
                        "state_corrupt", "Installed package identity does not match its object.")
                if row["enabled"]:
                    packages.append(package)
            order, outputs, owners = resolve(packages)
            require(len(outputs) <= MAX_FILES and sum(map(len, outputs.values())) <= MAX_TOTAL,
                    "selection_limit", "Selected outputs exceed installation limits.")
            managed, changes = {}, []
            resources = sorted(set(before["managed"]) | set(outputs))
            path_set(resources)
            for path in resources:
                raw = self._bytes(path)
                observed = self.store.put(raw) if raw is not None else None
                previous = before["managed"].get(path)
                if previous:
                    require(observed == previous["sha256"], "target_drift", "Managed files changed outside Hub.")
                baseline = previous["baseline"] if previous else observed
                if path in outputs:
                    after_hash = self.store.put(outputs[path])
                    managed[path] = {"owner": owners[path], "sha256": after_hash, "baseline": baseline}
                else:
                    after_hash = baseline
                changes.append({"path": path, "before": observed, "after": after_hash})
            after = {"schema": 1, "installation": self.identity["id"],
                     "generation": before["generation"] + 1,
                     "installed": desired, "managed": managed}
            plan_id = uuid.uuid4().hex
            plan = {"schema": 1, "id": plan_id, "installation": self.identity["id"],
                    "before": before, "after": after, "changes": changes, "order": order}
            self.store.envelope("plans/" + plan_id + ".json", plan)
            return self._summary(plan)

    @staticmethod
    def _summary(plan):
        return {"plan": plan["id"], "generation": plan["before"]["generation"],
                "packages": sorted(plan["after"]["installed"]), "order": plan["order"],
                "selection_changes": [{"id": ident,
                                       "before": plan["before"]["installed"].get(ident),
                                       "after": plan["after"]["installed"].get(ident)}
                                      for ident in sorted(set(plan["before"]["installed"]) |
                                                          set(plan["after"]["installed"]))
                                      if plan["before"]["installed"].get(ident) !=
                                      plan["after"]["installed"].get(ident)],
                "changes": [row for row in plan["changes"] if row["before"] != row["after"]]}

    def _validate_plan(self, plan):
        require(isinstance(plan, dict) and set(plan) ==
                {"schema", "id", "installation", "before", "after", "changes", "order"}
                and plan["schema"] == 1 and plan["installation"] == self.identity["id"],
                "plan_invalid", "Invalid or foreign installation plan.")
        _token(plan["id"])
        self._validate_state(plan["before"])
        self._validate_state(plan["after"])
        require(plan["after"]["generation"] == plan["before"]["generation"] + 1
                and isinstance(plan["changes"], list) and len(plan["changes"]) <= MAX_FILES * 2,
                "plan_invalid", "Invalid plan generation or change list.")
        paths = []
        for row in plan["changes"]:
            require(isinstance(row, dict) and set(row) == {"path", "before", "after"},
                    "plan_invalid", "Invalid resource change.")
            self._target(row["path"])
            paths.append(row["path"])
            for key in ("before", "after"):
                if row[key] is not None:
                    self.store.get(row[key])  # Verify every backup before any mutation.
        path_set(paths)
        require(set(paths) == set(plan["before"]["managed"]) | set(plan["after"]["managed"]),
                "plan_invalid", "Plan does not cover its managed resources.")
        for row in plan["changes"]:
            old = plan["before"]["managed"].get(row["path"])
            new = plan["after"]["managed"].get(row["path"])
            baseline = old["baseline"] if old else row["before"]
            require(not old or old["sha256"] == row["before"],
                    "plan_invalid", "Plan input does not match ownership state.")
            require((new and new["sha256"] == row["after"] and new["baseline"] == baseline)
                    or (new is None and row["after"] == baseline),
                    "plan_invalid", "Plan output does not match ownership state.")

    def _write_target(self, path, key):
        target = self._target(path)
        if key is None:
            if target.exists():
                unlink(target)
        else:
            raw = self.store.get(key)
            atomic_write(target, raw)
        require(self._hash(path) == key, "write_verification", "Target write verification failed.")

    def _finish(self, plan, outcome):
        self.store.envelope("receipts/" + plan["id"] + ".json", {"outcome": outcome, "plan": plan})
        self.checkpoint("receipt")
        unlink(self.store.path("active.json"))
        self.checkpoint("complete")
        return {"plan": plan["id"], "outcome": outcome}

    def apply(self, plan_id):
        _token(plan_id)
        with self.locked():
            self._clear()
            require(not self.store.path("receipts/" + plan_id + ".json").exists(),
                    "plan_used", "A completed or recovered plan cannot be reused.")
            plan = self.store.verified("plans/" + plan_id + ".json")
            self._validate_plan(plan)
            require(plan["id"] == plan_id and self._state() == plan["before"],
                    "plan_stale", "Installation state changed; review a new plan.")
            for row in plan["changes"]:
                require(self._hash(row["path"]) == row["before"], "plan_stale",
                        "Target inputs changed; review a new plan.")
            self.store.envelope("active.json", plan)
            self.checkpoint("journal")
            for row in plan["changes"]:
                if row["before"] != row["after"]:
                    # Detect non-cooperating writers again at each boundary.
                    require(self._hash(row["path"]) == row["before"], "target_drift", "Target changed during apply.")
                    self._write_target(row["path"], row["after"])
                    self.checkpoint("file:" + row["path"])
            require(all(self._hash(r["path"]) == r["after"] for r in plan["changes"]),
                    "target_drift", "Targets changed before state commit.")
            self.store.envelope("state.json", plan["after"])
            self.checkpoint("state")
            return self._finish(plan, "applied")

    def recover(self):
        with self.locked():
            if not self.store.path("active.json").exists():
                return {"outcome": "nothing_pending"}
            plan = self.store.verified("active.json")
            self._validate_plan(plan)
            current = self._state()
            require(current in (plan["before"], plan["after"]), "recovery_conflict",
                    "State differs from both journal generations; preserve it for inspection.")
            committed = current == plan["after"]
            # Preflight all resources before restoring any; never overwrite drift.
            for row in plan["changes"]:
                allowed = {row["after"]} if committed else {row["before"], row["after"]}
                require(self._hash(row["path"]) in allowed, "recovery_conflict",
                        "External file changes prevent automatic recovery.")
            if not committed:
                for row in reversed(plan["changes"]):
                    observed = self._hash(row["path"])
                    require(observed in {row["before"], row["after"]}, "recovery_conflict",
                            "Target changed during recovery.")
                    if observed != row["before"]:
                        self._write_target(row["path"], row["before"])
                        self.checkpoint("restore:" + row["path"])
                require(all(self._hash(r["path"]) == r["before"] for r in plan["changes"]),
                        "recovery_conflict", "Restoration verification failed.")
            return self._finish(plan, "applied" if committed else "rolled_back")

    def status(self):
        with self.locked():
            state = self._state()
            return {"kind": "synthetic", "generation": state["generation"],
                    "packages": [{"id": ident, "version": row["version"], "enabled": row["enabled"]}
                                 for ident, row in sorted(state["installed"].items())],
                    "managed_files": len(state["managed"]),
                    "recovery_required": self.store.path("active.json").exists()}
