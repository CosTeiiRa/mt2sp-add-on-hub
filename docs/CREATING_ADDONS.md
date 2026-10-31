# Create your first sandbox add-on

This guide tests packaging and installation with original text files. It does not create a playable Metin2SP feature. For that engineering workflow, use the [game starters](GAME_CREATORS.md) and [experimental game installation guide](GAME_INSTALLATION.md). You need Python 3.11 or newer and a checkout of this public repository; Studio and a GitHub account are not required to run these commands.

The [experimental game-source guide](GAME_CREATORS.md) uses the same workflow for a Python module, a quest, or both. Use those sources to develop the integration; keep using the sandbox starters below for installation testing until the real adapter is verified.

## 1. Create and build

Open PowerShell in the Hub checkout. Use fresh paths for this first run:

```powershell
$env:PYTHONPATH = "src"
python -m mt2sp_hub new scratch/hello --id example.hello --kind combined
python -m mt2sp_hub build scratch/hello scratch/hello-0.1.0.zip
```

Choose `client`, `server` or `combined`. Your package ID should be a stable public namespace and name, such as `example.hello`; do not use an email address or personal machine name. The starter uses version `0.1.0` and the MIT license; review the name and license before distributing your own work.

The source folder contains only:

```text
hello/
  addon.json
  payload/
    client.txt
    server.txt
```

`addon.json` describes the add-on. `payload/` holds its declared files. The starter includes only the components you requested.

The builder computes checksums from the current file contents and places them in the archive. You never need to calculate or edit checksums. It leaves your source unchanged, and the same source produces the same archive bytes. Building never runs the payload.

Keep archives, your project README, Git metadata and development tools **outside this source folder**. In a future add-on repository, this folder can be named `package/`, alongside the repository README. Builds refuse undeclared files instead of accidentally including them. Do not place personal information in the declared payload either: it is part of the distributable archive.

## 2. Test the installation

Create a new disposable sandbox, then ask Hub to show the changes:

```powershell
python -m mt2sp_hub sandbox-init scratch/hello-sandbox
python -m mt2sp_hub plan --root scratch/hello-sandbox --add scratch/hello-0.1.0.zip
```

The plan lists the selected package and relative files to change. Planning does not write the target files. Copy the returned `plan` ID into the command below after reviewing it:

```powershell
python -m mt2sp_hub apply --root scratch/hello-sandbox --plan PLAN_ID_FROM_REVIEW --yes
python -m mt2sp_hub status --root scratch/hello-sandbox
```

For the combined starter, you can now open `client/example.hello/message.txt` and `server/example.hello/message.txt` inside that sandbox. These are separate fixture directories, not real game components. Installation commands currently return JSON for engineering review; a friendly installation interface is still to come.

## 3. Edit and update

Edit `payload/client.txt` or `payload/server.txt`. In `addon.json`, change `version` from `0.1.0` to `0.1.1`. Then:

```powershell
python -m mt2sp_hub build scratch/hello scratch/hello-0.1.1.zip
python -m mt2sp_hub plan --root scratch/hello-sandbox --add scratch/hello-0.1.1.zip
```

Review and apply the new plan ID using the same `apply` command. Hub retains the original baseline so removing the add-on later can restore it.

An installation remembers the bytes of every ID/version it has seen. Changed bytes require a new version, even after removal. During early experiments you can instead use a fresh disposable sandbox. Rebuilding identical source is fine; choose an unused archive filename because the builder never overwrites an existing artifact.

To add a file, put it under `payload/` and add a row to the appropriate component's `files` list in `addon.json`:

```json
{"source": "extra.txt", "target": "example.hello/extra.txt"}
```

`source` is relative to `payload/`. `target` is relative to that component's sandbox directory. Keep targets under your add-on's namespace. The starter's API requirement and `fixture.files` capability describe the sandbox only; do not change them to claim game compatibility.

Editor tooling can use [the source schema](../sdk/schemas/addon-source-v2.schema.json). Configure it in the editor; do not add an unsupported `$schema` field to the manifest. The [archive schema](../sdk/schemas/addon-v2.schema.json) additionally requires hashes. `build` refreshes any existing well-formed source hashes, while the lower-level `pack` command verifies existing hashes. For normal authoring, use `build`.

## 4. Remove and recover

```powershell
python -m mt2sp_hub plan --root scratch/hello-sandbox --remove example.hello
```

Review and apply that new plan. `--disable example.hello` and `--enable example.hello` use the same flow. Removal and recovery work using Hub's cached data, even if the original ZIP is gone.

If an operation is interrupted, check `status`. If it reports pending recovery, run:

```powershell
python -m mt2sp_hub recover --root scratch/hello-sandbox --yes
```

External file changes may block automatic recovery. Preserve the sandbox and its `.mt2sp-hub` directory; do not delete journals or edit their checksums. See [the foundation contracts](FOUNDATION.md) for the recovery rules.

## Common fixes

| Message | Action |
| --- | --- |
| Starter folder already exists | Choose a new folder; `new` never replaces your work |
| Output already exists | Choose an unused output filename; bump the version if the contents changed |
| Put the output archive outside the source folder | Put the ZIP beside the source folder, as in this guide |
| Source contains undeclared files | Declare the intended payload file, or move development/private files outside the package source |
| Missing or unsupported manifest fields | Compare with a fresh starter; fields are intentionally strict |
| Published package ID/version already has different bytes | Increase the version before testing the changed package in the same sandbox |

`new` and `build` show short readable messages. Add `--json` to either for scripts. Existing validation and installation commands keep their structured output. Errors omit raw local paths; manifests and payload contents still need your own privacy review before sharing.
