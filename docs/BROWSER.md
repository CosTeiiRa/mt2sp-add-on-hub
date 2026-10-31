# Browser preview

Hub opens in your browser and uses a small service on the same computer to manage
game files and the local server. It reuses the CLI's package, installation and
recovery engine. Studio is not required. Use a disposable game world while this
remains an engineering preview for the [reviewed build](GAME_INSTALLATION.md).

## Start Hub

With Python 3.11+ installed, run this once from a Hub checkout:

```powershell
python -m pip install -e ".[game]"
```

Then launch it:

```powershell
mt2sp-hub serve
```

Your browser opens automatically. Keep the launcher running while using Hub.
If the browser does not open, copy the private local link printed by the launcher.
The link grants access to this Hub session; keep it private.

You can also use `python -m mt2sp_hub serve`, add `--root "PATH_TO_TEST_GAME"`
to select a folder at launch, or use `--no-open` to open the printed link yourself.
The earlier `mt2sp-hub-ui` and `gui` commands now open this same browser interface.
Reinstall from the updated checkout to replace an older installed launcher.
Tcl/Tk and a separate desktop window are no longer used. A bundled Windows
launcher without Python setup remains future work.

## Install and manage an add-on

1. Start your disposable game server through its normal launcher and wait for
   readiness. Close the game client; keep its updater and other managers idle.
2. Copy the game folder's full path from File Explorer's address bar, paste it
   into **Game folder**, and choose **Check folder**. Browser file pickers do not
   supply the full game folder path, so this first preview uses a path field.
3. For a new installation, choose **Review setup**, read it and confirm. Hub
   verifies the build, running server and world ownership, keeps recovery data,
   and reserves its server image reference. Setup installs no add-ons. A failed
   pre-claim setup that left only its regular lock files can be checked and retried;
   other unknown records remain protected.
4. Choose an **Add-on ZIP**, then **Review ZIP**. The ZIP is sent only to your local
   Hub service, validated and prepared. Preparation can take several minutes and
   may compile quests or prepare a server image. It does not activate the add-on.
5. Read the exact package/version/enabled-state changes and restart requirement.
   Choose **Confirm reviewed operation**, or **Cancel review** to keep the current
   installed selection. Prepared caches may remain after cancellation.

Use packages from creators you trust: add-ons run game code and are not a security
sandbox. The ordinary package limits also apply to browser uploads. Temporary
upload files are removed after preparation or a handled failure. A force-killed
service can leave an unused upload in the operating system's temporary folder;
that file is never automatically applied.

Import a newer version of the same ID to update. A disabled add-on stays disabled
after an update. Installed rows offer **Enable** or **Disable**, and **Remove**;
each action requires review and confirmation. Removal preserves quest progress
and earned rewards. It does not automatically reverse active gameplay effects
such as mounted riders; follow the add-on's documented policy.

## Refresh, multiple tabs and recovery

Refreshing the page retains this tab's session and displays the operation's latest
state. Closing a tab does not stop an installation. Reopen the launcher's private
link to reconnect. If a request loses its connection, check the result before
repeating it; the page never automatically retries a write.

All tabs share one selected folder and one review. Another tab's operation
invalidates an older view. Confirmation must match the specific current review,
and only one operation can run at a time. The installation engine additionally
rejects stale plans, changed files and changed worlds across separate Hub processes.

If Hub reports interrupted work, normal add-on changes are unavailable. Choose
**Review recovery** and confirm. Recovery finishes pending setup, restores an
uncommitted deployment, or verifies and finishes an already committed change.
It may restart the selected game server. Recovery remains reachable when a status
check fails. Keep the same database, world volumes, Hub records and backups intact;
missing backups or external edits stop recovery rather than being overwritten.
See [recovery details](GAME_INSTALLATION.md#recovery-and-player-progress).

If a change succeeds but its follow-up check fails, the result reports both.
Check again after resolving the condition; do not assume the change rolled back.

Choose **Stop Hub** when finished. It is unavailable during an operation. Ctrl+C
in the launcher also waits for active work. Installed add-ons continue working
with Hub stopped. Starting Hub again creates a new private link; old sessions
cannot control it.

## Local service boundary

The service binds only to `127.0.0.1` on an available port. It has no LAN/remote
binding option, hosted backend, account, CDN, telemetry or Studio dependency.
It serves three bundled assets and a small fixed API; it does not serve folders
or provide shell, arbitrary file-download or remote-server endpoints.

Each launch generates a random session key. The launch link carries it in a URL
fragment, which the page removes immediately and retains in tab session storage.
API requests require that key in a header, the exact local Host, and same-origin
POSTs. Cross-site requests and CORS preflights are refused. Framing and external
scripts are blocked, responses are not cached, and request logs are disabled.
Uploads have bounded sizes/timeouts and the service bounds simultaneous requests.
Local malware or a browser extension with access to the page is outside this boundary.

The selected path is intentionally visible locally. Review screenshots before
sharing; never publish the private launch link or local game records.

This is a dedicated loopback handler built on Python's HTTP primitives, not a
public web server. Python documents the [HTTP server's deployment limitations](https://docs.python.org/3.13/library/http.server.html).
The browser boundary also uses the documented [Origin header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin)
and [Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy).
Do not expose this preview through a proxy, tunnel or port forwarding.

## Evidence and remaining work

Shared workflow tests exercise setup, combined deployment and interrupted recovery
using the existing invented game/server fixture. Real loopback HTTP tests cover
installation/update/disable/enable/remove, review cancellation, stale tabs,
confirmation replay, busy operations, interrupted uploads, recovery and request
boundaries. These checks do not certify arbitrary add-on gameplay or usability.

On 31 October 2026, the actual browser page completed ZIP selection, reviewed
installation, refresh, disable, re-enable, removal and explicit service shutdown
with an original synthetic package. A transaction interrupted after a test-file
write was detected and restored through reviewed browser recovery. An isolated
installed wheel also opened the page outside the source checkout with all bundled
assets and no browser console errors. This is synthetic UI evidence, separate
from the earlier [connected game evidence](GAME_INSTALLATION.md).

The next decisions are simpler Windows startup, an independent operator/creator
trial, and the official-update rehearsal. Broader browser/accessibility acceptance
and public-alpha gameplay checks remain open. Catalogs and new gameplay features
are separate steps; the add-on library can remain private.
