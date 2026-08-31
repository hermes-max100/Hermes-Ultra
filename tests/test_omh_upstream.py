from __future__ import annotations

import json
from pathlib import Path


def test_omh_upstream_is_pinned_as_research_source_not_runtime_authority():
    data = json.loads(Path("config/omh-upstream.json").read_text())

    assert data["schema_version"] == 1
    assert data["source_repository"] == "rlaope/oh-my-hermes"
    assert data["stable_release"]["tag"] == "v2.0.0"
    assert data["stable_release"]["wheel_sha256"] == (
        "302ef2e629d99159a5e059c754a13e93c3435088b518af69a378da902ee45725"
    )
    assert data["research_snapshot"]["commit"] == "06df4eac8f300d9aa27290661f9edb0fb61e9b9d"
    assert data["license"] == "MIT"
    assert data["runtime_authority"] is False
    assert data["install_mode"] == "concepts_only"
    assert data["router_authority"] == "omniroute"
    assert data["durable_memory_authority"] is False
