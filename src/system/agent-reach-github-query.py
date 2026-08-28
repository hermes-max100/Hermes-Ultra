#!/usr/bin/env python3
"""Build a bounded unauthenticated GitHub repository-search URL."""
from __future__ import annotations

import sys
from urllib.parse import urlencode

MAX_QUERY_CHARS = 500
BASE = "https://api.github.com/search/repositories"


def build_url(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("GitHub search query is required")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"GitHub search query exceeds {MAX_QUERY_CHARS} characters")
    return BASE + "?" + urlencode(
        {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": "10",
        }
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: agent-reach-github-query.py <query>", file=sys.stderr)
        return 2
    try:
        print(build_url(sys.argv[1]))
    except ValueError as exc:
        print(f"Agent Reach GitHub search blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
