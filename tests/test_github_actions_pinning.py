#!/usr/bin/env python3
"""Fail if a repository workflow references a mutable third-party action tag."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^#\s]+)")
PINNED_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")


def main() -> int:
    failures: list[str] = []
    checked = 0
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES_RE.match(line)
            if not match:
                continue
            ref = match.group(1)
            if ref.startswith("./"):
                continue
            checked += 1
            if not PINNED_RE.fullmatch(ref):
                failures.append(f"{path.relative_to(ROOT)}:{lineno}: mutable action reference: {ref}")
    if checked == 0:
        failures.append("no external GitHub Action references found")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"github actions pinning tests passed ({checked} immutable references)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
