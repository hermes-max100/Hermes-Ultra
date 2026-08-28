#!/usr/bin/env python3
"""
Safe external source sweep for Hermes.

This script reads config/external-skill-sources.json, clones or updates each
registered repository into a local cache, inspects metadata without executing
repository code, and writes review artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RISK_TERMS = {
    "credential": ["credential theft", "password=", "api_key", "secret_key", "stealer", "phish"],
    "persistence": ["persistence module", "autorun", "launchagent", "schtasks"],
    "stealth": ["stealth mode", "evasion", "obfuscate", "anti-debug"],
    "scanning": ["nmap", "masscan", "shodan", "censys", "port scan", "vulnerability scan"],
    "exploit": ["exploit", "reverse shell", "rce", "cve-"],
    "network": ["curl http", "wget http", "fetch(", "axios."],
    "installer": ["postinstall", "install.sh", "setup.sh", "curl |", "wget |"],
}

PACKAGE_FILES = {
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "Dockerfile",
    "docker-compose.yml",
    "Makefile",
    "install.sh",
    "setup.sh",
}


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-") or "source"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_cache_path(cache_dir: Path, source: dict[str, Any]) -> Path:
    return cache_dir / slugify(source.get("id") or source.get("url", "source"))


def clone_or_update(source: dict[str, Any], dest: Path, offline: bool) -> tuple[str, str]:
    url = source.get("url", "")
    if not url:
        return "skipped", "missing url"

    if offline:
        return ("present" if dest.exists() else "skipped", "offline mode")

    if dest.exists():
        if (dest / ".git").is_dir():
            code, out, err = run(["git", "pull", "--ff-only"], cwd=dest)
            if code == 0:
                return "updated", out or "ff-only pull complete"
            return "update_failed", err or out
        return "skipped", "cache path exists but is not a git repository"

    dest.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = run(["git", "clone", "--depth", "1", url, str(dest)])
    if code == 0:
        return "cloned", out or "clone complete"
    return "clone_failed", err or out


def git_value(repo: Path, args: list[str]) -> str:
    if not (repo / ".git").is_dir():
        return ""
    code, out, _ = run(["git", *args], cwd=repo)
    return out if code == 0 else ""


def iter_text_files(repo: Path, max_files: int = 250) -> list[Path]:
    files: list[Path] = []
    for path in repo.rglob("*"):
        if len(files) >= max_files:
            break
        if ".git" in path.parts or not path.is_file():
            continue
        if path.stat().st_size > 300_000:
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz", ".pdf", ".pyc"}:
            continue
        files.append(path)
    return files


def read_small(path: Path, limit: int = 20_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def find_license(repo: Path) -> list[str]:
    names = []
    for path in repo.iterdir() if repo.is_dir() else []:
        if path.is_file() and path.name.lower().startswith(("license", "copying")):
            names.append(path.name)
    return sorted(names)


def find_package_files(repo: Path) -> list[str]:
    found = []
    for filename in sorted(PACKAGE_FILES):
        if (repo / filename).exists():
            found.append(filename)
    return found


def summarize_readme(repo: Path) -> str:
    for name in ("README.md", "readme.md", "README"):
        path = repo / name
        if path.is_file():
            text = read_small(path, 4000)
            for line in text.splitlines():
                line = line.strip().lstrip("# ").strip()
                if line:
                    return line[:180]
    return ""


def detect_package_script_risk(repo: Path) -> list[str]:
    flags = []
    package = repo / "package.json"
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            for name, value in scripts.items():
                lowered = str(value).lower()
                if name in {"postinstall", "preinstall", "prepare"}:
                    flags.append(f"npm_{name}_script")
                if any(term in lowered for term in ("curl ", "wget ", "sudo ", "chmod +x", "bash ")):
                    flags.append(f"npm_script_shell_bootstrap:{name}")
        except json.JSONDecodeError:
            flags.append("package_json_parse_failed")
    return sorted(set(flags))


def scan_risk(repo: Path) -> dict[str, Any]:
    categories: dict[str, int] = {key: 0 for key in RISK_TERMS}
    hits: list[str] = []
    for path in iter_text_files(repo):
        rel = str(path.relative_to(repo))
        lowered = read_small(path).lower()
        for category, terms in RISK_TERMS.items():
            matched = [term for term in terms if term in lowered or term in rel.lower()]
            if matched:
                categories[category] += len(matched)
                if len(hits) < 30:
                    hits.append(f"{category}:{rel}")

    script_flags = detect_package_script_risk(repo)
    if script_flags:
        categories["installer"] += len(script_flags)
        hits.extend(script_flags[:10])

    # Counts are intentionally capped so ordinary application repositories with
    # many HTTP clients do not swamp the review queue. High-risk scores require
    # multiple suspicious categories, not just lots of repeated generic words.
    score = 0
    score += min(categories["credential"], 4) * 5
    score += min(categories["persistence"], 3) * 6
    score += min(categories["stealth"], 3) * 6
    score += min(categories["exploit"], 5) * 5
    score += min(categories["scanning"], 4) * 3
    score += min(categories["installer"], 4) * 4
    score += min(categories["network"], 3) * 1

    level = "low"
    if score >= 80:
        level = "high"
    elif score >= 20:
        level = "medium"

    return {
        "risk_score": score,
        "detected_risk_level": level,
        "risk_categories": {k: v for k, v in categories.items() if v},
        "risk_hits": sorted(set(hits))[:30],
    }


def inspect_source(source: dict[str, Any], repo: Path, status: str, detail: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": source.get("id", ""),
        "url": source.get("url", ""),
        "homepage": source.get("homepage", ""),
        "configured_risk_level": source.get("risk_level", "unknown"),
        "import_policy": source.get("import_policy", "review_before_install"),
        "status": status,
        "status_detail": detail[:500],
        "cache_path": str(repo),
    }

    if not repo.is_dir():
        result.update({
            "commit": "",
            "commit_date": "",
            "license_files": [],
            "package_files": [],
            "readme_summary": "",
            "risk_score": 0,
            "detected_risk_level": "unknown",
            "risk_categories": {},
            "risk_hits": [],
        })
        return result

    result.update({
        "commit": git_value(repo, ["rev-parse", "--short=12", "HEAD"]),
        "commit_date": git_value(repo, ["log", "-1", "--format=%cI"]),
        "branch": git_value(repo, ["branch", "--show-current"]),
        "license_files": find_license(repo),
        "package_files": find_package_files(repo),
        "readme_summary": summarize_readme(repo),
    })
    result.update(scan_risk(repo))
    return result


def proposal_needed(item: dict[str, Any]) -> bool:
    if item.get("status") in {"clone_failed", "update_failed"}:
        return True
    if item.get("configured_risk_level") == "high":
        return True
    if item.get("detected_risk_level") in {"medium", "high"}:
        return True
    if item.get("package_files"):
        return True
    return False


def write_proposal(item: dict[str, Any], proposals_dir: Path, stamp: str) -> Path:
    proposal_dir = proposals_dir / f"{item['id']}-{stamp}"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    (proposal_dir / "source.json").write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# External Source Review: {item['id']}",
        "",
        f"- Source: {item.get('url', '')}",
        f"- Status: {item.get('status', '')}",
        f"- Commit: {item.get('commit', '') or 'unknown'}",
        f"- Configured risk: {item.get('configured_risk_level', 'unknown')}",
        f"- Detected risk: {item.get('detected_risk_level', 'unknown')} ({item.get('risk_score', 0)})",
        f"- Import policy: {item.get('import_policy', 'review_before_install')}",
        "",
        "## Review Checklist",
        "",
        "- Confirm license and provenance.",
        "- Inspect package/install scripts before running anything.",
        "- Compare useful patterns against existing Hermes skills.",
        "- Promote through proposal/changelog flow only.",
        "- For high-risk security sources, keep review-only unless explicit owned scope and human approval exist.",
        "",
        "## Detected Files",
        "",
    ]
    for filename in item.get("package_files", []):
        lines.append(f"- {filename}")
    if not item.get("package_files"):
        lines.append("- None detected")
    lines.extend(["", "## Risk Hits", ""])
    for hit in item.get("risk_hits", []):
        lines.append(f"- {hit}")
    if not item.get("risk_hits"):
        lines.append("- None detected")
    (proposal_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return proposal_dir


def render_report(results: list[dict[str, Any]], stamp: str, proposals: list[Path]) -> str:
    lines = [
        f"# Hermes External Source Sweep - {stamp}",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "No repository code was executed. This sweep only cloned/updated sources and inspected metadata/text.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Sources checked | {len(results)} |",
        f"| Review proposals created | {len(proposals)} |",
        f"| High detected risk | {sum(1 for r in results if r.get('detected_risk_level') == 'high')} |",
        f"| Medium detected risk | {sum(1 for r in results if r.get('detected_risk_level') == 'medium')} |",
        "",
        "## Sources",
        "",
        "| Source | Status | Commit | Config Risk | Detected Risk | Package Files |",
        "|---|---|---|---|---|---:|",
    ]
    for item in results:
        lines.append(
            f"| {item.get('id', '')} | {item.get('status', '')} | "
            f"{item.get('commit', '') or 'unknown'} | {item.get('configured_risk_level', 'unknown')} | "
            f"{item.get('detected_risk_level', 'unknown')} ({item.get('risk_score', 0)}) | "
            f"{len(item.get('package_files', []))} |"
        )
    lines.extend(["", "## Proposals", ""])
    if proposals:
        for path in proposals:
            lines.append(f"- {path}")
    else:
        lines.append("- No review proposals created.")
    return "\n".join(lines) + "\n"


def record_memory_trajectory(results: list[dict[str, Any]], proposals: list[Path], jsonl_path: Path, md_path: Path) -> None:
    if os.environ.get("HERMES_MEMORY_DISABLE") == "1":
        return
    root_dir = Path(__file__).resolve().parents[2]
    memory = root_dir / "src/system/memory-fabric.py"
    if not memory.is_file():
        return
    report_hash = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
    status = "completed"
    if any(item.get("status", "").endswith("failed") for item in results):
        status = "partial"
    envelope = {
        "producer": "external-source-sweep",
        "objective": "external-skill-source-discovery",
        "input_hash": report_hash,
        "selected_agent": "external-source-sweep",
        "actions": [
            {
                "type": "read_only_source_sweep",
                "sources_checked": len(results),
                "proposals_created": len(proposals),
            }
        ],
        "predicted_outcome": "candidate sources inspected without installation",
        "observed_outcome": f"sources={len(results)} proposals={len(proposals)}",
        "status": status,
        "failure_class": ",".join(sorted({item.get("status", "") for item in results if item.get("status", "").endswith("failed")})),
        "evidence_refs": [
            {"type": "external-source-jsonl", "path": str(jsonl_path), "sha256": report_hash},
            {"type": "external-source-md", "path": str(md_path)},
            *({"type": "external-source-proposal", "path": str(path)} for path in proposals),
        ],
        "security_classification": "internal",
        "metadata": {
            "source_ids": [item.get("id", "") for item in results],
            "proposal_paths": [str(path) for path in proposals],
            "high_risk": sum(1 for item in results if item.get("detected_risk_level") == "high"),
            "medium_risk": sum(1 for item in results if item.get("detected_risk_level") == "medium"),
        },
    }
    subprocess.run(
        [sys.executable, str(memory), "ingest-trajectory", "--json", json.dumps(envelope, sort_keys=True)],
        cwd=root_dir,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep registered external Hermes skill sources safely.")
    parser.add_argument("--config", default="config/external-skill-sources.json")
    parser.add_argument("--cache-dir", default=".hermes/external-cache")
    parser.add_argument("--reports-dir", default=".hermes/reports")
    parser.add_argument("--proposals-dir", default=".hermes/external-proposals")
    parser.add_argument("--max-sources", type=int, default=0, help="Limit sources checked; 0 means all.")
    parser.add_argument("--offline", action="store_true", help="Do not clone/update; inspect existing cache only.")
    parser.add_argument("--json-only", action="store_true", help="Print JSON results to stdout.")
    args = parser.parse_args()

    config_path = Path(args.config)
    cache_dir = Path(args.cache_dir)
    reports_dir = Path(args.reports_dir)
    proposals_dir = Path(args.proposals_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    config = read_json(config_path)
    sources = config.get("sources", [])
    if args.max_sources > 0:
        sources = sources[: args.max_sources]

    if not shutil.which("git") and not args.offline:
        print("git is required unless --offline is used", file=sys.stderr)
        return 2

    cache_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    proposals_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    proposals: list[Path] = []
    for source in sources:
        repo = source_cache_path(cache_dir, source)
        status, detail = clone_or_update(source, repo, args.offline)
        item = inspect_source(source, repo, status, detail)
        results.append(item)
        if proposal_needed(item):
            proposals.append(write_proposal(item, proposals_dir, stamp))

    jsonl_path = reports_dir / f"external-source-sweep-{stamp}.jsonl"
    md_path = reports_dir / f"external-source-sweep-{stamp}.md"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, sort_keys=True) + "\n")
    md_path.write_text(render_report(results, stamp, proposals), encoding="utf-8")
    record_memory_trajectory(results, proposals, jsonl_path, md_path)

    if args.json_only:
        print(json.dumps({"results": results, "report": str(md_path), "jsonl": str(jsonl_path)}, indent=2))
    else:
        print(f"report={md_path}")
        print(f"jsonl={jsonl_path}")
        print(f"proposals={len(proposals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
