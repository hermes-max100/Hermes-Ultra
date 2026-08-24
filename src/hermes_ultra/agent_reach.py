from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence

from .contracts import CapabilityResult, FailureClass
from .evidence import redact_secrets

SUPPORTED_CHANNELS = (
    "opencli",
    "twitter",
    "xiaoyuzhou",
    "xueqiu",
    "xiaohongshu",
    "reddit",
    "facebook",
    "instagram",
    "bilibili",
    "linkedin",
)


class AgentReachError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentReachResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _safe_text(value: str) -> str:
    redacted = redact_secrets(value)
    return redacted if isinstance(redacted, str) else str(redacted)


class AgentReachAdapter:
    """Hermes integration boundary for Agent Reach.

    Every supported Agent-Reach channel is eligible. Authenticated upstream
    tools receive the configured environment directly; Hermes never converts
    authentication into a per-use approval gate. Persisted diagnostics are
    redacted without narrowing the underlying capability.
    """

    def __init__(
        self,
        binary: str = "agent-reach",
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.binary = binary
        self._env = dict(os.environ if env is None else env)

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _run(self, args: Sequence[str], *, check: bool = True) -> AgentReachResult:
        proc = subprocess.run(
            [self.binary, *args],
            env=self._env,
            text=True,
            capture_output=True,
            check=False,
        )
        result = AgentReachResult(
            command=tuple([self.binary, *args]),
            returncode=proc.returncode,
            stdout=_safe_text(proc.stdout),
            stderr=_safe_text(proc.stderr),
        )
        if check and not result.ok:
            raise AgentReachError(
                f"Agent Reach command failed ({result.returncode}): "
                f"{self.binary}\n{result.stderr.strip()}"
            )
        return result

    def install_all(self, *, system: bool = False, dry_run: bool = False) -> AgentReachResult:
        """Prepare every supported Agent-Reach channel.

        `system=False` follows Agent Reach's read-only install check. `system=True`
        is available for an already-authorized host-management context; Hermes does
        not insert a separate per-channel approval mechanism here.
        """
        args = ["install", "--env=auto", "--channels=all"]
        if dry_run:
            args.append("--dry-run")
        elif system:
            args.append("--system")
        return self._run(args)

    def doctor(self) -> AgentReachResult:
        return self._run(["doctor"], check=False)

    def configure(self, target: str, *extra: str) -> AgentReachResult:
        if not target or target.startswith("-"):
            raise ValueError("configure target must be a non-option name")
        return self._run(["configure", target, *extra])

    def upstream(self, executable: str, *args: str, check: bool = True) -> AgentReachResult:
        """Execute an Agent-Reach-managed upstream CLI without narrowing capabilities."""
        if not executable or executable.startswith("-"):
            raise ValueError("executable must be a command name")
        if shutil.which(executable) is None:
            raise AgentReachError(f"Required upstream command is not installed: {executable}")
        proc = subprocess.run(
            [executable, *args],
            env=self._env,
            text=True,
            capture_output=True,
            check=False,
        )
        result = AgentReachResult(
            command=tuple([executable, *args]),
            returncode=proc.returncode,
            stdout=_safe_text(proc.stdout),
            stderr=_safe_text(proc.stderr),
        )
        if check and not result.ok:
            raise AgentReachError(
                f"Upstream command failed ({result.returncode}): "
                f"{executable}\n{result.stderr.strip()}"
            )
        return result

    def execute_with_fallback(
        self,
        routes: Sequence[tuple[str, Sequence[str]]],
    ) -> CapabilityResult[AgentReachResult]:
        """Try supported upstream routes in order until one succeeds.

        Route failure is evidence, not an approval event. Only exhaustion of all
        supplied routes returns a blocking capability failure.
        """
        attempted: list[str] = []
        failures: list[dict[str, object]] = []
        for executable, args in routes:
            attempted.append(executable)
            try:
                result = self.upstream(executable, *args, check=False)
            except AgentReachError as exc:
                failures.append({"backend": executable, "error": _safe_text(str(exc))})
                continue
            if result.ok:
                return CapabilityResult.success(
                    result,
                    metadata={
                        "selected_backend": executable,
                        "attempted_backends": attempted.copy(),
                        "prior_failures": failures,
                    },
                )
            failures.append(
                {
                    "backend": executable,
                    "returncode": result.returncode,
                    "stderr": result.stderr,
                }
            )
        return CapabilityResult.failure(
            FailureClass.UPSTREAM_UNAVAILABLE,
            "all Agent-Reach routes failed",
            recoverable=False,
            metadata={
                "attempted_backends": attempted,
                "failures": redact_secrets(failures),
            },
        )

    def status(self) -> dict[str, object]:
        doctor = self.doctor() if self.available() else None
        return redact_secrets(
            {
                "provider": "agent-reach",
                "mode": "all-channels",
                "supported_channels": list(SUPPORTED_CHANNELS),
                "binary_available": self.available(),
                "doctor_returncode": None if doctor is None else doctor.returncode,
                "doctor_stdout": None if doctor is None else doctor.stdout,
                "doctor_stderr": None if doctor is None else doctor.stderr,
            }
        )

    def status_json(self) -> str:
        return json.dumps(self.status(), indent=2, sort_keys=True)
