#!/usr/bin/env python3
"""Build one bounded mcporter Exa call expression without structural injection."""
from __future__ import annotations

import json
import sys

MAX_QUERY_CHARS = 2000


def build_expression(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("search query is required")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"search query exceeds {MAX_QUERY_CHARS} characters")
    return f"exa.web_search_exa(query: {json.dumps(query, ensure_ascii=False)}, numResults: 5)"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: agent-reach-query.py <query>", file=sys.stderr)
        return 2
    try:
        print(build_expression(sys.argv[1]))
    except ValueError as exc:
        print(f"Agent Reach search blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
