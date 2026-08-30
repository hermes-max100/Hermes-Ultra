import json

from hermes_ultra.agent_plugins import MCP_SCHEMA_1_0, PLUGIN_SCHEMA_1_0, AgentPluginLoader


def test_mcp_schema_mismatch_is_component_failure_not_plugin_failure(tmp_path):
    root = tmp_path / "plugin"
    (root / "skills" / "docs").mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"$schema": PLUGIN_SCHEMA_1_0, "name": "portable"}),
        encoding="utf-8",
    )
    (root / "skills" / "docs" / "SKILL.md").write_text("---\nname: docs\n---\n", encoding="utf-8")
    (root / "mcp.json").write_text(
        json.dumps({"$schema": MCP_SCHEMA_1_0.replace("1.0.0", "9.9.9"), "mcpServers": {}}),
        encoding="utf-8",
    )
    package = AgentPluginLoader().load(root)
    assert [skill.name for skill in package.skills] == ["docs"]
    assert package.mcp_servers == ()
    assert any("MCP component invalid" in warning for warning in package.warnings)
