# Quest staging and artifact ownership

Status: experimental preparation helpers, not a game installer. These validators do not run Docker, execute quests, change official files or establish build compatibility. The companion [isolated compiler helper](QUEST_COMPILATION.md) runs a fixed bounded recipe and passes only successful captured output through the same ownership checks. The [game coordinator](GAME_INSTALLATION.md) supplies reviewed input pins and complete baseline inventories for its one supported build pair.

The implementation is [installation/quests.py](../src/mt2sp_hub/installation/quests.py). Authors continue to use the [game-source starter](GAME_CREATORS.md); no installer scripts or new manifest fields are needed.

## Source preflight

`collect_quests(packages, official_names=...)` takes validated packages and the complete verified official quest-name set. It returns immutable source records with package ID, quest name, normalized source bytes and their SHA-256 digest. The coordinator still validates the selected dependency graph and client components separately.

The initial staging profile requires:

- A server component requesting only `server.quest`, with an API range accepting `1.0.0`.
- One `.quest` file directly under the logical target `PACKAGE_ID/quests/NAME.quest`.
- A declaration matching the filename, with the package ID's dots/hyphens converted to underscores followed by `_` as its prefix. Quest identifiers are at most 32 ASCII characters (the reviewed database namespace limit).
- Exactly one `quest NAME begin` declaration at the start, after comments/whitespace. Strings and Lua line/long comments cannot impersonate declarations. Quoted strings and long brackets must terminate.
- ASCII source with LF or CRLF line endings. CRLF is normalized for compilation, but limits count the original archive bytes. A different encoding requires a reviewed compiler profile.
- No name collision with official quests or another selected package, including case aliases. Prefix conversion alone is not unique: two distinct package IDs can produce the same quest prefix.

This is a small lexer and identity check, not a replacement quest parser. It deliberately rejects use of the reserved `quest` token outside the single declaration. Compiler validation is still mandatory; ordinary `build` remains archive validation and does not compile gameplay code.

The existing package limits also bound staging inputs: 128 selected packages, 2,048 quest sources, 16 MiB per source and 64 MiB total original source bytes. The full combined package selection must independently satisfy the core limits, including client files.

## Inspect each compiler output independently

`read_artifacts(quest, object_directory, occupied_paths=...)` reads one finished, isolated compiler `object/` directory. It returns deployment-relative paths and captured bytes. Store those exact bytes in the existing object store; do not later reread an unreviewed compiler directory for activation.

| Accepted path | Ownership/completeness rule |
| --- | --- |
| `object/state/QUEST` | Exactly the declared quest name; nonempty and required |
| `object/TARGET/EVENT/QUEST.STATE` | A nonempty handler belonging to that quest |
| `object/TARGET/EVENT/QUEST.STATE.N.arg` | Dialog label; must accompany `.when` and `.script` |
| `object/TARGET/EVENT/QUEST.STATE.N.when` | Dialog condition; may be empty for an unconditional choice |
| `object/TARGET/EVENT/QUEST.STATE.N.script` | Nonempty dialog body; must accompany `.arg` and `.when` |

Targets/events use bounded ASCII identifiers or numbers. A complete state file and at least one handler are required. Other paths, foreign quest prefixes, incomplete dialog groups, unused directories, links/reparse points, special files, excessive nesting and case/parent-path collisions are rejected. A bare handler whose state happens to be named `when` cannot use the empty-condition exception.

The reader applies the existing 2,048-file, 16 MiB/file and 64 MiB total limits, plus a bounded directory-entry count. It compares file identity, size and modification time before/after capture. Staging must belong exclusively to the operation, and the compiler must have finished; these checks do not claim atomic snapshots against a malicious concurrent writer.

`occupied_paths` must include the official baseline and already prepared add-ons. A collision is refused, never overwritten. Updating an existing owned quest will require the coordinator to distinguish its reviewed previous artifacts from unrelated resources before composing the next generation. This helper does not implement that update policy or authorization.

## Evidence and remaining integration

Synthetic tests cover misleading comments/strings, duplicate declarations, identity/capability/API checks, normalized-source limits, official/selected collisions, handler layouts, empty conditions, incomplete output, links, drift and bounded reads.

A local isolated compiler experiment compiled an original login greeting and another original quest containing login, conditional/unconditional NPC dialogs and a timer. The ownership reader accepted their 11 artifacts in separate staging directories and rejected reuse of their already occupied paths. Compiler/function-list inputs were mounted read-only, with no network or world-data mounts. Only original generated outputs were retained locally. No game-derived compiler inputs, private paths or build fingerprints are published.

The [compiler implementation and native evidence](QUEST_COMPILATION.md) now cover fixed execution, input pins, resource/time limits, captured artifacts, preparation receipts and temporary-container cleanup. The remaining adapter work is to identify a finite supported compiler/input combination, enumerate authoritative official quest names/artifacts, coordinate the full selection and prove the running deployment revision. Source identity checks, a successful exit code and filename ownership are necessary checks, not proof that arbitrary quest behavior is harmless.

Keep the existing server running through preflight and compilation. Only a reviewed, recoverable operation may replace artifacts or restart it. The [integration decision](MINIMAL_GAME_INTEGRATION.md) and [U04/U06 developer requests](METIN2SP_INTEGRATION_PROPOSAL.md#u04-server-extension-entry-points) describe the required include, build and status boundaries.
