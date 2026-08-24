from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence

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


class AgentReachAdapter:
    """Hermes integration boundary for Agent Reach.

    Broad capability is enabled by default: all Agent-Reach channels are eligible.
    Hermes does not scrape or persist browser secrets itself; Agent Reach/upstream tools
    own their documented local authentication flows.
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
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
        if check and not result.ok:
            raise AgentReachError(
                f"Agent Reach command failed ({result.returncode}): "
                f"{' '.join(result.command)}\n{result.stderr.strip()}"
            )
        return result

    def install_all(self, *, system: bool = False, dry_run: bool = False) -> AgentReachResult:
        """Prepare every supported Agent-Reach channel.

        system=False is intentionally read-only, matching Agent Reach's safe default.
        system=True performs upstream-supported installs/configuration and should only be
        used on a host where the operator has authorized those host changes.
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
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
        if check and not result.ok:
            raise AgentReachError(
                f"Upstream command failed ({result.returncode}): "
                f"{' '.join(result.command)}\n{result.stderr.strip()}"
            )
        return result

    def status(self) -> dict[str, object]:
        doctor = self.doctor() if self.available() else None
        return {
            "provider": "agent-reach",
            "mode": "all-channels",
            "supported_channels": list(SUPPORTED_CHANNELS),
            "binary_available": self.available(),
            "doctor_returncode": None if doctor is None else doctor.returncode,
            "doctor_stdout": None if doctor is None else doctor.stdout,
            "doctor_stderr": None if doctor is None else doctor.stderr,
        }

    def status_json(self) -> str:
        return json.dumps(self.status(), indent=2, sort_keys=True)
