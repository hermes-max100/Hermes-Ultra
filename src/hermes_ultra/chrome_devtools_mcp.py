from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from .evidence import EvidenceEnvelope, EvidenceRecorder
from .mcp_gateway import McpProvider
from .skill_lifecycle import LifecycleState

CHROME_DEVTOOLS_MCP_VERSION = "1.8.0"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_FORBIDDEN_PROFILES = frozenset({"legal", "legal_privileged"})
_MINIMUM_CHROME_MAJOR = 149


def _origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("target URL must be an absolute http(s) URL without embedded credentials")
    if parsed.fragment:
        raise ValueError("target URL fragments are not permitted")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _validate_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("allowed origins must be absolute http(s) origins")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


@dataclass(frozen=True)
class ChromeDevToolsAuthorization:
    allowed: bool
    reason: str
    target_origin: str
    allowed_origins: frozenset[str]

    def __post_init__(self) -> None:
        if not self.allowed:
            raise ValueError("Chrome DevTools authorization must represent an allowed target")
        target_origin = _validate_origin(self.target_origin)
        normalized = frozenset(_validate_origin(value) for value in self.allowed_origins)
        if not normalized or target_origin not in normalized:
            raise ValueError("authorized target origin must be present in allowed origins")
        object.__setattr__(self, "target_origin", target_origin)
        object.__setattr__(self, "allowed_origins", normalized)


@dataclass(frozen=True)
class ChromeDevToolsPolicy:
    """Fail-closed policy for the direct Chrome DevTools engineering capability."""

    allowed_external_origins: frozenset[str] = frozenset()
    production_allowed: bool = False

    def __post_init__(self) -> None:
        normalized = frozenset(_validate_origin(value) for value in self.allowed_external_origins)
        object.__setattr__(self, "allowed_external_origins", normalized)

    def authorize(
        self,
        *,
        profile: str,
        target_url: str,
        production: bool = False,
        sensitivity: str | None = None,
    ) -> ChromeDevToolsAuthorization:
        normalized_profile = profile.strip().lower()
        normalized_sensitivity = (sensitivity or "").strip().lower()
        if normalized_profile in _FORBIDDEN_PROFILES or normalized_sensitivity == "legal_privileged":
            raise PermissionError("Chrome DevTools MCP is forbidden for LEGAL_PRIVILEGED work")
        if normalized_profile != "coding":
            raise PermissionError("Chrome DevTools MCP is restricted to the coding profile")
        if production and not self.production_allowed:
            raise PermissionError("Chrome DevTools MCP production access is denied by default")

        parsed = urlsplit(target_url.strip())
        target_origin = _origin(target_url)
        if parsed.hostname in _LOCAL_HOSTS:
            return ChromeDevToolsAuthorization(
                True,
                "isolated_local_debug_target",
                target_origin,
                frozenset({target_origin}),
            )
        if target_origin not in self.allowed_external_origins:
            raise PermissionError("external Chrome DevTools target is not on the explicit allowlist")
        return ChromeDevToolsAuthorization(
            True,
            "explicit_external_debug_target",
            target_origin,
            frozenset({target_origin}),
        )


