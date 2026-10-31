# Client pack replacement and recovery steps

The internal `installation/client_files.py` helper prepares, writes and verifies the two fixed client resources, `pack/root.index` and `pack/root.data`. It uses the world's existing object store and never accepts package-selected filesystem destinations. It is a component of the game coordinator, not a standalone installer or new ownership system.

Preparation requires the expected current fingerprints and already-validated composed pack bytes. It snapshots and caches the complete before/after pairs without changing the client. Each pair is bounded to 64 MiB, within the existing object's read limit. The returned record is serializable, contains object references and a private canonical client binding, and must remain local.

The parent coordinator must verify the build and ownership, require a closed client and idle updater, hold both fixed target locks, and persist the full operation journal **before** invoking a file step. These prerequisites are not supplied by this helper. It deliberately does not create ownership, start/stop processes, commit installed state or clear the parent's journal.

For either replacement or restoration, every cached object and both current targets are checked before the first write. Current bytes must equal a recorded before or after revision. Each replacement uses the existing flushed temporary-file/atomic-replace primitive, rechecks the target at the write boundary and verifies the result. The pair is not filesystem-atomic: a crash between files leaves a mixed pair and requires recovery before launch.

For an uncommitted parent operation, `write(..., phase='before')` restores the original pair in reverse order and can be retried after another interruption. For a committed operation, the coordinator calls `verify()` and completes its receipt only if the desired pair still matches. External edits, an official update, missing targets or corrupt backups block automatic restoration; the helper preserves the journal and does not overwrite an unknown revision.

## Evidence and remaining work

Synthetic tests cover stale preparation, fixed paths/bindings, size limits, corrupt backups, edits at write boundaries, interruption between files, partial/short writes, flush/fsync/directory-sync failures, repeatable restoration, and verification without repair.

An additional private rehearsal uses the official reference pack in an owned disposable copy, adds the generated runtime bundle for two original window packages, and verifies every logical member after composition. Separate worker processes are terminated after the first replacement and during restoration; a fresh worker's saved record restores the original index/data bytes. Raw pack data, keys, copied game files and native reports remain excluded from the repository. The public helper has no private application imports or additional dependencies; public `client_pack.py` and `pack_codec.py` now provide the bounded composer, using locally verified configuration and the optional game codec dependency.

The [game coordinator](GAME_INSTALLATION.md) now provides attachment, full-selection composition, closed-client checks and the shared client/server journal. File verification remains separate from connected gameplay and official launcher/updater coordination.
