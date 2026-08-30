from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ultra.agent_plugins import (
    MCP_SCHEMA_1_0,
    PLUGIN_SCHEMA_1_0,
    AgentPluginError,
    AgentPluginLoader,
)
from hermes_ultra.skill_lifecycle import LifecycleState, Provenance


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_plugin(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    (root / "skills" / "debug").mkdir(parents=True)
    write_json(
        root / "plugin.json",
        {
            "$schema": PLUGIN_SCHEMA_1_0,
            "name": "portable-debugger",
            "version": "1.0.0",
        },
    )
    (root / "skills" / "debug" / "SKILL.md").write_text(
        "---\nname: debug\ndescription: Debug failures.\n---\n\nDiagnose failures.\n",
        encoding="utf-8",
    )
    write_json(
        root / "mcp.json",
        {
            "$schema": MCP_SCHEMA_1_0,
            "mcpServers": {
                "docs": {
                    "type": "streamable-http",
                    "url": "https://example.com/mcp",
                },
                "local": {
                    "type": "stdio",
                    "command": "python3",
                    "args": ["${PLUGIN_ROOT}/server.py"],
                    "cwd": "${PLUGIN_ROOT}",
                },
            },
        },
    )
    return root


def test_load_discovers_fixed_skill_and_mcp_locations(tmp_path: Path) -> None:
    package = AgentPluginLoader().load(make_plugin(tmp_path))
    assert package.manifest["name"] == "portable-debugger"
    assert [skill.name for skill in package.skills] == ["debug"]
    assert {server.name for server in package.mcp_servers} == {"docs", "local"}


def test_imported_plugin_normalizes_to_candidate_only(tmp_path: Path) -> None:
    package = AgentPluginLoader().load(make_plugin(tmp_path))
    candidate = AgentPluginLoader().to_candidate(
        package,
        provenance=Provenance(
            repository="https://github.com/example/plugin",
            commit_sha="a" * 40,
            license="MIT",
            discovered_from="scout",
        ),
    )
    assert candidate.state is LifecycleState.CANDIDATE
    assert candidate.authority.network is True
    assert candidate.authority.shell is True


def test_bad_mcp_entry_isolated_from_valid_skill_and_server(tmp_path: Path) -> None:
    root = make_plugin(tmp_path)
    payload = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    payload["mcpServers"]["bad"] = {"type": "streamable-http", "url": "http://example.com/mcp"}
    write_json(root / "mcp.json", payload)
    package = AgentPluginLoader().load(root)
    assert [skill.name for skill in package.skills] == ["debug"]
    assert {server.name for server in package.mcp_servers} == {"docs", "local"}
    assert any("skipped MCP server bad" in warning for warning in package.warnings)


def test_manifest_symlink_escape_rejects_plugin(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    root.mkdir()
    outside = tmp_path / "outside.json"
    write_json(outside, {"$schema": PLUGIN_SCHEMA_1_0, "name": "escaped"})
    (root / "plugin.json").symlink_to(outside)
    with pytest.raises(AgentPluginError, match="plugin.json.*plugin root"):
        AgentPluginLoader().load(root)


def test_skills_component_symlink_escape_is_isolated(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    root.mkdir()
    write_json(root / "plugin.json", {"$schema": PLUGIN_SCHEMA_1_0, "name": "portable"})
    outside = tmp_path / "outside-skills"
    (outside / "hidden").mkdir(parents=True)
    (outside / "hidden" / "SKILL.md").write_text("---\nname: hidden\n---\n", encoding="utf-8")
    (root / "skills").symlink_to(outside, target_is_directory=True)
    package = AgentPluginLoader().load(root)
    assert package.skills == ()
    assert any("skills component invalid" in warning for warning in package.warnings)


def test_stdio_command_escape_is_rejected_per_server(tmp_path: Path) -> None:
    root = make_plugin(tmp_path)
    payload = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    payload["mcpServers"]["escape"] = {"type": "stdio", "command": "../outside"}
    write_json(root / "mcp.json", payload)
    package = AgentPluginLoader().load(root)
    assert "escape" not in {server.name for server in package.mcp_servers}


def test_unknown_manifest_field_is_ignored_with_warning(tmp_path: Path) -> None:
    root = make_plugin(tmp_path)
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    manifest["future-field"] = {"ignored": True}
    write_json(root / "plugin.json", manifest)
    package = AgentPluginLoader().load(root)
    assert package.manifest["name"] == "portable-debugger"
    assert any("future-field" in warning for warning in package.warnings)


def test_export_round_trip_preserves_portable_components(tmp_path: Path) -> None:
    loader = AgentPluginLoader()
    package = loader.load(make_plugin(tmp_path))
    exported = loader.export(package, tmp_path / "exported")
    reloaded = loader.load(exported)
    assert reloaded.manifest["$schema"] == PLUGIN_SCHEMA_1_0
    assert [skill.name for skill in reloaded.skills] == ["debug"]
    assert {server.name for server in reloaded.mcp_servers} == {"docs", "local"}
