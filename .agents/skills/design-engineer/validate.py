#!/usr/bin/env python3
"""Static policy validation for the Hermes Ultra design-engineer capability."""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
HEX40 = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_GATES = {
    "source_policy_pass",
    "build_success",
    "no_new_console_errors",
    "responsive_pass",
    "accessibility_pass",
    "interaction_pass",
    "web_interface_guidelines_pass",
    "visual_regression_pass",
}

REQUIRED_SOURCE_IDS = {
    "vercel-web-interface-guidelines",
    "microsoft-playwright",
    "senlin-taste",
    "awesome-design-catalog",
    "abi-screenshot-to-code",
    "hermes-browser-harness-self-healing",
}


def load_json(name: str) -> dict:
    with (HERE / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def by_id(sources: dict) -> dict[str, dict]:
    rows = sources.get("sources", [])
    ids = [row.get("id") for row in rows]
    assert len(ids) == len(set(ids)), "source ids must be unique"
    return {row["id"]: row for row in rows}


def validate_sources() -> None:
    data = load_json("sources.json")
    assert data.get("schema_version") == 1

    policy = data["policy"]
    assert policy["default_external_trust"] == "untrusted"
    assert policy["self_promotion_allowed"] is False
    assert policy["scout_execution_allowed"] is False
    assert policy["baseline_auto_accept_allowed"] is False

    sources = by_id(data)
    assert REQUIRED_SOURCE_IDS <= sources.keys(), "required design sources missing"

    vercel = sources["vercel-web-interface-guidelines"]
    assert vercel["trust_class"] == "trusted_core"
    assert vercel["license"] == "MIT"
    assert HEX40.fullmatch(vercel["reviewed_revision"])
    assert vercel["live_rules"].startswith(
        "https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/"
    )

    playwright = sources["microsoft-playwright"]
    assert playwright["trust_class"] == "trusted_core"
    assert playwright["license"] == "Apache-2.0"
    assert playwright["mcp_license"] == "Apache-2.0"
    assert HEX40.fullmatch(playwright["reviewed_revision"])
    assert HEX40.fullmatch(playwright["mcp_reviewed_revision"])
    assert "playwright_cli" in playwright["interface_policy"]["deterministic_coding_loop"]
    assert "playwright_mcp" in playwright["interface_policy"]["persistent_exploratory_session"]

    taste = sources["senlin-taste"]
    assert taste["trust_class"] == "candidate"
    assert taste["activation"] == "disabled_until_promoted"
    assert taste["review_status"].startswith("quarantined_")
    assert taste["license"] == "NO_LICENSE_FILE_FOUND_AT_REVIEWED_REVISION"
    assert HEX40.fullmatch(taste["reviewed_revision"])
    assert {"vendor_source", "auto_install", "auto_execute", "self_promote"} <= set(
        taste["forbidden_actions"]
    )

    catalog = sources["awesome-design-catalog"]
    assert catalog["trust_class"] == "scout_only"
    assert catalog["license"] == "MIT"
    assert {"auto_install", "execute_candidate_code", "promote_candidate"} <= set(
        catalog["forbidden_actions"]
    )

    screenshot = sources["abi-screenshot-to-code"]
    assert screenshot["trust_class"] == "optional_adapter"
    assert screenshot["activation"] == "disabled_until_needed_and_reviewed"
    assert screenshot["license"] == "MIT"
    assert {"declare_fidelity_pass", "declare_accessibility_pass", "declare_security_pass"} <= set(
        screenshot["forbidden_actions"]
    )

    local_browser = sources["hermes-browser-harness-self-healing"]
    assert local_browser["trust_class"] == "local_existing"
    assert (HERE / local_browser["path"]).resolve().is_file(), "local browser skill missing"


def validate_acceptance() -> None:
    data = load_json("acceptance.json")
    assert data.get("schema_version") == 1
    gates = {gate["id"] for gate in data["required_gates"]}
    assert gates == REQUIRED_GATES, f"acceptance gates drifted: {gates ^ REQUIRED_GATES}"

    viewports = {row["name"]: (row["width"], row["height"]) for row in data["fallback_viewports"]}
    assert viewports == {
        "mobile": (390, 844),
        "tablet": (768, 1024),
        "desktop": (1440, 900),
    }

    shortcuts = set(data["prohibited_shortcuts"])
    assert "auto_accept_changed_visual_baseline" in shortcuts
    assert "allow_discovery_catalog_to_install_or_promote_itself" in shortcuts


def validate_skill_contracts() -> None:
    design_skill = (HERE / "SKILL.md").read_text(encoding="utf-8")
    assert design_skill.startswith("---\nname: design-engineer\n")
    for heading in (
        "## Source and trust policy",
        "## Pipeline",
        "## Acceptance contract",
        "## External capability roles",
        "## Completion evidence",
    ):
        assert heading in design_skill, f"missing design-engineer section: {heading}"

    vercel_skill = SKILL_ROOT / "web-design-guidelines" / "SKILL.md"
    assert vercel_skill.is_file(), "web-design-guidelines wrapper missing"
    vercel_text = vercel_skill.read_text(encoding="utf-8")
    assert "raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md" in vercel_text
    assert "Do not return `PASS` while an applicable `FAIL` remains unresolved." in vercel_text


def main() -> None:
    validate_sources()
    validate_acceptance()
    validate_skill_contracts()
    print("DESIGN_ENGINEER_VALIDATION=PASS")


if __name__ == "__main__":
    main()
