#!/usr/bin/env python3
"""Verify the staged Agent Reach source before privileged provisioning."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

EXPECTED_POLICY_KEYS = {"schema_version", "repository", "commit", "version", "runtime_policy"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class SourcePolicyError(RuntimeError):
    pass


def _run_git(source: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(source), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SourcePolicyError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _canonical_repo(value: str) -> str:
    value = value.strip()
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:"):]
    if value.startswith("ssh://git@github.com/"):
        value = "https://github.com/" + value[len("ssh://git@github.com/"):]
    if value.startswith("http://github.com/"):
        value = "https://github.com/" + value[len("http://github.com/"):]
    if value.startswith("https://github.com/") and not value.endswith(".git"):
        value += ".git"
    return value


def load_policy(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourcePolicyError(f"invalid source policy: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != EXPECTED_POLICY_KEYS:
        raise SourcePolicyError("source policy schema mismatch")
    if raw.get("schema_version") != "agent-reach-source-policy-v1":
        raise SourcePolicyError("unsupported source policy schema")
    commit = raw.get("commit")
    if not isinstance(commit, str) or not SHA40.fullmatch(commit):
        raise SourcePolicyError("source policy commit must be a full 40-character SHA")
    repository = raw.get("repository")
    if repository != "https://github.com/Panniantong/Agent-Reach.git":
        raise SourcePolicyError("unexpected Agent Reach repository")
    if raw.get("runtime_policy") != "read-collect-only":
        raise SourcePolicyError("runtime policy must remain read-collect-only")
    if not isinstance(raw.get("version"), str) or not raw["version"]:
        raise SourcePolicyError("source policy version is required")
    return raw


def reject_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise SourcePolicyError(f"source path is a symlink: {path}")
    for item in path.rglob("*"):
        if item.is_symlink():
            raise SourcePolicyError(f"source tree contains symlink: {item.relative_to(path)}")


def verify_source(source: Path, policy_path: Path) -> dict[str, Any]:
    policy = load_policy(policy_path)
    if not source.exists() or not source.is_dir():
        raise SourcePolicyError(f"Agent Reach source missing: {source}")
    reject_symlinks(source)

    inside = _run_git(source, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        raise SourcePolicyError("source is not a git work tree")
    head = _run_git(source, "rev-parse", "HEAD")
    if head != policy["commit"]:
        raise SourcePolicyError(f"source commit mismatch: expected {policy['commit']}, got {head}")
    origin = _canonical_repo(_run_git(source, "remote", "get-url", "origin"))
    if origin != policy["repository"]:
        raise SourcePolicyError(f"source origin mismatch: {origin}")
    dirty = _run_git(source, "status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise SourcePolicyError("source work tree is dirty; refuse provisioning")
    if (source / ".gitmodules").exists():
        submodules = _run_git(source, "submodule", "status", "--recursive")
        if any(line[:1] in {"-", "+", "U"} for line in submodules.splitlines() if line):
            raise SourcePolicyError("source submodule state is not pinned/clean")

    pyproject = source / "pyproject.toml"
    try:
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SourcePolicyError(f"invalid pyproject.toml: {exc}") from exc
    project = metadata.get("project")
    if not isinstance(project, dict):
        raise SourcePolicyError("pyproject project metadata missing")
    if project.get("name") != "agent-reach":
        raise SourcePolicyError("unexpected project name")
    if project.get("version") != policy["version"]:
        raise SourcePolicyError(
            f"source version mismatch: expected {policy['version']}, got {project.get('version')}"
        )

    return {
        "schema_version": "agent-reach-source-verification-v1",
        "verified": True,
        "repository": policy["repository"],
        "commit": head,
        "version": policy["version"],
        "source": str(source.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--policy", required=True)
    args = parser.parse_args()
    try:
        result = verify_source(Path(args.source), Path(args.policy))
    except SourcePolicyError as exc:
        print(f"Agent Reach source verification failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
