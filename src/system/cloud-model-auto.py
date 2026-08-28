#!/usr/bin/env python3
"""Select the best configured Hermes cloud model for a task."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

STOPWORDS = frozenset(
    """
    a an the and or but in on at to for of with by from is are was were be been being
    this that these those it its what when where how why can could should would please
    use using need want make build create update fix run route model llm ai
    """.split()
)


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._-]*", text.lower())
        if len(token) >= 3 and token not in STOPWORDS
    }


def task_tags(query: str) -> set[str]:
    lower = query.lower()
    tags = tokenize(query)
    patterns = {
        "coding": r"\b(code|test|bug|repo|script|function|api|cli|python|bash|javascript)\b",
        "reasoning": r"\b(reason|analyze|debug|architecture|strategy|complex|deep|evaluate)\b",
        "writing": r"\b(write|draft|rewrite|copy|email|brief|memo|marketing)\b",
        "long_context": r"\b(long|document|pdf|transcript|contract|record|evidence|context)\b",
        "fast": r"\b(quick|fast|simple|short|classify|summarize)\b",
        "agentic_work": r"\b(agent|tool|workflow|orchestrate|router|skill|automation)\b",
        "large_repo": r"\b(large repo|repository|codebase|monorepo|multi-file|many files)\b",
        "kimi": r"\b(kimi|moonshot|k3|kimi3|kimi-k3)\b",
        "cyberkimi": r"\b(cyberkimi|cyber kimi|adverserial|cyberkimi-quarantine|quarantine)\b",
    }
    for tag, pattern in patterns.items():
        if re.search(pattern, lower):
            tags.add(tag)
    return tags


def score_model(query_tags: set[str], provider_key: str, provider: dict, model: dict, require_key: bool) -> tuple[float, dict]:
    credential_env = provider.get("credential_env_var", "")
    has_key = bool(credential_env and os.environ.get(credential_env))
    best_for = set(model.get("best_for", []))
    tier = model.get("tier", "")
    overlap = len(query_tags & best_for)
    score = overlap * 10.0

    if has_key:
        score += 25.0
    elif require_key:
        score -= 1000.0

    if tier == "large":
        score += 4.0
    elif tier == "router":
        score += 6.0
    elif tier == "small" and "fast" in query_tags:
        score += 5.0

    if provider_key == "zenmux" and model.get("id") == "auto":
        score += 3.0
    if provider_key == "9router" and model.get("id") in {"auto", "auto/coding"}:
        score += 3.0
    if model.get("id") == "moonshotai/kimi-k3" and {"coding", "agentic_work", "long_context", "large_repo", "kimi"} & query_tags:
        score += 5.0
    if model.get("id") == "kimi/kimi-latest" and {"reasoning", "coding", "agentic_work", "long_context", "large_repo", "kimi"} & query_tags:
        score += 5.0
    if model.get("id") == "clinepass/cline-pass/kimi-k2.7-code" and {"coding", "agentic_work", "large_repo", "kimi"} & query_tags:
        score += 6.0
    if provider_key == "nvidia" and {"coding", "reasoning"} & query_tags:
        score += 2.0
    if provider_key == "adverserial":
        if "cyberkimi" in query_tags:
            score += 8.0
        else:
            score -= 500.0

    return score, {
        "provider": provider_key,
        "model_id": model["id"],
        "router_model": provider["router_model"],
        "display_name": provider.get("display_name", provider_key),
        "credential_env_var": credential_env,
        "has_key": has_key,
        "base_url_env_var": provider.get("base_url_env_var", ""),
        "default_base_url": provider.get("default_base_url", ""),
        "protocol": provider.get("protocol", ""),
        "score": round(score, 3),
        "matched_tags": sorted(query_tags & best_for),
        "tier": tier,
        "label": model.get("label", model["id"]),
    }


def select(catalog_path: Path, query: str, require_key: bool) -> dict:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    query_tags = task_tags(query)
    candidates = []
    for provider_key, provider in catalog.get("providers", {}).items():
        for model in provider.get("models", []):
            _, detail = score_model(query_tags, provider_key, provider, model, require_key)
            candidates.append(detail)
    if not candidates:
        raise SystemExit("no cloud models in catalog")
    candidates.sort(key=lambda item: item["score"], reverse=True)
    selected = dict(candidates[0])
    selected["query_tags"] = sorted(query_tags)
    selected["candidates"] = candidates[:10]
    if require_key and not selected["has_key"]:
        raise SystemExit("no catalog provider with a loaded API key matched the task")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-select a Hermes cloud model.")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--require-key", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    selected = select(Path(args.catalog), args.query, args.require_key)
    if args.json:
        print(json.dumps(selected, indent=2, sort_keys=True))
    else:
        print(f"{selected['provider']}\t{selected['model_id']}\t{selected['score']}\t{','.join(selected['matched_tags'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
