#!/usr/bin/env python3
"""Hermes Sandbox Candidate Executor v1.

Executes an explicit candidate patch in a disposable detached Git worktree and
emits immutable sandbox evidence. This tool never edits the live checkout,
commits, promotes, or validates a candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTECTED_PATH_PREFIXES = {
    ".hermes/",
    ".skills/",
    "config/anchor",
    "config/canary",
    "src/system/anchor-evaluator.",
    "src/system/canary-controller.",
    "src/system/memory-fabric.",
    "src/system/sandbox-candidate-executor.",
    "src/system/trust-gate.",
    "tests/test_anchor_evaluator.",
    "tests/test_canary_controller.",
    "tests/test_memory_classification.",
    "tests/test_memory_fabric.",
    "tests/test_sandbox_candidate_executor.",
    "tests/test_trust_gate.",
}

NETWORK_COMMAND_RE = re.compile(
    r"\b(curl|wget|ssh|scp|sftp|rsync|nc|netcat|ncat|telnet|ftp|gh|git\s+push|"
    r"git\s+pull|git\s+fetch|npm|pnpm|yarn|pip|pip3|uv|poetry|cargo\s+install|"
    r"go\s+get|docker\s+pull|docker\s+run)\b",
    re.I,
)

SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|cookie|credential|otp|pass(word)?|secret|session|token)",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fsync_file(path)


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    fsync_file(path)


def fsync_file(path: Path) -> None:
    with path.open("rb") as f:
        os.fsync(f.fileno())


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    input_text: str | None = None,
) -> dict[str, Any]:
    started = utc_now()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": cmd,
            "cwd": str(cwd),
            "started_at": started,
            "finished_at": utc_now(),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "cwd": str(cwd),
            "started_at": started,
            "finished_at": utc_now(),
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"command timed out after {timeout}s",
            "timed_out": True,
        }


def sanitized_env(home: Path) -> dict[str, str]:
    keep = {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TERM": os.environ.get("TERM", "dumb"),
        "HOME": str(home),
        "HERMES_SANDBOX": "1",
        "NO_NETWORK": "1",
    }
    return {k: v for k, v in keep.items() if v}


def scrub_for_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = scrub_for_artifact(item)
        return out
    if isinstance(value, list):
        return [scrub_for_artifact(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1[REDACTED]", value)
    return value


def verify_candidate_package(package_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = package_dir / "candidate-manifest.json"
    receipt_path = package_dir / "candidate-receipt.json"
    regression_path = package_dir / "regression-test-spec.json"
    for path in (manifest_path, receipt_path, regression_path):
        if not path.is_file():
            raise SystemExit(f"candidate package missing required artifact: {path}")

    manifest = read_json(manifest_path)
    receipt = read_json(receipt_path)
    regression = read_json(regression_path)

    if manifest.get("artifact_type") != "hermes-candidate-package":
        raise SystemExit("candidate manifest has unsupported artifact_type")
    if receipt.get("artifact_type") != "candidate-package-receipt":
        raise SystemExit("candidate receipt has unsupported artifact_type")
    if regression.get("artifact_type") != "candidate-regression-test-spec":
        raise SystemExit("regression spec has unsupported artifact_type")
    if manifest.get("required_anchor_changes") != []:
        raise SystemExit("candidate required_anchor_changes must be empty")
    if receipt.get("package_immutable") is not True:
        raise SystemExit("candidate receipt must declare package_immutable=true")

    expected_manifest_hash = str(manifest.get("candidate_manifest_hash") or "")
    body = dict(manifest)
    body.pop("candidate_manifest_hash", None)
    actual_manifest_hash = sha256_json(body)
    if expected_manifest_hash != actual_manifest_hash:
        raise SystemExit(f"candidate manifest hash mismatch: {expected_manifest_hash} != {actual_manifest_hash}")
    if str(receipt.get("candidate_manifest_hash") or "") != expected_manifest_hash:
        raise SystemExit("candidate receipt manifest hash does not match manifest")

    actual_regression_hash = sha256_file(regression_path)
    if str(manifest.get("regression_test_spec_hash") or "") != actual_regression_hash:
        raise SystemExit("manifest regression_test_spec_hash does not match regression artifact")
    if str(receipt.get("regression_test_spec_hash") or "") != actual_regression_hash:
        raise SystemExit("receipt regression_test_spec_hash does not match regression artifact")
    return manifest, receipt, regression


def git_output(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def repo_root(path: Path) -> Path:
    return Path(git_output(path, "rev-parse", "--show-toplevel"))


def parse_patch_paths(diff_text: str) -> list[str]:
    paths: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                for raw in parts[2:4]:
                    path = raw[2:] if raw.startswith(("a/", "b/")) else raw
                    if path != "/dev/null":
                        paths.add(path)
        elif line.startswith(("--- ", "+++ ")):
            raw = line.split(maxsplit=1)[1].strip()
            if raw == "/dev/null":
                continue
            path = raw[2:] if raw.startswith(("a/", "b/")) else raw
            paths.add(path)
    return sorted(paths)


def normalize_rel_path(path: str) -> str:
    normalized = Path(path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise SystemExit(f"unsafe affected path: {path}")
    return normalized.as_posix()


def is_protected_path(path: str) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def explicit_diff(manifest: dict[str, Any]) -> str:
    proposed = manifest.get("proposed_diff")
    if not isinstance(proposed, dict):
        return ""
    if str(proposed.get("status") or "") == "not_generated_by_v1":
        return ""
    return str(proposed.get("content") or "")


def verify_base_hashes(root: Path, worktree: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    verified: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    base_hashes = manifest.get("base_version_hashes", {})
    if not isinstance(base_hashes, dict):
        raise SystemExit("manifest base_version_hashes must be a JSON object")
    for raw_path, raw_digest in base_hashes.items():
        rel = normalize_rel_path(str(raw_path))
        digest = str(raw_digest)
        path = worktree / rel
        if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            skipped.append({"path": rel, "reason": "non_sha256_digest"})
            continue
        if not path.is_file():
            raise SystemExit(f"base hash target missing: {rel}")
        actual = sha256_file(path)
        if actual != digest:
            raise SystemExit(f"base hash mismatch for {rel}: {digest} != {actual}")
        verified.append({"path": rel, "sha256": actual})
    return verified, skipped


def run_test_command(command: str, worktree: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    if NETWORK_COMMAND_RE.search(command):
        return {
            "cmd": command,
            "returncode": 126,
            "stdout": "",
            "stderr": "network-capable command rejected by sandbox policy",
            "timed_out": False,
            "rejected": True,
        }
    return run(["bash", "-lc", command], cwd=worktree, env=env, timeout=timeout)


def summarize_command(result: dict[str, Any]) -> dict[str, Any]:
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    return {
        "cmd": result.get("cmd"),
        "returncode": result.get("returncode"),
        "timed_out": result.get("timed_out", False),
        "stdout_sha256": sha256_text(stdout),
        "stderr_sha256": sha256_text(stderr),
        "stdout_excerpt": stdout[:500],
        "stderr_excerpt": stderr[:500],
        "rejected": bool(result.get("rejected")),
    }


def changed_paths(worktree: Path) -> list[str]:
    out = git_output(worktree, "diff", "--name-only")
    return sorted(path for path in out.splitlines() if path.strip())


def seal_dir(tmp_dir: Path, final_dir: Path) -> None:
    if final_dir.exists():
        raise SystemExit(f"sandbox result already exists; refusing overwrite: {final_dir}")
    fsync_dir(tmp_dir)
    fsync_dir(final_dir.parent)
    try:
        os.replace(tmp_dir, final_dir)
    except FileExistsError:
        raise SystemExit(f"sandbox result already exists; refusing overwrite: {final_dir}") from None
    fsync_dir(final_dir.parent)


def persist_memory(root: Path, result: dict[str, Any], result_path: Path, result_hash: str) -> tuple[str, str]:
    if os.environ.get("HERMES_MEMORY_DISABLE") == "1":
        return "", "disabled"
    memory = root / "src/system/memory-fabric.py"
    if not memory.is_file():
        return "", "memory-fabric-missing"
    envelope = {
        "producer": "sandbox-candidate-executor",
        "objective": "sandbox-candidate-execution",
        "input_hash": str(result.get("input_manifest_hash") or ""),
        "selected_agent": "sandbox-candidate-executor",
        "actions": [
            {
                "type": "sandbox_candidate_execution",
                "candidate_id": result.get("candidate_id"),
                "sandbox_run_id": result.get("sandbox_run_id"),
            }
        ],
        "predicted_outcome": "candidate patch should pass bounded sandbox checks",
        "observed_outcome": f"status={result.get('status')} changed_paths={len(result.get('actual_affected_paths', []))}",
        "status": result.get("status"),
        "failure_class": "" if result.get("status") == "sandbox_passed" else str(result.get("failure_class") or "sandbox candidate did not pass"),
        "evidence_refs": [{"type": "sandbox-result-json", "path": str(result_path), "sha256": result_hash}],
        "security_classification": result.get("security_classification") or "INTERNAL",
        "metadata": {
            "candidate_id": result.get("candidate_id"),
            "sandbox_run_id": result.get("sandbox_run_id"),
            "safety_claim": result.get("status") == "sandbox_passed",
            "evidence_persisted": True,
            "result_hash": result_hash,
        },
    }
    proc = subprocess.run(
        [sys.executable, str(memory), "ingest-trajectory", "--json", json.dumps(envelope, sort_keys=True)],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return "", proc.stderr.strip() or proc.stdout.strip()
    return proc.stdout.strip().partition("=")[2], "persisted"


def run_trust_gate(root: Path, final_dir: Path, reports_dir: Path) -> dict[str, Any]:
    gate = root / "src/system/trust-gate.sh"
    if not gate.is_file():
        return {"status": "missing"}
    env = dict(os.environ)
    env["HERMES_TRUST_GATE_REPORTS_DIR"] = str(reports_dir)
    proc = subprocess.run(
        [str(gate), "scan", str(final_dir), "--type", "package"],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    parsed: dict[str, Any] = {
        "status": "ran",
        "returncode": proc.returncode,
        "stdout_sha256": sha256_text(proc.stdout),
        "stderr_sha256": sha256_text(proc.stderr),
    }
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            parsed[key.strip()] = value.strip()
    if proc.returncode != 0:
        parsed["stderr_excerpt"] = proc.stderr[:500]
    return parsed


def execute_candidate(args: argparse.Namespace) -> dict[str, Any]:
    package_dir = Path(args.package_dir).resolve()
    manifest, _receipt, regression = verify_candidate_package(package_dir)
    root = repo_root(Path.cwd())
    base_commit = args.base_commit or git_output(root, "rev-parse", "HEAD")
    sandbox_root = Path(args.sandbox_dir).resolve()
    result_root = Path(args.result_dir).resolve()
    sandbox_root.mkdir(parents=True, exist_ok=True)
    result_root.mkdir(parents=True, exist_ok=True)

    sandbox_run_id = "sbox_" + sha256_text(f"{manifest['candidate_id']}:{utc_now()}:{uuid.uuid4().hex}")[:20]
    worktree = sandbox_root / sandbox_run_id / "worktree"
    home = sandbox_root / sandbox_run_id / "home"
    home.mkdir(parents=True, exist_ok=False)

    add = run(["git", "worktree", "add", "--detach", str(worktree), base_commit], cwd=root, timeout=args.command_timeout)
    if add["returncode"] != 0:
        raise SystemExit(add["stderr"] or add["stdout"] or "git worktree add failed")

    env = sanitized_env(home)
    failures: list[str] = []
    test_results: list[dict[str, Any]] = []
    subsystem_results: list[dict[str, Any]] = []
    governance_results: list[dict[str, Any]] = []
    verified_hashes: list[dict[str, str]] = []
    skipped_hashes: list[dict[str, str]] = []
    patch_text = ""
    patch_hash = sha256_text("")
    actual_paths: list[str] = []
    protected_violations: list[str] = []
    scope_escape: list[str] = []
    status = "sandbox_failed"

    try:
        verified_hashes, skipped_hashes = verify_base_hashes(root, worktree, manifest)
        diff_text = explicit_diff(manifest)
        declared_paths = {normalize_rel_path(path) for path in manifest.get("affected_paths", []) if str(path).strip()}
        patch_paths = {normalize_rel_path(path) for path in parse_patch_paths(diff_text)}
        if diff_text and not patch_paths:
            failures.append("explicit patch did not declare changed paths")
        if patch_paths and not declared_paths:
            failures.append("candidate patch has no predeclared affected_paths")
        scope_escape = sorted(patch_paths - declared_paths)
        if scope_escape:
            failures.append("candidate patch modifies paths outside affected_paths")
        protected_violations = sorted(path for path in patch_paths if is_protected_path(path))
        if protected_violations and not args.allow_governance_paths:
            failures.append("candidate patch touches protected governance paths")

        if not diff_text:
            status = "sandbox_noop"
            failures.append("candidate package contains no explicit patch content")
        elif not failures:
            check = run(["git", "apply", "--check", "-"], cwd=worktree, env=env, input_text=diff_text, timeout=args.command_timeout)
            if check["returncode"] != 0:
                failures.append("candidate patch failed git apply --check")
                test_results.append({"phase": "patch_check", **summarize_command(check)})
            else:
                applied = run(["git", "apply", "-"], cwd=worktree, env=env, input_text=diff_text, timeout=args.command_timeout)
                test_results.append({"phase": "patch_apply", **summarize_command(applied)})
                if applied["returncode"] != 0:
                    failures.append("candidate patch failed to apply")

        actual_paths = changed_paths(worktree)
        actual_set = set(actual_paths)
        if declared_paths and actual_set - declared_paths:
            failures.append("sandbox changed paths outside affected_paths")
        if any(is_protected_path(path) for path in actual_paths) and not args.allow_governance_paths:
            failures.append("sandbox changed protected governance paths")

        regression_commands = [
            str(command)
            for command in regression.get("commands", [])
            if isinstance(command, str) and command.strip()
        ]
        if regression_commands and not failures:
            for command in regression_commands:
                result = run_test_command(command, worktree, env, args.command_timeout)
                test_results.append({"phase": "candidate_regression", **summarize_command(result)})
                if result["returncode"] != 0:
                    failures.append("candidate regression command failed")

        subsystem_commands = [command for command in args.subsystem_test if command.strip()]
        if subsystem_commands and not failures:
            for command in subsystem_commands:
                result = run_test_command(command, worktree, env, args.command_timeout)
                subsystem_results.append(summarize_command(result))
                if result["returncode"] != 0:
                    failures.append("affected subsystem test failed")

        governance_commands = [command for command in args.governance_test if command.strip()]
        if governance_commands and not failures:
            for command in governance_commands:
                result = run_test_command(command, worktree, env, args.command_timeout)
                governance_results.append(summarize_command(result))
                if result["returncode"] != 0:
                    failures.append("mandatory governance regression failed")

        patch_text = git_output(worktree, "diff", "--binary", "--no-ext-diff")
        patch_hash = sha256_text(patch_text)
        if not failures:
            status = "sandbox_passed"
    finally:
        if not args.keep_worktree:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    tmp_dir = result_root / f".tmp-{sandbox_run_id}"
    final_dir = result_root / sandbox_run_id
    if tmp_dir.exists():
        raise SystemExit(f"stale sandbox result staging directory exists: {tmp_dir}")
    tmp_dir.mkdir(parents=True, exist_ok=False)
    patch_path = tmp_dir / "candidate.patch"
    write_text(patch_path, patch_text)

    result_body = scrub_for_artifact(
        {
            "artifact_type": "sandbox-candidate-result",
            "candidate_id": manifest["candidate_id"],
            "sandbox_run_id": sandbox_run_id,
            "input_manifest_hash": manifest["candidate_manifest_hash"],
            "base_commit": base_commit,
            "base_file_hashes": verified_hashes,
            "skipped_base_file_hashes": skipped_hashes,
            "declared_affected_paths": sorted(manifest.get("affected_paths", [])),
            "actual_affected_paths": actual_paths,
            "scope_escape_paths": scope_escape,
            "protected_path_violations": protected_violations,
            "patch_path": str(final_dir / "candidate.patch"),
            "patch_hash": patch_hash,
            "regression_spec_hash": sha256_file(package_dir / "regression-test-spec.json"),
            "test_results": test_results,
            "existing_suite_results": {
                "subsystem": subsystem_results,
                "mandatory_governance": governance_results,
            },
            "stdout_stderr_hashes": [
                {"cmd": item.get("cmd"), "stdout_sha256": item.get("stdout_sha256"), "stderr_sha256": item.get("stderr_sha256")}
                for item in [*test_results, *subsystem_results, *governance_results]
            ],
            "resource_usage": {
                "command_timeout_seconds": args.command_timeout,
                "network_policy": "default-deny-command-filter",
                "secret_policy": "sanitized-environment",
            },
            "security_findings": failures,
            "failure_class": "; ".join(failures),
            "exit_status": 0 if status == "sandbox_passed" else 1,
            "status": status,
            "security_classification": manifest.get("security_classification") or "INTERNAL",
            "created_at": utc_now(),
            "governance_boundary": [
                "sandbox-result-only",
                "no live checkout mutation",
                "no commit",
                "no promotion",
                "Trust Gate must review result before Anchor Evaluator treats it as candidate implementation",
            ],
        }
    )
    result_hash = sha256_json(result_body)
    result_body["sandbox_result_hash"] = result_hash
    result_path = tmp_dir / "sandbox-result.json"
    write_json(result_path, result_body)

    memory_id, memory_status = persist_memory(root, result_body, final_dir / "sandbox-result.json", result_hash)
    receipt = {
        "artifact_type": "sandbox-candidate-receipt",
        "candidate_id": manifest["candidate_id"],
        "sandbox_run_id": sandbox_run_id,
        "sandbox_result_path": str(final_dir / "sandbox-result.json"),
        "sandbox_result_hash": result_hash,
        "memory_evidence_id": memory_id,
        "memory_status": memory_status,
        "created_at": utc_now(),
    }
    write_json(tmp_dir / "sandbox-receipt.json", receipt)
    seal_dir(tmp_dir, final_dir)

    trust = run_trust_gate(root, final_dir, result_root / "trust-gate")
    receipt["trust_gate"] = trust
    write_json(final_dir / "sandbox-receipt.json", receipt)
    return {
        "status": status,
        "candidate_id": manifest["candidate_id"],
        "sandbox_run_id": sandbox_run_id,
        "sandbox_result_dir": str(final_dir),
        "sandbox_result_path": str(final_dir / "sandbox-result.json"),
        "sandbox_result_hash": result_hash,
        "patch_path": str(final_dir / "candidate.patch"),
        "patch_hash": patch_hash,
        "memory_evidence_id": memory_id,
        "memory_status": memory_status,
        "trust_gate": trust,
    }


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Sandbox Candidate Executor v1")
    parser.add_argument("package_dir", help="Immutable candidate package directory")
    parser.add_argument("--base-commit", default="")
    parser.add_argument("--sandbox-dir", default=".hermes/sandbox-worktrees")
    parser.add_argument("--result-dir", default=".hermes/sandbox-results")
    parser.add_argument("--command-timeout", type=int, default=120)
    parser.add_argument("--subsystem-test", action="append", default=[])
    parser.add_argument(
        "--governance-test",
        action="append",
        default=[
            "bash tests/test_memory_fabric.sh",
            "bash tests/test_trajectory_fabric.sh",
            "bash tests/test_memory_classification.sh",
            "bash tests/test_anchor_evaluator.sh",
            "bash tests/test_canary_controller.sh",
            "bash tests/test_trust_gate.sh",
        ],
    )
    parser.add_argument("--allow-governance-paths", action="store_true")
    parser.add_argument("--keep-worktree", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = execute_candidate(args)
    print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
