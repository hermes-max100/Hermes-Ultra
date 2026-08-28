#!/usr/bin/env python3
"""Hermes Sandbox Candidate Executor hardened entrypoint.

The orchestration core remains separate from the OS containment boundary so the
security-critical command runner is small and independently reviewable. Every
candidate-controlled regression, subsystem, and governance command is executed
under Landlock + seccomp. Missing/unsafe isolation fails the candidate closed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MAX_COMMAND_TIMEOUT_SECONDS = 600


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load_module("hermes_sandbox_candidate_core", HERE / "sandbox-candidate-core.py")
isolation = load_module("hermes_sandbox_isolation", HERE / "sandbox-isolation.py")

core.PROTECTED_PATH_PREFIXES.update({
    "src/system/sandbox-candidate-core.",
    "src/system/sandbox-isolation.",
    "src/system/containment-gateway.",
    "src/system/approval-security.",
    "src/system/outbound-executor.",
    "src/system/outbound-executor-core.",
    "src/system/contact-form-executor.",
    "src/system/contact-form-executor-core.",
})


def hardened_run_test_command(command: str, worktree: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    # Lexical rejection remains defense in depth; hidden socket calls inside an
    # otherwise benign command are denied by seccomp and filesystem escape is
    # denied by Landlock in the child launcher.
    if core.NETWORK_COMMAND_RE.search(command):
        return {
            "cmd": command,
            "returncode": 126,
            "stdout": "",
            "stderr": "network-capable command rejected by sandbox policy",
            "timed_out": False,
            "rejected": True,
            "isolation": "pre-execution-command-filter",
        }
    try:
        home = Path(env["HOME"])
        return isolation.run_isolated(command, worktree, home, timeout)
    except isolation.SandboxIsolationError as exc:
        return {
            "cmd": ["sandbox:landlock+seccomp", "bash", "-lc", command],
            "returncode": 126,
            "stdout": "",
            "stderr": f"OS sandbox unavailable: {exc}",
            "timed_out": False,
            "rejected": True,
            "isolation": "fail-closed",
        }


_original_scrub = core.scrub_for_artifact
_original_execute_candidate = core.execute_candidate


def hardened_scrub_for_artifact(value: Any) -> Any:
    if isinstance(value, dict) and isinstance(value.get("resource_usage"), dict):
        value = dict(value)
        resource_usage = dict(value["resource_usage"])
        resource_usage["network_policy"] = "seccomp-deny-network-syscalls"
        resource_usage["filesystem_policy"] = "landlock-read-allowlist+writable-workspace-and-sandbox-home-only"
        resource_usage["process_policy"] = "no-new-privs+seccomp+bounded-rlimits"
        resource_usage["secret_policy"] = "minimal-environment+Landlock-denies-host-home-and-unlisted-paths"
        value["resource_usage"] = resource_usage
    return _original_scrub(value)


def hardened_execute_candidate(args: Any) -> dict[str, Any]:
    if bool(getattr(args, "allow_governance_paths", False)):
        raise SystemExit("--allow-governance-paths is not permitted at the candidate execution boundary")
    timeout = int(getattr(args, "command_timeout", 0))
    if timeout < 1 or timeout > MAX_COMMAND_TIMEOUT_SECONDS:
        raise SystemExit(f"--command-timeout must be between 1 and {MAX_COMMAND_TIMEOUT_SECONDS} seconds")
    return _original_execute_candidate(args)


core.run_test_command = hardened_run_test_command
core.scrub_for_artifact = hardened_scrub_for_artifact
core.execute_candidate = hardened_execute_candidate


def main() -> int:
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
