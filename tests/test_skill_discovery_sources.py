from hermes_ultra.skill_lifecycle import DEFAULT_DISCOVERY_SOURCES


def test_skill_manager_sources_are_discovery_only() -> None:
    by_name = {source.name: source for source in DEFAULT_DISCOVERY_SOURCES}

    assert by_name["skill-manager"].repository == (
        "https://github.com/abubakarsiddik31/skill-manager"
    )
    assert by_name["all-mcp-servers"].repository == "https://www.allmcpservers.com/"
    assert by_name["skill-manager"].discovery_only
    assert by_name["all-mcp-servers"].discovery_only
    assert not by_name["skill-manager"].auto_install
    assert not by_name["all-mcp-servers"].auto_install
