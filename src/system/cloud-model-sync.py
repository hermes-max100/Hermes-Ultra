#!/usr/bin/env python3
"""Sync OpenAI-compatible provider model lists into a local Hermes catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def fetch_models(provider_key: str, provider: dict) -> tuple[list[dict], str]:
    credential_env = provider.get("credential_env_var", "")
    api_key = os.environ.get(credential_env, "") if credential_env else ""
    if credential_env and not api_key:
        return [], f"missing_key:{credential_env}"

    base_env = provider.get("base_url_env_var", "")
    base_url = os.environ.get(base_env, provider.get("default_base_url", "")).rstrip("/")
    if not base_url:
        return [], "missing_base_url"

    url = f"{base_url}/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=int(os.environ.get("HERMES_MODEL_SYNC_TIMEOUT", "45"))) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return [], f"http_{exc.code}:{body[:160].replace(chr(10), ' ')}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return [], f"fetch_failed:{exc}"

    raw_models = payload.get("data", payload if isinstance(payload, list) else [])
    if not isinstance(raw_models, list):
        return [], "unexpected_models_response"

    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    models: list[dict] = []
    seen: set[str] = set()
    for item in raw_models:
        if isinstance(item, str):
            model_id = item
            owned_by = ""
        elif isinstance(item, dict):
            model_id = str(item.get("id", "")).strip()
            owned_by = str(item.get("owned_by", item.get("provider", ""))).strip()
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        best_for = ["synced"]
        lower = model_id.lower()
        if "code" in lower or "coder" in lower:
            best_for.append("coding")
        if "reason" in lower or lower.startswith(("o", "r1")):
            best_for.append("reasoning")
        if "search" in lower or "sonar" in lower:
            best_for.extend(["web_research", "citations"])
        if "flash" in lower or "mini" in lower or "small" in lower:
            best_for.append("fast")
        models.append(
            {
                "id": model_id,
                "label": model_id,
                "tier": "synced",
                "best_for": sorted(set(best_for)),
                "source": "provider_models_api",
                "owned_by": owned_by,
                "last_synced_at": synced_at,
            }
        )
    return models, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync provider model ids into Hermes local catalog.")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--local-catalog", required=True)
    parser.add_argument("--provider", default="all")
    args = parser.parse_args()

    base = load_json(Path(args.catalog), {"providers": {}})
    local_path = Path(args.local_catalog)
    local = load_json(local_path, {"version": "1.0.0", "providers": {}})
    local.setdefault("version", "1.0.0")
    local.setdefault("providers", {})

    providers = base.get("providers", {})
    selected = providers.keys() if args.provider == "all" else [args.provider]
    summaries = []

    for provider_key in selected:
        provider = providers.get(provider_key)
        if provider is None:
            summaries.append({"provider": provider_key, "status": "unknown_provider", "models": 0})
            continue
        if provider.get("protocol") != "openai_compatible":
            summaries.append({"provider": provider_key, "status": "unsupported_protocol", "models": 0})
            continue

        models, status = fetch_models(provider_key, provider)
        if status == "ok":
            local["providers"][provider_key] = {
                "display_name": provider.get("display_name", provider_key),
                "models": models,
                "last_synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        summaries.append({"provider": provider_key, "status": status, "models": len(models)})

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(local, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(local_path, 0o600)

    for item in summaries:
        print(f"{item['provider']}\t{item['status']}\tmodels={item['models']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
