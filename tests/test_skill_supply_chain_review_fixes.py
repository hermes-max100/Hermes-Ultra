from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import threading
from pathlib import Path

import pytest

import hermes_ultra.skill_supply_chain as supply_chain
from hermes_ultra.skill_lifecycle import (
    AuthorityProfile,
    CapabilityDescriptor,
    LifecycleState,
    Provenance,
    SkillCandidate,
)
from hermes_ultra.skill_supply_chain import (
    ManagedSkillInstaller,
    PinnedArchiveFetcher,
    PinnedSkillSource,
    SkillArchiveInspector,
    SkillManifestEditor,
    SkillSupplyChainError,
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


def _tarball(entries: list[tuple[str, bytes, int, str]]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        for path, body, mode, kind in entries:
            info = tarfile.TarInfo(path)
            info.mode = mode
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                info.size = 0
                archive.addfile(info)
            else:
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
    return raw.getvalue()


def _skill_tarball(source: PinnedSkillSource) -> bytes:
    prefix = "skills-aaaaaaaa/" + source.skill_path
    return _tarball(
        [
            (prefix + "/SKILL.md", b"---\nname: demo\n---\nRun safely.\n", 0o644, "file"),
            (prefix + "/scripts/run.py", b"print('ok')\n", 0o755, "file"),
        ]
    )


def _artifact(source: PinnedSkillSource | None = None):
    source = source or _source()
    return SkillArchiveInspector(clock=lambda: "2026-08-30T18:00:00Z").inspect(
        source, _skill_tarball(source)
    )


def _artifact_identity(artifact) -> str:
    payload = artifact.manifest.to_dict()
    payload.pop("staged_at", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bound_candidate(artifact, *, candidate_id: str = "cand_demo") -> SkillCandidate:
    source = artifact.source
    provenance = Provenance(
        repository=source.repository_url,
        commit_sha=source.commit_sha,
        license=source.license,
        discovered_from=source.discovered_from,
    )
    # These attributes define the desired trusted-artifact binding. They are set
    # dynamically so this regression suite reproduces the old behavior before
    # Provenance grows the corresponding typed fields.
    object.__setattr__(provenance, "skill_path", artifact.manifest.skill_path)
    object.__setattr__(provenance, "artifact_sha256", _artifact_identity(artifact))
    return SkillCandidate(
        candidate_id=candidate_id,
        name="demo",
        provenance=provenance,
        authority=AuthorityProfile(filesystem_read=True),
        capability=CapabilityDescriptor(
            capability_id="demo",
            capabilities=frozenset({"coding"}),
            tools=frozenset({"files"}),
            outputs=frozenset({"report"}),
        ),
        state=LifecycleState.TRUSTED,
    )


def _installer(tmp_path: Path, *, clock=lambda: "2026-08-30T19:00:00Z"):
    root = tmp_path / "skills"
    return root, ManagedSkillInstaller(
        {"coding": [root]},
        receipt_dir=tmp_path / "receipts",
        clock=clock,
    )


def test_fetcher_verifies_commit_tree_before_downloading_archive() -> None:
    source = _source()
    calls: list[str] = []

    def fetch(url: str, max_bytes: int) -> bytes:
        calls.append(url)
        if "/git/commits/" in url:
            return json.dumps({"tree": {"sha": source.tree_sha}}).encode("utf-8")
        return b"archive"

    data = PinnedArchiveFetcher(fetcher=fetch, max_archive_bytes=1024).fetch(source)

    assert data == b"archive"
    assert calls == [
        "https://api.github.com/repos/example/skills/git/commits/" + source.commit_sha,
        source.codeload_url(),
    ]


def test_fetcher_rejects_tree_sha_mismatch_before_archive_download() -> None:
    source = _source()
    calls: list[str] = []

    def fetch(url: str, max_bytes: int) -> bytes:
        calls.append(url)
        if "/git/commits/" in url:
            return json.dumps({"tree": {"sha": "c" * 40}}).encode("utf-8")
        return b"archive"

    with pytest.raises(SkillSupplyChainError, match="tree SHA"):
        PinnedArchiveFetcher(fetcher=fetch, max_archive_bytes=1024).fetch(source)
    assert calls == [
        "https://api.github.com/repos/example/skills/git/commits/" + source.commit_sha
    ]


def test_archive_limit_counts_directory_headers_too() -> None:
    source = _source()
    archive = _tarball(
        [
            ("skills-aaaaaaaa/skills", b"", 0o755, "dir"),
            ("skills-aaaaaaaa/skills/demo", b"", 0o755, "dir"),
            ("skills-aaaaaaaa/skills/demo/SKILL.md", b"demo\n", 0o644, "file"),
        ]
    )

    with pytest.raises(SkillSupplyChainError, match="entry count cap"):
        SkillArchiveInspector(max_files=2).inspect(source, archive)


def test_trusted_candidate_is_bound_to_exact_selected_artifact(tmp_path: Path) -> None:
    approved = _artifact(_source(skill_path="skills/demo"))
    candidate = _bound_candidate(approved)
    different = _artifact(_source(skill_path="skills/other"))
    root, installer = _installer(tmp_path)

    with pytest.raises(SkillSupplyChainError, match="artifact binding"):
        installer.install(
            candidate,
            different,
            profile="coding",
            target_root=root,
            review_approved=True,
            authorized_by="owner",
        )


def test_create_only_target_cannot_be_replaced_by_rename_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    candidate = _bound_candidate(artifact)
    root, installer = _installer(tmp_path)
    original = supply_chain._files_from_directory
    injected = False

    def race(base, expected=None):
        nonlocal injected
        result = original(base, expected)
        if not injected:
            injected = True
            collision = root / "demo"
            collision.mkdir(parents=True)
        return result

    monkeypatch.setattr(supply_chain, "_files_from_directory", race)

    with pytest.raises(SkillSupplyChainError, match="already exists"):
        installer.install(
            candidate,
            artifact,
            profile="coding",
            target_root=root,
            review_approved=True,
            authorized_by="owner",
        )

    assert (root / "demo").is_dir()
    assert list((root / "demo").iterdir()) == []


def test_managed_root_is_pinned_against_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    candidate = _bound_candidate(artifact)
    root, installer = _installer(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    original = installer._managed_root

    def race(profile, target_root):
        normalized = original(profile, target_root)
        if normalized.exists() and not normalized.is_symlink():
            shutil.rmtree(normalized)
        normalized.symlink_to(outside, target_is_directory=True)
        return normalized

    monkeypatch.setattr(installer, "_managed_root", race)

    with pytest.raises(SkillSupplyChainError, match="managed root"):
        installer.install(
            candidate,
            artifact,
            profile="coding",
            target_root=root,
            review_approved=True,
            authorized_by="owner",
        )
    assert not (outside / "demo").exists()


def test_receipt_collision_never_deletes_existing_immutable_receipt(tmp_path: Path) -> None:
    artifact = _artifact()
    candidate = _bound_candidate(artifact)
    root, installer = _installer(tmp_path)

    first = installer.install(
        candidate,
        artifact,
        profile="coding",
        target_root=root,
        review_approved=True,
        authorized_by="owner",
    )
    receipt_path = tmp_path / "receipts" / f"{first.receipt.receipt_hash}.json"
    before = receipt_path.read_bytes()
    shutil.rmtree(root / "demo")

    with pytest.raises(FileExistsError):
        installer.install(
            candidate,
            artifact,
            profile="coding",
            target_root=root,
            review_approved=True,
            authorized_by="owner",
        )

    assert receipt_path.read_bytes() == before


def test_manifest_editor_holds_cooperative_lock_across_compare_and_swap(
    tmp_path: Path,
) -> None:
    fcntl = pytest.importorskip("fcntl")
    manifest = tmp_path / "SKILL.md"
    manifest.write_text("version one\n", encoding="utf-8")
    editor = SkillManifestEditor()
    snapshot = editor.read(manifest)
    lock_path = manifest.parent / ".SKILL.md.hermes.lock"
    lock_handle = lock_path.open("a+b")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)

    finished = threading.Event()
    failure: list[BaseException] = []

    def writer() -> None:
        try:
            editor.write(
                manifest,
                "version two\n",
                expected_sha256=snapshot.sha256,
            )
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            failure.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        assert not finished.wait(0.2), "write ignored cooperative manifest lock"
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()
    thread.join(timeout=2)

    assert finished.is_set()
    assert failure == []
    assert manifest.read_text(encoding="utf-8") == "version two\n"
