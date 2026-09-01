#!/usr/bin/env python3
"""Verify one reviewed plugin-scan baseline for an immutable Relay snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

FIELDS = ("severity", "pattern_id", "category", "file", "line", "match", "description")


def canonical_findings(raw):
    findings = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("finding is not an object")
        finding = {key: item.get(key) for key in FIELDS}
        finding["line"] = int(finding["line"] or 0)
        findings.append(finding)
    return sorted(
        findings,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )


def digest_json(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def fail(reason: str) -> int:
    print(f"RELAY_SCAN_BASELINE=FAIL reason={reason}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-result", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tag", required=True)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source-commit")
    source_group.add_argument("--source-commit-file")
    args = parser.parse_args()

    try:
        scan = json.loads(Path(args.scan_result).read_text())
        baseline = json.loads(Path(args.baseline).read_text())
        findings = canonical_findings(scan.get("findings", []))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return fail(f"invalid_input:{type(exc).__name__}")

    source_commit = args.source_commit
    if args.source_commit_file:
        try:
            source_commit = Path(args.source_commit_file).read_text().strip()
        except OSError as exc:
            return fail(f"source_commit:{type(exc).__name__}")

    try:
        plugin_root = Path(args.plugin_root)
        if not plugin_root.is_dir():
            raise OSError('plugin root is not a directory')
        plugin_rows = []
        for path in sorted(p for p in plugin_root.rglob('*') if p.is_file()):
            plugin_rows.append({
                'path': path.relative_to(plugin_root).as_posix(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        if not plugin_rows:
            raise OSError('plugin root contains no files')
        plugin_tree_sha = digest_json(plugin_rows)
    except OSError as exc:
        return fail(f"plugin_root:{type(exc).__name__}")

    expected = {
        "schema_version": 1,
        "decision": "allow_exact_reviewed_snapshot",
        "source": args.source,
        "tag": args.tag,
        "source_commit": source_commit,
        "plugin_tree_sha256": plugin_tree_sha,
        "scanner_version": scan.get("scanner_version"),
        "raw_verdict": scan.get("verdict"),
        "finding_count": len(findings),
        "finding_fingerprint_sha256": digest_json(findings),
    }
    for key, value in expected.items():
        if baseline.get(key) != value:
            return fail(f"mismatch:{key}")

    severity_counts = dict(sorted(Counter(str(x["severity"]) for x in findings).items()))
    pattern_counts = dict(sorted(Counter(str(x["pattern_id"]) for x in findings).items()))
    if baseline.get("finding_severity_counts") != severity_counts:
        return fail("mismatch:finding_severity_counts")
    if baseline.get("finding_pattern_counts") != pattern_counts:
        return fail("mismatch:finding_pattern_counts")

    print(
        "RELAY_SCAN_BASELINE=PASS "
        f"commit={source_commit} findings={len(findings)} fingerprint={expected['finding_fingerprint_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
