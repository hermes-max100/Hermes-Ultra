# Hermes Ultra Skill Supply Chain

Hermes Ultra treats skill catalogs, desktop skill managers, MCP directories, and curated lists as **discovery surfaces only**. They can propose a candidate. They cannot establish trust, install files, activate a capability, or grant runtime authority.

This layer incorporates the useful mechanics identified in Skill Manager v0.4.2—managed roots, safe archive handling, provenance, and cross-agent skill inventory—while preserving Hermes Ultra's stricter lifecycle and evidence model.

## Trust boundary

The lifecycle authority remains:

`discovered -> quarantined -> candidate -> trusted -> installed_disabled -> canary -> active`

The supply-chain module operates between discovery and installation:

1. Scout or another discovery source proposes repository coordinates.
2. Hermes resolves and records a **full Git commit SHA** and **full tree SHA**.
3. `PinnedArchiveFetcher` constructs a GitHub codeload URL from the commit SHA only. `HEAD`, branch names, short SHAs, and mutable tags are not accepted as artifact identity.
4. `SkillArchiveInspector` reads the downloaded tarball without extracting it directly to a managed root.
5. The selected skill is materialized as an in-memory `QuarantinedSkillArtifact` with deterministic hashes.
6. Existing structural/content validation and evaluation gates run while the artifact remains non-installed.
7. Only a candidate already promoted to `trusted`, with review approval, may pass to `ManagedSkillInstaller`.
8. Installation writes into an exact configured profile root and remains disabled until the separate lifecycle transition to `installed_disabled`.
9. Canary and activation remain separate decisions governed by `LifecycleController`.

## Immutable source identity

`PinnedSkillSource` requires:

- canonical GitHub repository identity;
- 40-character commit SHA;
- 40-character tree SHA;
- canonical skill subpath;
- declared license; and
- discovery source.

Mutable coordinates such as `HEAD`, `main`, `master`, or a short commit prefix are rejected before network retrieval.

A staged artifact records:

- repository URL;
- commit SHA;
- tree SHA;
- skill path;
- license;
- discovery source;
- SHA-256 of the downloaded archive;
- deterministic SHA-256 of the selected skill directory;
- SHA-256 of `SKILL.md`; and
- staging timestamp.

The install receipt adds the candidate ID, profile, exact managed root, exact target path, authorizer, and installation timestamp. Receipt hashes use canonical JSON and are persisted create-only.

## Archive safety

`SkillArchiveInspector` never calls `tarfile.extract()`.

It iterates archive entries and rejects:

- absolute paths;
- `.` or `..` path components;
- backslash paths and Windows drive-style components;
- symlinks;
- hardlinks;
- device/FIFO/special entries;
- archives exceeding the compressed-size cap;
- individual files exceeding the file-size cap;
- archives exceeding the declared uncompressed-size cap;
- archives exceeding the file-count cap; and
- selected skill folders without exactly one root `SKILL.md`.

Only regular files beneath the declared skill subpath are copied into the quarantined artifact. File permission bits are restricted to `0o777`; setuid/setgid/sticky bits are not preserved.

## Deterministic skill hashing

`hash_skill_files()` sorts files by canonical relative path and hashes path, permission mode, byte length, and SHA-256 of file contents. Archive ordering therefore cannot change the skill-directory identity.

The installer re-hashes the files after writing them to its temporary directory. A mismatch aborts installation.

## Managed-root installation

`ManagedSkillInstaller` is initialized with a map of profile names to managed skill roots. A requested target must resolve to an **exact configured root for that profile**.

Installation fails closed unless:

- the candidate state is `trusted`;
- review approval is present;
- `authorized_by` is non-empty;
- candidate provenance matches the staged artifact repository, commit, license, and discovery source;
- staged directory and `SKILL.md` hashes verify;
- the target root belongs to the selected profile; and
- the target skill directory does not already exist.

The installer writes to a temporary sibling directory, verifies the written content, adds `.hermes-skill-provenance.json`, atomically renames the directory into place, and persists a create-only install receipt. If receipt persistence fails, the newly installed directory is removed so Hermes does not leave an unattested installation behind.

Installation does **not** activate the skill. The existing lifecycle still requires the `trusted -> installed_disabled -> canary -> active` sequence.

## Recoverable removal

`LocalSkillArchive` provides a local archive/restore path instead of irreversible deletion.

Before moving a managed skill, Hermes computes a deterministic tree hash and writes archive metadata keyed by a canonical SHA-256 archive ID. Restore verifies both metadata identity and payload hash, refuses collisions, and restores only into an exact configured managed root.

This is intentionally local. It is not a cloud backup or synchronization mechanism.

## Concurrent editing

`SkillManifestEditor` returns a SHA-256 revision token when reading `SKILL.md`. A write must provide that exact expected revision. If another editor, agent, Git operation, or tool changed the file in the meantime, the write is rejected with `ManifestConflictError` instead of silently overwriting newer work.

Successful writes use a temporary file, `fsync`, permission preservation, and atomic replacement.

## Discovery sources

The default discovery registry now also includes:

- `skill-manager` -> `https://github.com/abubakarsiddik31/skill-manager`
- `all-mcp-servers` -> `https://www.allmcpservers.com/`

Both are `discovery_only=true` and `auto_install=false`.

The Official MCP Registry and vendor repositories remain provenance/reference authorities where applicable. A catalog listing is never equivalent to vendor provenance or Hermes trust promotion.

## Operational rule

A skill may be:

- **discoverable without being trusted**;
- **trusted without being installed**;
- **installed without being enabled**; and
- **enabled for one profile without being authorized for another**.

Those distinctions are deliberate. Skill quality, source identity, installation state, profile visibility, and consequential authority are separate control planes.
