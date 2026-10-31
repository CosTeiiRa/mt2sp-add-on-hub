# Desktop preview

A small local window for the existing installation engine. It manages client,
server and combined packages on the [reviewed game build](GAME_INSTALLATION.md).
Use a disposable game world while this remains an engineering preview.

## Open Hub

Use Python 3.11+ with Tcl/Tk support. From a Hub checkout, install once:

```powershell
python -m pip install -e ".[game]"
mt2sp-hub-ui
```

The installed `mt2sp-hub-ui` launcher opens without a console on Windows. It is
in that Python installation's Scripts directory. You can also run
`python -m mt2sp_hub gui`, optionally with `--root "PATH_TO_TEST_GAME"`.
The command-line tools continue to work without Tcl/Tk. This is not yet a
self-contained Windows installer or Start menu installation.

## First installation

1. Start your disposable game server through its normal launcher and wait for
   readiness. Close the game client and keep its updater and other managers idle.
2. Choose **Choose folder...** and select the game folder. An existing Hub
   installation is checked. A new folder is checked against the reviewed build
   and local running server before **Review setup** becomes available.
3. Review setup and confirm. Hub verifies the world and ownership again, retains
   recovery data, and reserves its server image reference. Setup installs no add-ons.
4. Choose **Import ZIP...**. Hub validates and prepares the package; this can
   take several minutes and may compile quests or prepare a local server image.
   It does not activate the package yet. Use packages from creators you trust:
   add-ons run code in the game and are not a security sandbox.
5. Read the package/version/enabled-state changes and restart requirement. Choose
   **Confirm reviewed operation** to apply, or **Cancel review** to leave the
   installed selection unchanged. Prepared caches may remain after cancellation.

The selected local folder is visible so you can check the destination. Package
contents and selection are retained by the engine during preparation; replacing
the imported ZIP afterward does not replace the reviewed operation. If another
manager changes the installation, Hub refuses a stale plan and asks for a new review.

## Update, disable and remove

Import a new version of the same package ID to update it. A disabled package stays
disabled after an update. Select an installed row for **Enable**, **Disable** or
**Remove**; each action prepares a review before confirmation. Removal preserves
quest progress and rewards. Active gameplay effects follow the add-on's documented
policy; Hub does not automatically unmount riders or undo earned items.

Changing folders, **Check again**, cancellation, or a failed operation discards
the current review. Hub keeps only one operation running in the window, keeps
its controls responsive, and asks you to wait before closing during that work.
The window can be closed after an installation; it is not a gameplay service.

## Recover an interruption

Open the same folder. If its records show interrupted work, ordinary add-on
changes stay unavailable. Choose **Review recovery**, read its scope and confirm.
Hub completes pending setup, restores an uncommitted deployment, or verifies and
finishes an already committed operation. It may restart the selected game service.

If the status check cannot finish, recovery remains reachable. Keep the existing
database available, the client closed, and the same Hub records, images and world
volumes intact. A missing backup, external edit or changed world stops recovery;
the window does not bypass those checks. See [recovery details](GAME_INSTALLATION.md#recovery-and-player-progress).

If changes succeeded but a follow-up check failed, the result says both things.
Check again after resolving the reported condition; do not assume the change was
rolled back. Unexpected errors show a fixed message without raw local exception
details. The folder shown in the window is private local information: review any
screenshot before sharing it. Hub sends no reports or telemetry.

## Evidence and next steps

Workflow tests use the real public commands with synthetic files and the existing
invented game/server fixture. They cover setup checks, review without activation,
cached package identity, stale plans, updates of disabled packages, folder changes,
interrupted attachment/apply, recovery conflicts and error redaction. They do not
certify arbitrary add-on gameplay or independent-user usability.

On 31 October 2026, the native Windows window was exercised with an original
synthetic package: file-picker import, review, confirmation, disable, re-enable
and removal. A separate transaction was interrupted after a test-file write;
reopening the window showed recovery required, and confirmed recovery restored
the prior empty installation with no pending journal. This is a desktop/synthetic
rehearsal; the game coordinator's earlier connected evidence is documented
separately in [Game installation](GAME_INSTALLATION.md).

The first window deliberately has no catalog, account, updater, saved recent-folder
list or second deployment implementation. One-time Python setup, packaging for a
fresh Windows machine, independent creator/operator trials, accessibility across
assistive technologies and the official-update rehearsal remain public-alpha gates.
