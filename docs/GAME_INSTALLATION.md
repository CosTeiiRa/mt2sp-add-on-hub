# Experimental game installation

The public CLI now coordinates client modules and server quests on the reviewed
client **2.0.135 / server 2.2.134** Windows/local-Docker layout. Use a disposable
world for this engineering preview. It is not a stable public gameplay release.
Only the exact official baseline is accepted; an older version label, a modified
world, or a copied ownership record cannot register itself as supported.

## Creator and operator workflow

The [desktop preview](DESKTOP.md) provides folder selection, setup, ZIP import,
review/apply, installed-package actions and recovery through the same commands.
The CLI below remains available for creators and scripted checks.

Install the optional game codec once, from a Hub checkout with Python 3.11+:

```powershell
python -m pip install -e ".[game]"
python -m mt2sp_hub new scratch/hello --id example.hello --kind combined --profile game
python -m mt2sp_hub build scratch/hello scratch/hello-0.1.0.zip
```

Creators edit one manifest and their Python/quest files. The builder computes
checksums. They supply no installation scripts, compiler commands or physical
game paths. Keep documentation and output archives outside the package folder.

Start the selected disposable server and wait for readiness. Close its client
and keep the launcher/updater and other editors idle during Hub operations:

```powershell
python -m mt2sp_hub probe "path/to/Metin2 Singleplayer" --build --runtime
python -m mt2sp_hub attach "path/to/Metin2 Singleplayer" --yes
python -m mt2sp_hub plan --root "path/to/Metin2 Singleplayer" --add scratch/hello-0.1.0.zip
python -m mt2sp_hub apply --root "path/to/Metin2 Singleplayer" --plan PLAN_ID --yes
python -m mt2sp_hub status --root "path/to/Metin2 Singleplayer"
```

`plan` prints an operation ID, selected package IDs and whether a server restart
is needed. It caches outputs and can build local images, but does not change the
running deployment. `apply` requires that exact still-current plan. Updating
uses `--add` with a new version of the same package ID. Use `--disable ID`,
`--enable ID` or `--remove ID` with `plan`, then apply the returned ID. Updating
a disabled package leaves it disabled. Changed bytes require a new version.

## What happens

Attachment verifies the official inputs, the running engine and effective quest
inventory. It compares the existing persistent world ID in the database, game
volume and spool, and binds all three named volumes to the selected Compose
project. Fixed client/world locks and matching local ownership records prevent
two Hub installations from managing the same targets. Attachment reserves a
world-specific image reference in Compose without restarting the server.

Preparation composes one client pack from the retained official bytes and all
enabled modules. A single Hub startup entry loads their namespaced sources. The
last client module's removal restores the original index/data bytes exactly.
Keys and game content are read from the verified local installation, never
distributed by Hub. The optional codec dependency is `lzokay==2.1.0`.

Server quests compile in the existing isolated compiler. Their verified outputs
use the stock quest-object directory already included by the official build;
authors do not patch its Dockerfile or quest list. Hub prepares an immutable
local image from a retained baseline plus those outputs. Local preparation
receipts retain the compiler, source and artifact fingerprints.

Apply verifies cached backups, free disk headroom, closed-client status, both
image references, world identity and current files before journaling. A changed
server quest set stops only the selected game service. Hub replaces the owned
quest files, its Compose image reference and the client pack, starts that service,
then verifies the immutable image ID, engine, complete quest inventory, health
and world identity before committing state. Client-only changes do not restart
the server. Hub can be closed after installation; it is not a gameplay service.

## Recovery and player progress

After an interruption, keep the game client closed and run:

```powershell
python -m mt2sp_hub status --root "path/to/Metin2 Singleplayer"
python -m mt2sp_hub recover --root "path/to/Metin2 Singleplayer" --yes
```

If attachment was interrupted, recovery completes that attachment. If an apply
did not commit its installation state, recovery restores the prior client,
quest files and server image. If it already committed, recovery verifies that
generation and finishes its receipt. Recovery itself is repeatable after another
interruption. Scratch writes stay outside the official server build tree.

The database must be available to identify the persistent world; the game
service may be stopped or absent during rollback. Start the existing database
through the normal environment if needed, keeping its volumes intact. Do not
create a new world to make recovery pass. Preserve the `.mt2sp-hub` stores,
retained images and volumes. External edits, missing/corrupt backups, a reset
world or changed image tag stop automatic recovery before restoration.

Disable/remove retains namespaced quest progress. Hub does not roll back the
database, undo rewards, remove items, or clean up active mount effects. Therefore
the first lifecycle example is a harmless login counter and window. Rewarding
or persistent-effect add-ons need their own tested gameplay lifecycle policy.
Quest names must remain stable and fit this build's **32-character** persisted
quest namespace; the starter reserves nine characters for `_greeting`.

## Evidence and remaining limits

Public tests use invented pack keys/content and a persistent fake server. They
cover the full lifecycle, subprocess termination at each install/attachment/
recovery boundary, partial writes, restart failure, malformed journals, stale
plans, moved claims, changed worlds/images, low disk space and external edits.
Real deployment tests use separately owned official client/server copies; no
game files, local identifiers, credentials or raw reports are published.

On 31 October 2026, an original combined window/login-counter add-on was tested
in a separately owned official Windows/local-Docker world on the build pair
above. Test-only startup/login instrumentation automated native connections;
the actual selection, loading, gameplay and installed Hub hooks executed. Each
probe restored the exact managed client pack afterward. The quest counter was
read from the test database after disconnect, never seeded as test evidence.

| Step | Observed connected behavior |
| --- | --- |
| Install | Window appeared; the quest saved visit 1 |
| Update to a new package version | Window appeared; visits continued from 1 to 2 |
| Disable | Original client pair restored; no add-on window; visits stayed at 2 |
| Re-enable | Window returned; visits continued from 2 to 3 |
| Interrupted removal and recovery | Previous installed generation restored; window returned; visits continued from 3 to 4 |
| Remove | Exact original client pair and stock quest inventory restored; native login succeeded without the window; visits stayed at 4 |

The removal process was terminated after writing both components. Recovery was
then terminated after restoring one client file. A fresh recovery completed the
rollback and passed another connected login. The persistent world and all three
named volumes remained the same.
Final state contained no installed packages or owned quest files and no pending
recovery. Backups, images and namespaced player progress were retained.

This is evidence for the harmless example, not rewards, mounted combat or
arbitrary modules. The rehearsal did not validate normal launcher navigation,
official updates, map transitions, long sessions or independent creator/user
usability. Controlled process exits do not simulate hardware power loss.

`deployment_files_verified` reports the installed files/runtime checks above.
`gameplay_verified` stays false in routine status: health and hashes cannot prove
that arbitrary author code behaves correctly. Connected play, quest behavior
and rewards require separate testing for each add-on.

There is no launcher/updater lock shared with Metin2SP yet. Do not rebuild images,
update the game, or run another manager during installation/recovery. An external
rebuild that changes the recorded image ID is detected as drift; Hub does not
silently adopt it. Existing attachments cannot yet migrate across official builds;
running `attach` again does not adopt an updated baseline. Test a newly reviewed
build in a fresh, separate installation and retain the old world and recovery
records. Build migration, relocation, remote server management, binary patching,
catalog and a standalone installer are not included. The first desktop window
uses this same coordinator. Independent creator usability trials
remain a public-alpha gate.

The smallest upstream improvements are recorded in the
[developer proposal](METIN2SP_INTEGRATION_PROPOSAL.md): a stable loader/include,
build and quest-inventory metadata, a shared update lock and deployment receipts.
