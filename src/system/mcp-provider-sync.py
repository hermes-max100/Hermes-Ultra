#!/usr/bin/env python3
"""Merge Hermes-managed MCP providers into native Hermes Agent configuration."""
from __future__ import annotations

from typing import Any, Mapping, Iterable

_PRIVATE_KEYS = {"hermes_managed", "hermes_provider_id"}


def _native_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in config.items() if key not in _PRIVATE_KEYS}


def merge_managed_servers(
    existing: Mapping[str, Mapping[str, Any]],
    rendered: Mapping[str, Mapping[str, Any]],
    managed_ids: Iterable[str],
    *,
    previous_managed: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """Replace managed entries while preserving unrelated user MCP servers."""
    managed = set(managed_ids) | set(previous_managed)
    merged: dict[str, dict[str, Any]] = {}
    for name, config in existing.items():
        if name in managed or config.get("hermes_managed") is True:
            continue
        merged[str(name)] = dict(config)
    for name, config in rendered.items():
        merged[str(name)] = _native_config(config)
    return merged
