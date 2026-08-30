from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse

from .skill_lifecycle import LifecycleState, SkillCandidate

_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SLUG_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class SkillSupplyChainError(RuntimeError):
    """A fail-closed supply-chain validation or filesystem error."""


class ManifestConflictError(SkillSupplyChainError):
    """Raised when SKILL.md changed after it was read."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _canonical_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _safe_relative_path(value: str, *, field: str = "path") -> str:
    if not value or value.startswith("/") or "\\" in value:
        raise ValueError(f"{field} must be a non-empty relative POSIX path")
    path = PurePosixPath(value)
    parts = path.parts
    if not parts or any(
        part in {"", ".", ".."} or ":" in part
        for part in parts
    ):
        raise ValueError(f"{field} contains an unsafe path component")
    normalized = path.as_posix()
    if normalized != value.rstrip("/") or value.endswith("/"):
        raise ValueError(f"{field} must be canonical")
    return normalized


def _safe_archive_path(value: str) -> tuple[str, ...]:
    if not value or value.startswith("/") or "\\" in value:
        raise SkillSupplyChainError(f"unsafe archive path: {value!r}")
    path = PurePosixPath(value)
    parts = path.parts
    if not parts or any(
        part in {"", ".", ".."} or ":" in part
        for part in parts
    ):
        raise SkillSupplyChainError(f"unsafe archive path: {value!r}")
    return parts


def _canonical_repository(repository: str) -> tuple[str, str, str]:
    raw = repository.strip().rstrip("/")
    if not raw:
        raise ValueError("repository is required")
    if raw.endswith(".git"):
        raw = raw[:-4]

    if raw.startswith("https://"):
        parsed = urlparse(raw)
        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
            raise ValueError(
                "repository must be a public github.com HTTPS URL or owner/repo slug"
            )
        if parsed.query or parsed.fragment or parsed.params:
            raise ValueError("repository URL must not contain query or fragment components")
        parts = tuple(part for part in parsed.path.split("/") if part)
        if len(parts) != 2:
            raise ValueError("repository URL must identify exactly owner/repo")
        owner, repo = parts
    elif "://" not in raw and raw.count("/") == 1:
        owner, repo = raw.split("/", 1)
    else:
        raise ValueError(
            "repository must be a public github.com HTTPS URL or owner/repo slug"
        )

    if (
        not _SLUG_PART_RE.fullmatch(owner)
        or not _SLUG_PART_RE.fullmatch(repo)
        or owner in {".", ".."}
        or repo in {".", ".."}
    ):
        raise ValueError("repository owner/repo slug is invalid")
    canonical = f"https://github.com/{owner}/{repo}"
    return owner, repo, canonical


@dataclass(frozen=True)
class PinnedSkillSource:
    repository: str
    commit_sha: str
    tree_sha: str
    skill_path: str
    license: str
    discovered_from: str

    def __post_init__(self) -> None:
        owner, repo, canonical = _canonical_repository(self.repository)
        if not _SHA40_RE.fullmatch(self.commit_sha):
            raise ValueError(
                "commit_sha must be a full 40-character hexadecimal SHA"
            )
        if not _SHA40_RE.fullmatch(self.tree_sha):
            raise ValueError("tree_sha must be a full 40-character hexadecimal SHA")
        safe_path = _safe_relative_path(self.skill_path, field="skill_path")
        if not self.license.strip():
            raise ValueError("license is required")
        if not self.discovered_from.strip():
            raise ValueError("discovered_from is required")
        object.__setattr__(self, "repository", canonical)
        object.__setattr__(self, "commit_sha", self.commit_sha.lower())
        object.__setattr__(self, "tree_sha", self.tree_sha.lower())
        object.__setattr__(self, "skill_path", safe_path)
        object.__setattr__(self, "license", self.license.strip())
        object.__setattr__(self, "discovered_from", self.discovered_from.strip())
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_repo", repo)

    @property
    def repository_url(self) -> str:
        return self.repository

    @property
    def owner(self) -> str:
        return getattr(self, "_owner")

    @property
    def repo(self) -> str:
        return getattr(self, "_repo")

    def codeload_url(self) -> str:
        return (
            f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/"
            f"{self.commit_sha}"
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "repository": self.repository_url,
            "commit_sha": self.commit_sha,
            "tree_sha": self.tree_sha,
            "skill_path": self.skill_path,
            "license": self.license,
            "discovered_from": self.discovered_from,
        }


FetchBytes = Callable[[str, int], bytes]


class PinnedArchiveFetcher:
    def __init__(
        self,
        *,
        fetcher: FetchBytes | None = None,
        max_archive_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if max_archive_bytes <= 0:
            raise ValueError("max_archive_bytes must be positive")
        self.max_archive_bytes = int(max_archive_bytes)
        self._fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str, max_bytes: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Hermes-Ultra/skill-supply-chain"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(max_bytes + 1)
        return data

    def fetch(self, source: PinnedSkillSource) -> bytes:
        data = self._fetcher(source.codeload_url(), self.max_archive_bytes)
        if len(data) > self.max_archive_bytes:
            raise SkillSupplyChainError("archive byte cap exceeded")
        return bytes(data)


@dataclass(frozen=True)
class SkillFile:
    relative_path: str
    bytes: bytes
    mode: int = 0o644

    def __post_init__(self) -> None:
        safe = _safe_relative_path(self.relative_path, field="relative_path")
        object.__setattr__(self, "relative_path", safe)
        object.__setattr__(self, "bytes", bytes(self.bytes))
        object.__setattr__(self, "mode", int(self.mode) & 0o777)


def hash_skill_files(files: Sequence[SkillFile]) -> str:
    seen: set[str] = set()
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda file: file.relative_path):
        if item.relative_path in seen:
            raise SkillSupplyChainError(
                f"duplicate skill path: {item.relative_path}"
            )
        seen.add(item.relative_path)
        path_bytes = item.relative_path.encode("utf-8")
        body_hash = hashlib.sha256(item.bytes).digest()
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(item.mode.to_bytes(4, "big"))
        digest.update(len(item.bytes).to_bytes(8, "big"))
        digest.update(body_hash)
    if not seen:
        raise SkillSupplyChainError("skill artifact contains no files")
    return digest.hexdigest()


@dataclass(frozen=True)
class SkillArtifactManifest:
    repository: str
    commit_sha: str
    tree_sha: str
    skill_path: str
    license: str
    discovered_from: str
    archive_sha256: str
    skill_dir_sha256: str
    manifest_sha256: str
    staged_at: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class QuarantinedSkillArtifact:
    source: PinnedSkillSource
    files: tuple[SkillFile, ...]
    manifest: SkillArtifactManifest


class SkillArchiveInspector:
    def __init__(
        self,
        *,
        max_archive_bytes: int = 64 * 1024 * 1024,
        max_uncompressed_bytes: int = 128 * 1024 * 1024,
        max_file_bytes: int = 16 * 1024 * 1024,
        max_files: int = 4096,
        clock: Callable[[], str] | None = None,
    ) -> None:
        limits = (
            max_archive_bytes,
            max_uncompressed_bytes,
            max_file_bytes,
            max_files,
        )
        if any(int(value) <= 0 for value in limits):
            raise ValueError("archive limits must be positive")
        self.max_archive_bytes = int(max_archive_bytes)
        self.max_uncompressed_bytes = int(max_uncompressed_bytes)
        self.max_file_bytes = int(max_file_bytes)
        self.max_files = int(max_files)
        self._clock = clock or _utc_now

    def inspect(
        self,
        source: PinnedSkillSource,
        archive_bytes: bytes,
    ) -> QuarantinedSkillArtifact:
        archive_bytes = bytes(archive_bytes)
        if len(archive_bytes) > self.max_archive_bytes:
            raise SkillSupplyChainError("archive byte cap exceeded")

        files: list[SkillFile] = []
        regular_count = 0
        declared_bytes = 0
        prefix = source.skill_path + "/"
        try:
            with tarfile.open(
                fileobj=io.BytesIO(archive_bytes),
                mode="r:gz",
            ) as archive:
                for member in archive:
                    parts = _safe_archive_path(member.name)
                    if member.isdir():
                        continue
                    if not member.isreg():
                        raise SkillSupplyChainError(
                            "archive contains unsupported non-regular entry: "
                            f"{member.name}"
                        )
                    regular_count += 1
                    if regular_count > self.max_files:
                        raise SkillSupplyChainError("file count cap exceeded")
                    if member.size < 0 or member.size > self.max_file_bytes:
                        raise SkillSupplyChainError(
                            f"file byte cap exceeded: {member.name}"
                        )
                    declared_bytes += int(member.size)
                    if declared_bytes > self.max_uncompressed_bytes:
                        raise SkillSupplyChainError(
                            "uncompressed byte cap exceeded"
                        )
                    if len(parts) < 2:
                        continue
                    repo_relative = "/".join(parts[1:])
                    if not repo_relative.startswith(prefix):
                        continue
                    relative = repo_relative[len(prefix) :]
                    if not relative:
                        continue
                    try:
                        _safe_relative_path(
                            relative,
                            field="archive member",
                        )
                    except ValueError as exc:
                        raise SkillSupplyChainError(str(exc)) from exc
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise SkillSupplyChainError(
                            f"cannot read archive member: {member.name}"
                        )
                    body = extracted.read(self.max_file_bytes + 1)
                    if len(body) > self.max_file_bytes or len(body) != member.size:
                        raise SkillSupplyChainError(
                            f"archive member size mismatch: {member.name}"
                        )
                    files.append(
                        SkillFile(
                            relative,
                            body,
                            member.mode & 0o777,
                        )
                    )
        except SkillSupplyChainError:
            raise
        except (tarfile.TarError, OSError, EOFError) as exc:
            raise SkillSupplyChainError(
                f"invalid tar.gz archive: {exc}"
            ) from exc

        files.sort(key=lambda item: item.relative_path)
        manifests = [
            item
            for item in files
            if item.relative_path == "SKILL.md"
        ]
        if len(manifests) != 1:
            raise SkillSupplyChainError(
                "selected skill must contain exactly one root SKILL.md"
            )
        skill_hash = hash_skill_files(files)
        manifest_hash = hashlib.sha256(manifests[0].bytes).hexdigest()
        staged = SkillArtifactManifest(
            repository=source.repository_url,
            commit_sha=source.commit_sha,
            tree_sha=source.tree_sha,
            skill_path=source.skill_path,
            license=source.license,
            discovered_from=source.discovered_from,
            archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
            skill_dir_sha256=skill_hash,
            manifest_sha256=manifest_hash,
            staged_at=self._clock(),
        )
        return QuarantinedSkillArtifact(
            source=source,
            files=tuple(files),
            manifest=staged,
        )


def _validate_skill_name(name: str) -> str:
    if not _SKILL_NAME_RE.fullmatch(name) or name in {".", ".."}:
        raise SkillSupplyChainError(
            "candidate name is not a safe skill folder name"
        )
    return name


def _normalized_root(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _files_from_directory(
    base: Path,
    expected: Sequence[SkillFile] | None = None,
) -> tuple[SkillFile, ...]:
    if base.is_symlink() or not base.is_dir():
        raise SkillSupplyChainError(
            "skill directory must be a real directory"
        )
    paths: list[Path]
    if expected is None:
        paths = sorted(
            (
                path
                for path in base.rglob("*")
                if path.is_file() or path.is_symlink()
            ),
            key=lambda path: path.as_posix(),
        )
    else:
        paths = [base / item.relative_path for item in expected]
    files: list[SkillFile] = []
    for path in paths:
        if path.is_symlink():
            raise SkillSupplyChainError(
                f"symlink is not allowed in managed skill: {path}"
            )
        if not path.is_file():
            raise SkillSupplyChainError(
                f"expected regular file is missing: {path}"
            )
        rel = path.relative_to(base).as_posix()
        mode = path.stat().st_mode & 0o777
        files.append(SkillFile(rel, path.read_bytes(), mode))
    return tuple(files)


@dataclass(frozen=True)
class SkillInstallReceipt:
    candidate_id: str
    name: str
    profile: str
    target_root: str
    target_path: str
    authorized_by: str
    installed_at: str
    artifact: SkillArtifactManifest
    receipt_hash: str

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "profile": self.profile,
            "target_root": self.target_root,
            "target_path": self.target_path,
            "authorized_by": self.authorized_by,
            "installed_at": self.installed_at,
            "artifact": self.artifact.to_dict(),
        }

    def verify(self) -> bool:
        return _canonical_hash(self.unsigned_dict()) == self.receipt_hash

    def to_dict(self) -> dict[str, object]:
        return {
            **self.unsigned_dict(),
            "receipt_hash": self.receipt_hash,
        }


@dataclass(frozen=True)
class InstalledSkill:
    path: Path
    receipt: SkillInstallReceipt


class ManagedSkillInstaller:
    def __init__(
        self,
        managed_roots: Mapping[str, Sequence[str | Path]],
        *,
        receipt_dir: str | Path,
        clock: Callable[[], str] | None = None,
    ) -> None:
        roots: dict[str, tuple[Path, ...]] = {}
        for profile, values in managed_roots.items():
            if not profile.strip():
                raise ValueError("profile names must be non-empty")
            normalized = tuple(
                _normalized_root(value)
                for value in values
            )
            if not normalized:
                raise ValueError(
                    f"profile {profile!r} must declare at least one managed root"
                )
            roots[profile] = normalized
        if not roots:
            raise ValueError("at least one managed profile is required")
        self.managed_roots = roots
        self.receipt_dir = Path(receipt_dir)
        self._clock = clock or _utc_now

    @staticmethod
    def _provenance_matches(
        candidate: SkillCandidate,
        source: PinnedSkillSource,
    ) -> bool:
        try:
            _, _, candidate_repo = _canonical_repository(
                candidate.provenance.repository
            )
        except ValueError:
            return False
        return (
            candidate_repo == source.repository_url
            and candidate.provenance.commit_sha.lower() == source.commit_sha
            and candidate.provenance.license.strip() == source.license
            and candidate.provenance.discovered_from.strip()
            == source.discovered_from
        )

    def _managed_root(
        self,
        profile: str,
        target_root: str | Path,
    ) -> Path:
        if profile not in self.managed_roots:
            raise SkillSupplyChainError(
                f"unknown install profile: {profile}"
            )
        normalized = _normalized_root(target_root)
        if normalized not in self.managed_roots[profile]:
            raise SkillSupplyChainError(
                "target is not an exact managed root for this profile"
            )
        if Path(target_root).exists() and Path(target_root).is_symlink():
            raise SkillSupplyChainError(
                "managed root may not be a symlink"
            )
        return normalized

    def install(
        self,
        candidate: SkillCandidate,
        artifact: QuarantinedSkillArtifact,
        *,
        profile: str,
        target_root: str | Path,
        review_approved: bool,
        authorized_by: str,
    ) -> InstalledSkill:
        if candidate.state is not LifecycleState.TRUSTED:
            raise PermissionError(
                "candidate must be trusted before installation"
            )
        if not review_approved:
            raise PermissionError(
                "review approval is required before installation"
            )
        if not authorized_by.strip():
            raise PermissionError("authorized_by is required")
        if not self._provenance_matches(candidate, artifact.source):
            raise SkillSupplyChainError(
                "candidate provenance does not match staged artifact provenance"
            )

        if hash_skill_files(artifact.files) != artifact.manifest.skill_dir_sha256:
            raise SkillSupplyChainError(
                "staged skill directory hash verification failed"
            )
        manifest_file = next(
            (
                item
                for item in artifact.files
                if item.relative_path == "SKILL.md"
            ),
            None,
        )
        if (
            manifest_file is None
            or hashlib.sha256(manifest_file.bytes).hexdigest()
            != artifact.manifest.manifest_sha256
        ):
            raise SkillSupplyChainError(
                "staged SKILL.md hash verification failed"
            )

        root = self._managed_root(profile, target_root)
        name = _validate_skill_name(candidate.name)
        root.mkdir(parents=True, exist_ok=True)
        target = root / name
        if target.exists() or target.is_symlink():
            raise SkillSupplyChainError(
                f"skill target already exists: {target}"
            )

        tmp = Path(
            tempfile.mkdtemp(
                prefix=f".{name}.tmp-",
                dir=root,
            )
        )
        renamed = False
        receipt_path: Path | None = None
        try:
            for item in artifact.files:
                dest = tmp / item.relative_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("xb") as handle:
                    handle.write(item.bytes)
                os.chmod(dest, item.mode)

            written = _files_from_directory(tmp, artifact.files)
            if (
                hash_skill_files(written)
                != artifact.manifest.skill_dir_sha256
            ):
                raise SkillSupplyChainError(
                    "written skill content failed deterministic hash verification"
                )

            installed_at = self._clock()
            provenance_payload = {
                **artifact.manifest.to_dict(),
                "candidate_id": candidate.candidate_id,
                "name": candidate.name,
                "profile": profile,
                "authorized_by": authorized_by.strip(),
                "installed_at": installed_at,
            }
            provenance_path = tmp / ".hermes-skill-provenance.json"
            with provenance_path.open("x", encoding="utf-8") as handle:
                json.dump(
                    provenance_payload,
                    handle,
                    sort_keys=True,
                    indent=2,
                )
                handle.write("\n")

            os.replace(tmp, target)
            renamed = True
            unsigned = {
                "candidate_id": candidate.candidate_id,
                "name": candidate.name,
                "profile": profile,
                "target_root": str(root),
                "target_path": str(target),
                "authorized_by": authorized_by.strip(),
                "installed_at": installed_at,
                "artifact": artifact.manifest.to_dict(),
            }
            receipt = SkillInstallReceipt(
                candidate_id=candidate.candidate_id,
                name=candidate.name,
                profile=profile,
                target_root=str(root),
                target_path=str(target),
                authorized_by=authorized_by.strip(),
                installed_at=installed_at,
                artifact=artifact.manifest,
                receipt_hash=_canonical_hash(unsigned),
            )
            if not receipt.verify():
                raise SkillSupplyChainError(
                    "install receipt hash verification failed"
                )
            self.receipt_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = (
                self.receipt_dir
                / f"{receipt.receipt_hash}.json"
            )
            with receipt_path.open("x", encoding="utf-8") as handle:
                json.dump(
                    receipt.to_dict(),
                    handle,
                    sort_keys=True,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return InstalledSkill(path=target, receipt=receipt)
        except Exception:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            if receipt_path is not None and receipt_path.exists():
                receipt_path.unlink(missing_ok=True)
            if renamed and target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise


@dataclass(frozen=True)
class ArchivedSkill:
    archive_id: str
    name: str
    archived_at: str
    reason: str
    original_parent: str
    tree_sha256: str
    payload_path: Path
    metadata_path: Path


class LocalSkillArchive:
    def __init__(
        self,
        directory: str | Path,
        *,
        managed_roots: Sequence[str | Path],
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.directory = Path(directory).expanduser().resolve(strict=False)
        self.managed_roots = tuple(
            _normalized_root(root)
            for root in managed_roots
        )
        if not self.managed_roots:
            raise ValueError("managed_roots must not be empty")
        self._clock = clock or _utc_now

    def _validate_root(self, root: str | Path) -> Path:
        normalized = _normalized_root(root)
        if normalized not in self.managed_roots:
            raise SkillSupplyChainError(
                "target is not an exact managed root"
            )
        return normalized

    def archive(
        self,
        skill_dir: str | Path,
        *,
        reason: str,
    ) -> ArchivedSkill:
        skill = Path(skill_dir)
        if skill.is_symlink() or not skill.is_dir():
            raise SkillSupplyChainError(
                "skill to archive must be a real directory"
            )
        parent = self._validate_root(skill.parent)
        if _normalized_root(skill.parent) != parent:
            raise SkillSupplyChainError(
                "skill must be a direct child of a managed root"
            )
        name = _validate_skill_name(skill.name)
        if not reason.strip():
            raise ValueError("archive reason is required")
        files = _files_from_directory(skill)
        tree_hash = hash_skill_files(files)
        archived_at = self._clock()
        unsigned = {
            "name": name,
            "archived_at": archived_at,
            "reason": reason.strip(),
            "original_parent": str(parent),
            "tree_sha256": tree_hash,
        }
        archive_id = _canonical_hash(unsigned)
        archive_dir = self.directory / archive_id
        payload = archive_dir / "payload"
        metadata = archive_dir / "metadata.json"
        archive_dir.mkdir(parents=True, exist_ok=False)
        try:
            shutil.move(str(skill), str(payload))
            with metadata.open("x", encoding="utf-8") as handle:
                json.dump(
                    {**unsigned, "archive_id": archive_id},
                    handle,
                    sort_keys=True,
                    indent=2,
                )
                handle.write("\n")
        except Exception:
            if payload.exists() and not skill.exists():
                shutil.move(str(payload), str(skill))
            shutil.rmtree(archive_dir, ignore_errors=True)
            raise
        return ArchivedSkill(
            archive_id=archive_id,
            name=name,
            archived_at=archived_at,
            reason=reason.strip(),
            original_parent=str(parent),
            tree_sha256=tree_hash,
            payload_path=payload,
            metadata_path=metadata,
        )

    def restore(
        self,
        archive_id: str,
        target_root: str | Path,
    ) -> Path:
        if not _SHA256_RE.fullmatch(archive_id):
            raise SkillSupplyChainError(
                "archive_id must be a SHA-256 hex digest"
            )
        root = self._validate_root(target_root)
        archive_dir = self.directory / archive_id
        metadata_path = archive_dir / "metadata.json"
        payload = archive_dir / "payload"
        try:
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillSupplyChainError(
                "archive metadata is missing or invalid"
            ) from exc
        unsigned = {
            "name": metadata.get("name"),
            "archived_at": metadata.get("archived_at"),
            "reason": metadata.get("reason"),
            "original_parent": metadata.get("original_parent"),
            "tree_sha256": metadata.get("tree_sha256"),
        }
        if (
            metadata.get("archive_id") != archive_id
            or _canonical_hash(unsigned) != archive_id
        ):
            raise SkillSupplyChainError(
                "archive metadata hash verification failed"
            )
        name = _validate_skill_name(str(metadata.get("name", "")))
        if not payload.is_dir() or payload.is_symlink():
            raise SkillSupplyChainError("archive payload is missing")
        if (
            hash_skill_files(_files_from_directory(payload))
            != metadata.get("tree_sha256")
        ):
            raise SkillSupplyChainError(
                "archive payload hash verification failed"
            )
        target = root / name
        if target.exists() or target.is_symlink():
            raise SkillSupplyChainError(
                f"restore target already exists: {target}"
            )
        root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(payload), str(target))
        shutil.rmtree(archive_dir, ignore_errors=True)
        return target


@dataclass(frozen=True)
class ManifestSnapshot:
    path: Path
    content: str
    sha256: str


class SkillManifestEditor:
    @staticmethod
    def _validate(path: str | Path) -> Path:
        target = Path(path)
        if target.name != "SKILL.md":
            raise SkillSupplyChainError(
                "manifest editor only manages SKILL.md"
            )
        if target.is_symlink() or not target.is_file():
            raise SkillSupplyChainError(
                "SKILL.md must be a real existing file"
            )
        return target

    def read(self, path: str | Path) -> ManifestSnapshot:
        target = self._validate(path)
        body = target.read_bytes()
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillSupplyChainError(
                "SKILL.md must be valid UTF-8"
            ) from exc
        return ManifestSnapshot(
            target,
            content,
            hashlib.sha256(body).hexdigest(),
        )

    def write(
        self,
        path: str | Path,
        content: str,
        *,
        expected_sha256: str,
    ) -> ManifestSnapshot:
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise ValueError(
                "expected_sha256 must be a SHA-256 hex digest"
            )
        current = self.read(path)
        if current.sha256.lower() != expected_sha256.lower():
            raise ManifestConflictError(
                "SKILL.md changed since it was opened"
            )
        target = current.path
        data = content.encode("utf-8")
        mode = target.stat().st_mode & 0o777
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.tmp-",
            dir=target.parent,
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, target)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            tmp.unlink(missing_ok=True)
            raise
        return self.read(target)