@dataclass(frozen=True)
class ChromeDevToolsLaunchSpec:
    command: str
    args: tuple[str, ...]
    workspace_root: str
    allowed_origins: frozenset[str]
    minimum_chrome_major: int = _MINIMUM_CHROME_MAJOR

    @classmethod
    def for_authorized_target(
        cls,
        workspace_root: Path,
        authorization: ChromeDevToolsAuthorization,
        *,
        headless: bool = True,
    ) -> "ChromeDevToolsLaunchSpec":
        if not isinstance(authorization, ChromeDevToolsAuthorization):
            raise TypeError("ChromeDevToolsAuthorization is required")
        if not authorization.allowed:
            raise PermissionError("Chrome DevTools target is not authorized")

        path = Path(workspace_root)
        if not path.is_absolute():
            raise ValueError("workspace_root must be absolute")
        allowed_origins = authorization.allowed_origins
        if not allowed_origins:
            raise ValueError("authorized target must include at least one allowed origin")

        args: list[str] = [
            "-y",
            f"chrome-devtools-mcp@{CHROME_DEVTOOLS_MCP_VERSION}",
            "--isolated",
            "--no-performance-crux",
            "--no-usage-statistics",
            "--redact-network-headers",
            f"--filesystem-root={path}",
        ]
        if headless:
            args.append("--headless")
        for origin in sorted(allowed_origins):
            args.append(f"--allowed-url-pattern={origin}/*")
        return cls(
            command="npx",
            args=tuple(args),
            workspace_root=str(path),
            allowed_origins=allowed_origins,
        )

    def validate_chrome_major(self, major: int) -> None:
        if type(major) is not int or major <= 0:
            raise ValueError("Chrome major version must be a positive integer")
        if major < self.minimum_chrome_major:
            raise RuntimeError(
                f"Chrome {self.minimum_chrome_major} or newer is required for allow-only URL enforcement"
            )


def chrome_devtools_provider() -> McpProvider:
    """Return the existing gateway's provider metadata for Chrome DevTools MCP.

    The provider remains installed-disabled until a deployment supplies and certifies
    a stdio MCP transport. This module deliberately does not bypass McpGateway.
    """

    return McpProvider(
        provider_id="chrome-devtools",
        transport_type="stdio",
        profiles=frozenset({"coding"}),
        state=LifecycleState.INSTALLED_DISABLED,
        authorization_context="chrome-devtools-isolated",
    )


def _evidence_categories(
    *,
    console_events: tuple[str, ...],
    network_events: tuple[str, ...],
    screenshots: tuple[str, ...],
    performance_traces: tuple[str, ...],
) -> tuple[str, ...]:
    categories: list[str] = []
    if console_events:
        categories.append("console")
    if network_events:
        categories.append("network")
    if screenshots:
        categories.append("screenshot")
    if performance_traces:
        categories.append("performance")
    return tuple(categories)


def record_browser_verification(
    recorder: EvidenceRecorder,
    *,
    task_id: str,
    run_id: str,
    target_url: str,
    scenario: str,
    issue_resolved: bool,
    tests_passed: bool,
    reproduction_verified: bool,
    console_events: Iterable[str] = (),
    network_events: Iterable[str] = (),
    screenshots: Iterable[str] = (),
    performance_traces: Iterable[str] = (),
) -> dict[str, object]:
    """Record browser proof and refuse a success assertion without complete evidence."""

    if not task_id.strip() or not run_id.strip() or not scenario.strip():
        raise ValueError("task_id, run_id, and scenario are required")
    _origin(target_url)
    console = tuple(console_events)
    network = tuple(network_events)
    shots = tuple(screenshots)
    traces = tuple(performance_traces)
    categories = _evidence_categories(
        console_events=console,
        network_events=network,
        screenshots=shots,
        performance_traces=traces,
    )
    if issue_resolved:
        if not tests_passed:
            raise ValueError("tests must pass before browser success can be asserted")
        if not reproduction_verified:
            raise ValueError("original browser scenario must be re-verified before success")
        if not categories:
            raise ValueError("browser evidence is required before success can be asserted")

    envelope = EvidenceEnvelope.new(
        task_id=task_id.strip(),
        capability="chrome-devtools-browser-verification",
        run_id=run_id.strip(),
    )
    envelope.provider_version = CHROME_DEVTOOLS_MCP_VERSION
    envelope.artifacts.append(
        {
            "target_url": target_url.strip(),
            "scenario": scenario.strip(),
            "issue_resolved": issue_resolved,
            "tests_passed": tests_passed,
            "reproduction_verified": reproduction_verified,
            "evidence_categories": categories,
            "console_events": console,
            "network_events": network,
            "screenshots": shots,
            "performance_traces": traces,
        }
    )
    envelope.tests.append({"tests_passed": tests_passed})
    envelope.health["reproduction_verified"] = reproduction_verified
    envelope.finish(status="success" if issue_resolved else "failure")
    return recorder.record(envelope)
