# Public information and privacy

The public Hub repository contains original platform source, documentation, schemas and synthetic tests. Personal installations and development evidence remain local. These rules apply to commits, pull requests, issues, workflow logs and release artifacts, including draft pull requests on this public repository.

## Publication boundary

| Suitable for public review | Keep private or local |
| --- | --- |
| Original source with appropriate notices | Credentials, service/session tokens, pack keys and private certificates |
| Invented fixture IDs and example configuration | Account/character data, inventories, database dumps and world saves |
| Repository-relative paths and neutral placeholders | Usernames embedded in absolute paths, device names and installation IDs |
| Public upstream documentation links | Personal email, private contact information and private repository URLs |
| Reviewed aggregate compatibility results | Raw logs, crash dumps, screenshots, native traces and full support archives |
| Dependency names, versions and licenses | Game executables, packs, copied clients and extracted game assets |
| Public GitHub handles and GitHub noreply commit identities | Private author/committer addresses or signed-off-by metadata |

Do not copy source application history or entire working directories into this repository. Select files individually and review source comments, test fixtures, generated metadata and embedded URLs. Repository-relative paths are preferred; examples use neutral names such as `SERVER_ROOT`, `CLIENT_ROOT` and `STATE_DIR`.

The root ignore file reduces accidental additions. It cannot remove files already tracked, inspect Git history, redact a screenshot or decide whether an artifact is safe to publish.

## Before every public change

1. Inspect the exact tracked/staged diff and new file list. Use explicit staging paths; avoid adding a whole working directory blindly.
2. Check content for local paths, personal identifiers, credentials, private URLs and game-derived material. Review findings rather than relying only on a pattern scanner.
3. Inspect the complete outgoing commit range, including author, committer, messages, trailers and deleted files. Use an already approved public handle and GitHub noreply address; set identity locally rather than changing global Git preferences.
4. Verify that code/docs can be understood without private paths or a private repository. Synthetic fixtures must be created from invented data, not lightly redacted user dumps.
5. Inspect the PR title/body and attachments as part of the publication. A draft PR is still public.

When a necessary source notice contains an author's identity, preserve the required notice and resolve publication rights explicitly. Do not silently strip attribution to satisfy a privacy scan.

## Build and release boundary

Create source/release artifacts from an explicit allowlist and inspect their extracted contents. Exclude working state, dependency caches, logs, backups, screenshots, game files and test outputs. Do not archive the repository's parent folder or publish a developer's installed environment.

Use synthetic data in public CI. Local tests that need a legitimate game installation produce local detailed evidence; public reports contain reviewed totals, tested public build identifiers and limitations. Workflow logs must not print environment dumps, raw process arguments containing secrets or full state records.

Pin and review CI dependencies when implementation begins. Pull-request validation must not receive release credentials. Any future publishing credential gets the minimum permissions needed for its job. Secret scanning complements the file/metadata review; it does not replace it.

## Runtime privacy

No telemetry or support upload is part of the initial Hub design. Source checks/downloads contact only the selected providers and do not transmit world data. A future support export must use a field allowlist and a preview before sharing.

Useful diagnostic fields include Hub version, public game build identifiers, adapter/API versions, operation stage, stable error codes and sanitized counts. Exclude raw paths, usernames, network addresses, settings values, free-form errors, source credentials and payload contents unless the user explicitly selects and reviews a separate attachment.

Keep server credentials in protected local configuration and out of client payloads, package manifests and release archives. Redact secrets at the logging boundary so they do not enter downstream reports in the first place.

## If private information is published

Stop further publication, identify the exposed material and notify the repository owner privately. Revoke/rotate exposed credentials before relying on deletion. Remove the material from current content and assess Git history, releases, logs and caches; a later deletion commit does not retract old public copies.

Coordinate any history rewrite with the owner and affected collaborators. Describe the incident publicly only to the extent needed, without repeating the private data. Do not add an issue containing the original secret or personal identifier as evidence.
