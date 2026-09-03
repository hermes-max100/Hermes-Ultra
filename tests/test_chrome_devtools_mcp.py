from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ultra.chrome_devtools_mcp import (
    CHROME_DEVTOOLS_MCP_VERSION,
    ChromeDevToolsLaunchSpec,
    ChromeDevToolsPolicy,
    record_browser_verification,
    chrome_devtools_provider,
)
from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.skill_lifecycle import LifecycleState


def test_provider_is_direct_coding_only_and_installed_disabled() -> None:
    provider = chrome_devtools_provider()

    assert provider.provider_id == "chrome-devtools"
    assert provider.transport_type == "stdio"
    assert provider.profiles == frozenset({"coding"})
    assert provider.state is LifecycleState.INSTALLED_DISABLED
    assert provider.authorization_context == "chrome-devtools-isolated"


def test_launch_spec_is_policy_bound_pinned_isolated_and_privacy_hardened(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    authorization = ChromeDevToolsPolicy().authorize(
        profile="coding",
        target_url="http://127.0.0.1:4700/",
    )
    spec = ChromeDevToolsLaunchSpec.for_authorized_target(workspace, authorization)

    assert spec.command == "npx"
    assert spec.args[:2] == ("-y", f"chrome-devtools-mcp@{CHROME_DEVTOOLS_MCP_VERSION}")
    assert "--isolated" in spec.args
    assert "--headless" in spec.args
    assert "--no-performance-crux" in spec.args
    assert "--no-usage-statistics" in spec.args
    assert "--redact-network-headers" in spec.args
    assert f"--filesystem-root={workspace}" in spec.args
    assert "--allowed-url-pattern=http://127.0.0.1:4700/*" in spec.args
    assert spec.minimum_chrome_major == 149
    assert all("user-data-dir" not in arg for arg in spec.args)
    assert all("browser-url" not in arg for arg in spec.args)
    assert all("ws-endpoint" not in arg for arg in spec.args)


def test_launch_spec_requires_absolute_workspace(tmp_path: Path) -> None:
    authorization = ChromeDevToolsPolicy().authorize(
        profile="coding",
        target_url="http://127.0.0.1:4700/",
    )
    with pytest.raises(ValueError, match="absolute"):
        ChromeDevToolsLaunchSpec.for_authorized_target(
            Path("relative/workspace"), authorization
        )


def test_launch_spec_requires_chrome_149_for_allow_only_network_enforcement(tmp_path: Path) -> None:
    authorization = ChromeDevToolsPolicy().authorize(
        profile="coding",
        target_url="http://127.0.0.1:4700/",
    )
    spec = ChromeDevToolsLaunchSpec.for_authorized_target(tmp_path.resolve(), authorization)

    with pytest.raises(RuntimeError, match="Chrome 149"):
        spec.validate_chrome_major(148)
    spec.validate_chrome_major(149)


def test_policy_allows_local_coding_target() -> None:
    policy = ChromeDevToolsPolicy()

    decision = policy.authorize(
        profile="coding",
        target_url="http://127.0.0.1:4700/",
    )

    assert decision.allowed is True
    assert decision.reason == "isolated_local_debug_target"
    assert decision.allowed_origins == frozenset({"http://127.0.0.1:4700"})


@pytest.mark.parametrize("profile", ["legal", "LEGAL_PRIVILEGED"])
def test_policy_categorically_denies_legal_profiles(profile: str) -> None:
    policy = ChromeDevToolsPolicy()

    with pytest.raises(PermissionError, match="LEGAL_PRIVILEGED"):
        policy.authorize(profile=profile, target_url="http://127.0.0.1:4700/")


def test_policy_denies_legal_sensitivity_even_for_coding_profile() -> None:
    with pytest.raises(PermissionError, match="LEGAL_PRIVILEGED"):
        ChromeDevToolsPolicy().authorize(
            profile="coding",
            target_url="http://127.0.0.1:4700/",
            sensitivity="LEGAL_PRIVILEGED",
        )


def test_policy_denies_production_by_default() -> None:
    policy = ChromeDevToolsPolicy()

    with pytest.raises(PermissionError, match="production"):
        policy.authorize(
            profile="coding",
            target_url="http://127.0.0.1:4700/",
            production=True,
        )


def test_policy_denies_external_origin_until_explicitly_allowlisted() -> None:
    policy = ChromeDevToolsPolicy()

    with pytest.raises(PermissionError, match="allowlist"):
        policy.authorize(profile="coding", target_url="https://example.com/app")

    allowed = ChromeDevToolsPolicy(
        allowed_external_origins=frozenset({"https://example.com"})
    ).authorize(profile="coding", target_url="https://example.com/app")
    assert allowed.allowed is True
    assert allowed.reason == "explicit_external_debug_target"
    assert allowed.allowed_origins == frozenset({"https://example.com"})


def test_browser_success_requires_tests_reproduction_and_browser_evidence() -> None:
    recorder = EvidenceRecorder()

    with pytest.raises(ValueError, match="browser evidence"):
        record_browser_verification(
            recorder,
            task_id="ui-bug-1",
            run_id="run-1",
            target_url="http://127.0.0.1:4700/",
            scenario="reproduce HUD websocket failure",
            issue_resolved=True,
            tests_passed=True,
            reproduction_verified=True,
        )


def test_browser_success_records_proof_before_success() -> None:
    recorder = EvidenceRecorder()

    evidence = record_browser_verification(
        recorder,
        task_id="ui-bug-2",
        run_id="run-2",
        target_url="http://127.0.0.1:4700/",
        scenario="reproduce HUD websocket failure",
        issue_resolved=True,
        tests_passed=True,
        reproduction_verified=True,
        console_events=("WebSocket connected",),
        network_events=("GET /health 200",),
        screenshots=("artifact://hud-after-fix.webp",),
    )

    assert evidence["status"] == "success"
    assert evidence["capability"] == "chrome-devtools-browser-verification"
    artifact = evidence["artifacts"][0]
    assert artifact["issue_resolved"] is True
    assert artifact["tests_passed"] is True
    assert artifact["reproduction_verified"] is True
    assert artifact["evidence_categories"] == ("console", "network", "screenshot")
