from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from hermes_ultra.skill_lifecycle import (
    AuthorityProfile,
    CapabilityDescriptor,
    LifecycleState,
    Provenance,
    SkillCandidate,
)
from hermes_ultra.skill_supply_chain import (
    LocalSkillArchive,
    ManagedSkillInstaller,
    ManifestConflictError,
    PinnedArchiveFetcher,
    PinnedSkillSource,
    SkillArchiveInspector,
    SkillFile,
    SkillManifestEditor,
    SkillSupplyChainError,
    hash_skill_files,
)


def _source(**overrides) -> PinnedSkillSource:
    values = {
        "repository": "https://github.com/example/skills",
        "commit_sha": "a" * 40,
        "tree_sha": "b" * 40,
        "skill_path": "skills/demo",
        "license": "MIT",
        "discovered_from": "skill-manager",
    }
    values.update(overrides)
    return PinnedSkillSource(**values)


def _candidate(*, state: LifecycleState = LifecycleState.TRUSTED, **overrides) -> SkillCandidate:
    source = _source()
    values = {
        "candidate_id": "cand_demo",
        "name": "demo",
        "provenance": Provenance(
            repository=source.repository_url,
            commit_sha=source.commit_sha,
            license=source.license,
            discovered_from=source.discovered_from,
        ),
        "authority": AuthorityProfile(filesystem_read=True),
        "capability": CapabilityDescriptor(
            capability_id="demo",
            capabilities=frozenset({"coding"}),
            tools=frozenset({"files"}),
            outputs=frozenset({"report"}),
        ),
        "state": state,
    }
    values.update(overrides)
    return SkillCandidate(**values)


def _tarball(entries: list[tuple[str, bytes, int, str]]) -> bytes:
    """Build a GitHub-like tar.gz.

    Entry tuple: (path, bytes, mode, kind) where kind is file/dir/symlink/hardlink.
    """

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        for path, body, mode, kind in entries:
            info = tarfile.TarInfo(path)
            info.mode = mode
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                info.size = 0
                archive.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                info.size = 0
                archive.addfile(info)
            elif kind == "hardlink":
                info.type = tarfile.LNKTYPE
                info.linkname = "repo-deadbeef/README.md"
                info.size = 0
                archive.addfile(info)
            else:
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
    return raw.getvalue()


def _valid_tarball(*, reverse: bool = False) -> bytes:
    entries = [
        ("skills-aaaaaaaa/skills/demo/SKILL.md", b"---\nname: demo\n---\nRun safely.\n", 0o644, "file"),
        ("skills-aaaaaaaa/skills/demo/scripts/run.py", b"print('ok')\n", 0o755, "file"),
        ("skills-aaaaaaaa/README.md", b"repo docs\n", 0o644, "file"),
    ]
    if reverse:
        entries.reverse()
    return _tarball(entries)


def _artifact():
    return SkillArchiveInspector(clock=lambda: "2026-08-30T18:00:00Z").inspect(
        _source(), _valid_tarball()
    )


