#!/usr/bin/env python3
"""Profile/capability/effect routing over the canonical MCP provider registry.

This module is intentionally separate from the inbound stateless MCP validation
boundary. It selects provider candidates only; it does not connect, authenticate,
promote lifecycle state, or execute tools.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _registry_module():
    module_path = Path(__file__).with_name("mcp-provider-registry.py")
    spec = importlib.util.spec_from_file_location("hermes_mcp_provider_registry", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("MCP provider registry module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_registry_providers(
    *,
    profile: str,
    capability: str,
    effect: str,
    registry_path: Path | str = Path("config/mcp-provider-registry.json"),
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """Return deterministic provider candidates for one capability request."""
    module = _registry_module()
    data = module.load_registry(Path(registry_path))
    return module.select_candidates(
        data,
        profile=profile,
        capability=capability,
        effect=effect,
        include_inactive=include_inactive,
    )
