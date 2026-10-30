# Official build reference

`probe --build` compares a selected installation with one reviewed reference, offline and without changing it:

```powershell
python -m mt2sp_hub probe "path/to/Metin2 Singleplayer" --build
```

Add `--json` for the same sanitized result, or `--runtime` for the separate read-only Docker observation. No archive download, game execution, repair, baseline registration or installation happens during this check.

## What is reviewed

The current reference is **client 2.0.135 / protected server 2.2.134**. Other version pairs report `unknown_build`; a version label cannot authorize a new build. Matching labels select a candidate whose actual bytes must still match.

The reference combines these public upstream sources:

- The full **2.2.106 protected distribution** linked by the [official game site](https://metin2singleplayer.com/) to [this Drive file](https://drive.google.com/file/d/1RuPolBqX6rP2nMzY-tHSgsEPgtaMJTkK/view). Its archive SHA-256 is `f89ab4005d8346cf2a9114923cf25d8ab6554bca9275adac8f42b80e5ebf78ad`, length 1,025,987,160 bytes. This is a Hub-reviewed HTTPS-download fingerprint, **not a publisher-signed checksum**. A changed Drive download requires a new review.
- The client update, client supplement and protected server update from [upstream release v2.2.134](https://github.com/TieruYT/metin2-playerbots/releases/tag/v2.2.134), verified against the GitHub release assets' published SHA-256 digests and sizes.
- The executable retained by the official updater from [v2.2.126](https://github.com/TieruYT/metin2-playerbots/releases/tag/v2.2.126), identified by its published asset digest. The newer client update does not contain a replacement executable.

The exact pins are in `installation/official_build.py`. They were derived from those upstream bytes, not from an installed user's files. No game bytes, pack configuration values, keys or private observations are included in that file. Release asset metadata is the update archive authority: the source commit associated with a release can still contain an older update manifest.

The full distribution matters: update ZIPs omit the stock quest objects and base `quest_functions`. An update ZIP alone cannot establish the complete server build inventory. The reviewed server tree overlays the protected update onto the full distribution's `linux-port/docker/game` tree.

## Checks and limits

| Input | Check |
| --- | --- |
| Client executable, root index/data, local root configuration, native DLLs shipped in the client update | Exact size and SHA-256 for 23 inputs |
| Server Dockerfile, compiler, game/database binaries, entrypoint and stock quest function list | Six individual size/digest checks for useful diagnostics |
| Complete server game build tree | Canonical sorted path/length/digest inventory: 14,493 files, 60,666,041 bytes |

The tree includes stock quest objects and all build inputs; extra, missing or changed files produce `reference_mismatch`. Only empty directories are ignored. It rejects links/reparse points, nonregular files, invalid/colliding portable paths and excessive counts/depth/bytes. Limits are 64 MiB per input, 128 MiB per tree, 32,768 files, 65,536 entries and depth 32. File identities and directory inventories are rechecked to detect changes during inspection. This is an unlocked snapshot, not an updater lock; activation must repeat checks under the coordinator's locks and require other writers idle.

Version labels accept normal surrounding whitespace and UTF-8 BOMs. Binary/build inputs use exact bytes; scripts are not silently normalized. The report contains fixed reviewed relative paths and status codes. It omits observed hashes, unexpected local filenames, absolute paths and raw metadata/errors.

`reference_match` means only that these scoped source inputs match. Other client resource packs, the effective Docker image, compiler recipe, persistent world identity and loaded deployment revision are not certified by this check. The report always has `activation_supported: false`, and the outer probe keeps `can_install: false`. A healthy container cannot change that.

## Reproduce the reference

Maintainers can obtain the four archives separately, keep them outside tracked source, and run:

```powershell
python tools/review_game_baseline.py --base BASE.zip --client CLIENT.zip --supplement SUPPLEMENT.zip --server SERVER.zip
```

The tool verifies the pinned complete archives before reading member inventories and compares the result with the checked-in reference. It neither extracts files nor registers arbitrary local baselines. The executable pin comes directly from the separately published asset metadata. Keep full archives, extracted trees and detailed evidence local. Public CI uses invented fixtures and requires no game download.

Local verification reproduced the reference from official inputs and checked an owned disposable tree. Client pack replacement/recovery is a separate [file-step rehearsal](CLIENT_FILES.md). Real ownership attachment, pack composition in the public adapter, an exact compiler/runtime profile and coordinated server activation remain required before enabling installation.