def test_pinned_source_normalizes_repo_and_builds_commit_only_codeload_url() -> None:
    source = _source(repository="example/skills")

    assert source.repository_url == "https://github.com/example/skills"
    assert source.codeload_url() == (
        "https://codeload.github.com/example/skills/tar.gz/" + "a" * 40
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit_sha", "HEAD"),
        ("commit_sha", "abc123"),
        ("tree_sha", "main"),
        ("tree_sha", "b" * 39),
        ("skill_path", ""),
        ("skill_path", "../escape"),
        ("skill_path", "/absolute"),
        ("skill_path", "skills\\demo"),
    ],
)
def test_pinned_source_rejects_mutable_or_unsafe_identity(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        _source(**{field: value})


def test_pinned_archive_fetcher_uses_only_commit_pinned_url() -> None:
    calls: list[tuple[str, int]] = []

    def fetch(url: str, max_bytes: int) -> bytes:
        calls.append((url, max_bytes))
        if "/git/commits/" in url:
            return json.dumps({"tree": {"sha": "b" * 40}}).encode("utf-8")
        return b"archive"

    source = _source()
    data = PinnedArchiveFetcher(fetcher=fetch, max_archive_bytes=1024).fetch(source)

    assert data == b"archive"
    assert calls == [(source.commit_api_url(), 1024 * 1024), (source.codeload_url(), 1024)]
    assert all("HEAD" not in url for url, _ in calls)


def test_archive_inspector_extracts_only_selected_skill_and_records_hashes() -> None:
    artifact = _artifact()

    assert [item.relative_path for item in artifact.files] == ["SKILL.md", "scripts/run.py"]
    assert artifact.files[1].mode == 0o755
    assert artifact.manifest.archive_sha256 == hashlib.sha256(_valid_tarball()).hexdigest()
    assert len(artifact.manifest.skill_dir_sha256) == 64
    assert artifact.manifest.manifest_sha256 == hashlib.sha256(
        b"---\nname: demo\n---\nRun safely.\n"
    ).hexdigest()
    assert artifact.manifest.commit_sha == "a" * 40
    assert artifact.manifest.tree_sha == "b" * 40
    assert artifact.manifest.staged_at == "2026-08-30T18:00:00Z"


def test_skill_directory_hash_is_stable_independent_of_archive_order() -> None:
    inspector = SkillArchiveInspector(clock=lambda: "2026-08-30T18:00:00Z")
    first = inspector.inspect(_source(), _valid_tarball())
    second = inspector.inspect(_source(), _valid_tarball(reverse=True))

    assert first.manifest.skill_dir_sha256 == second.manifest.skill_dir_sha256
    assert hash_skill_files(first.files) == hash_skill_files(second.files)


@pytest.mark.parametrize(
    "entries",
    [
        [("repo-root/skills/demo/../../escape.sh", b"x", 0o644, "file")],
        [("/repo-root/skills/demo/SKILL.md", b"x", 0o644, "file")],
        [("repo-root/skills/demo/link", b"", 0o777, "symlink")],
        [("repo-root/skills/demo/link", b"", 0o777, "hardlink")],
    ],
)
def test_archive_inspector_rejects_unsafe_or_link_entries(entries) -> None:
    archive = _tarball(entries)

    with pytest.raises(SkillSupplyChainError):
        SkillArchiveInspector().inspect(_source(), archive)


def test_archive_inspector_requires_skill_manifest() -> None:
    archive = _tarball(
        [("repo-root/skills/demo/scripts/run.py", b"print('x')\n", 0o644, "file")]
    )

    with pytest.raises(SkillSupplyChainError, match="SKILL.md"):
        SkillArchiveInspector().inspect(_source(), archive)


def test_archive_inspector_enforces_archive_and_file_count_caps() -> None:
    archive = _valid_tarball()
    with pytest.raises(SkillSupplyChainError, match="archive byte cap"):
        SkillArchiveInspector(max_archive_bytes=8).inspect(_source(), archive)

    with pytest.raises(SkillSupplyChainError, match="file count cap"):
        SkillArchiveInspector(max_files=1).inspect(_source(), archive)


def test_managed_installer_requires_trusted_state_review_and_exact_managed_root(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    installer = ManagedSkillInstaller(
        {"coding": [root]},
        receipt_dir=tmp_path / "receipts",
        clock=lambda: "2026-08-30T19:00:00Z",
    )
    artifact = _artifact()

    with pytest.raises(PermissionError, match="trusted"):
        installer.install(
            _candidate(state=LifecycleState.CANDIDATE),
            artifact,
            profile="coding",
            target_root=root,
            review_approved=True,
            authorized_by="owner",
        )

    with pytest.raises(PermissionError, match="review approval"):
        installer.install(
            _candidate(),
            artifact,
            profile="coding",
            target_root=root,
            review_approved=False,
            authorized_by="owner",
        )

    with pytest.raises(SkillSupplyChainError, match="managed root"):
        installer.install(
            _candidate(provenance=Provenance(repository=artifact.source.repository_url, commit_sha=artifact.source.commit_sha, license=artifact.source.license, discovered_from=artifact.source.discovered_from, skill_path=artifact.manifest.skill_path, artifact_sha256=artifact.manifest.identity_hash())),
            artifact,
            profile="coding",
            target_root=tmp_path / "other",
            review_approved=True,
            authorized_by="owner",
        )


def test_managed_installer_rejects_provenance_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    installer = ManagedSkillInstaller({"coding": [root]}, receipt_dir=tmp_path / "receipts")
    artifact = _artifact()
    bad = _candidate(
        provenance=Provenance(
            repository="https://github.com/example/skills",
            commit_sha="c" * 40,
            license="MIT",
            discovered_from="skill-manager",
        )
    )

    with pytest.raises(SkillSupplyChainError, match="provenance"):
        installer.install(
            bad,
            artifact,
            profile="coding",
            target_root=root,
            review_approved=True,
            authorized_by="owner",
        )


def test_managed_installer_is_atomic_create_only_and_writes_attested_receipt(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    receipts = tmp_path / "receipts"
    installer = ManagedSkillInstaller(
        {"coding": [root]},
        receipt_dir=receipts,
        clock=lambda: "2026-08-30T19:00:00Z",
    )
    artifact = _artifact()
    candidate = _candidate(provenance=Provenance(repository=artifact.source.repository_url, commit_sha=artifact.source.commit_sha, license=artifact.source.license, discovered_from=artifact.source.discovered_from, skill_path=artifact.manifest.skill_path, artifact_sha256=artifact.manifest.identity_hash()))

    installed = installer.install(
        candidate,
        artifact,
        profile="coding",
        target_root=root,
        review_approved=True,
        authorized_by="owner",
    )

    target = root / "demo"
    assert installed.path == target
    assert (target / "SKILL.md").read_bytes() == artifact.files[0].bytes
    provenance = json.loads((target / ".hermes-skill-provenance.json").read_text(encoding="utf-8"))
    assert provenance["commit_sha"] == "a" * 40
    assert provenance["tree_sha"] == "b" * 40
    assert provenance["skill_dir_sha256"] == artifact.manifest.skill_dir_sha256
    assert installed.receipt.verify()
    assert installed.receipt.authorized_by == "owner"
    assert installed.receipt.profile == "coding"
    assert (receipts / f"{installed.receipt.receipt_hash}.json").is_file()

    with pytest.raises(SkillSupplyChainError, match="already exists"):
        installer.install(
            candidate,
            artifact,
            profile="coding",
            target_root=root,
            review_approved=True,
            authorized_by="owner",
        )


def test_local_archive_moves_and_restores_without_irreversible_delete(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    skill = root / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("demo\n", encoding="utf-8")
    archive = LocalSkillArchive(
        tmp_path / "archive",
        managed_roots=[root],
        clock=lambda: "2026-08-30T20:00:00Z",
    )

    archived = archive.archive(skill, reason="replace candidate")
    assert not skill.exists()
    assert archived.payload_path.is_dir()
    restored = archive.restore(archived.archive_id, root)

    assert restored == skill
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "demo\n"


def test_local_archive_detects_tampering_and_restore_collision(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    skill = root / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("demo\n", encoding="utf-8")
    archive = LocalSkillArchive(tmp_path / "archive", managed_roots=[root])
    archived = archive.archive(skill, reason="cleanup")

    (archived.payload_path / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(SkillSupplyChainError, match="hash"):
        archive.restore(archived.archive_id, root)

    # restore collision is checked independently with a fresh archive
    source = root / "other"
    source.mkdir()
    (source / "SKILL.md").write_text("other\n", encoding="utf-8")
    archived2 = archive.archive(source, reason="cleanup")
    collision = root / "other"
    collision.mkdir()
    with pytest.raises(SkillSupplyChainError, match="already exists"):
        archive.restore(archived2.archive_id, root)


def test_manifest_editor_uses_revision_hash_and_rejects_stale_writes(tmp_path: Path) -> None:
    manifest = tmp_path / "SKILL.md"
    manifest.write_text("version one\n", encoding="utf-8")
    editor = SkillManifestEditor()

    first = editor.read(manifest)
    second = editor.write(manifest, "version two\n", expected_sha256=first.sha256)
    assert second.content == "version two\n"
    assert second.sha256 != first.sha256

    with pytest.raises(ManifestConflictError, match="changed"):
        editor.write(manifest, "stale overwrite\n", expected_sha256=first.sha256)
    assert manifest.read_text(encoding="utf-8") == "version two\n"


def test_hash_skill_files_rejects_duplicate_paths() -> None:
    files = (
        SkillFile("SKILL.md", b"a", 0o644),
        SkillFile("SKILL.md", b"b", 0o644),
    )

    with pytest.raises(SkillSupplyChainError, match="duplicate"):
        hash_skill_files(files)
