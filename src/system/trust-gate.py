#!/usr/bin/env python3
"""Hermes Trust Gate.

Read-only analyzer for external skills, MCP servers, packages, model artifacts,
and capability bundles. It never executes candidate code. It emits local
evidence artifacts that can be used by governance/promotion workflows.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BINARY_SUFFIXES = {
    ".apk", ".bin", ".dylib", ".dll", ".exe", ".jar", ".o", ".pyc", ".so",
    ".wasm", ".zip", ".gz", ".xz", ".7z", ".rar", ".tar", ".tgz",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf",
}

PACKAGE_FILES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt",
    "poetry.lock", "uv.lock", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "Dockerfile", "docker-compose.yml", "Makefile", "install.sh", "setup.sh",
}

RISK_PATTERNS: dict[str, list[str]] = {
    "credential_access": [
        r"api[_-]?key", r"secret[_-]?key", r"password", r"token", r"cookie",
        r"credential", r"stealer", r"session", r"\.ssh", r"keychain",
    ],
    "prompt_injection": [
        r"ignore (all )?(previous|prior) instructions", r"reveal (the )?secret",
        r"exfiltrat", r"system prompt", r"developer message", r"bypass policy",
        r"disable safety", r"do not tell the user",
    ],
    "installer_hooks": [
        r"postinstall", r"preinstall", r"\bprepare\b", r"curl\s+[^|]*\|",
        r"wget\s+[^|]*\|", r"bash\s+-c", r"chmod\s+\+x", r"\bsudo\b",
    ],
    "persistence": [
        r"launchagent", r"launchdaemon", r"systemd", r"crontab", r"autorun",
        r"schtasks", r"startup folder", r"boot receiver", r"foreground service",
    ],
    "stealth": [
        r"stealth", r"evasion", r"anti[- ]debug", r"obfuscat", r"hide process",
        r"disable logging", r"clear logs",
    ],
    "network_exfil": [
        r"webhook", r"pastebin", r"ngrok", r"telegram bot", r"discord webhook",
        r"sendBeacon", r"socket\.connect", r"reverse shell",
    ],
    "public_scanning": [
        r"\bnmap\b", r"\bmasscan\b", r"\bshodan\b", r"\bcensys\b",
        r"public target", r"port scan", r"vulnerability scan",
    ],
    "exploit_execution": [
        r"exploit module", r"metasploit", r"meterpreter", r"payload",
        r"rce", r"cve-\d{4}-\d+", r"shellcode",
    ],
    "mcp_write_surface": [
        r"delete_file", r"write_file", r"send_email", r"post_message",
        r"execute_command", r"run_shell", r"browser_profile", r"install_package",
    ],
}

HARD_BLOCK_CATEGORIES = {
    "credential_access",
    "prompt_injection",
    "stealth",
    "network_exfil",
    "exploit_execution",
}


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-") or "candidate"


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "ssh", "git"} or value.startswith("git@")


def clone_url(url: str, cache_dir: Path) -> tuple[Path, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = slugify(url.replace("://", "-").replace("/", "-").replace(":", "-"))
    dest = cache_dir / name
    if dest.exists() and (dest / ".git").is_dir():
        code, out, err = run(["git", "pull", "--ff-only"], cwd=dest)
        if code != 0:
            return dest, f"update_failed:{err or out}"
        return dest, "updated"
    if dest.exists():
        return dest, "cache_path_exists_not_git"
    code, out, err = run(["git", "clone", "--depth", "1", url, str(dest)])
    if code != 0:
        return dest, f"clone_failed:{err or out}"
    return dest, "cloned"


def iter_files(root: Path, max_files: int) -> list[Path]:
    out: list[Path] = []
    if root.is_file():
        return [root]
    for path in root.rglob("*"):
        if len(out) >= max_files:
            break
        if ".git" in path.parts or not path.is_file():
            continue
        out.append(path)
    return out


def read_text(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_meta(root: Path) -> dict[str, str]:
    if root.is_file():
        root = root.parent
    if not (root / ".git").is_dir():
        return {}
    fields = {
        "commit": ["rev-parse", "HEAD"],
        "short_commit": ["rev-parse", "--short=12", "HEAD"],
        "commit_date": ["log", "-1", "--format=%cI"],
        "branch": ["branch", "--show-current"],
        "signed_commit_status": ["log", "-1", "--format=%G?"],
        "author": ["log", "-1", "--format=%an <%ae>"],
    }
    meta: dict[str, str] = {}
    for key, args in fields.items():
        code, out, _ = run(["git", *args], cwd=root)
        if code == 0:
            meta[key] = out
    return meta


def package_script_flags(root: Path) -> list[str]:
    package = root / "package.json"
    if not package.is_file():
        return []
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["package_json_parse_failed"]
    flags: list[str] = []
    for name, value in data.get("scripts", {}).items():
        lowered = str(value).lower()
        if name in {"preinstall", "postinstall", "prepare"}:
            flags.append(f"npm_lifecycle_script:{name}")
        if re.search(r"(curl|wget|bash|sh|sudo|chmod|powershell|python)\b", lowered):
            flags.append(f"npm_shell_script:{name}")
    return sorted(set(flags))


def negated_security_context(line: str) -> bool:
    return bool(re.search(
        r"\b(do not|don't|never|forbid|forbidden|without approval|requires human approval|human approval is required|blocked|must ask before)\b",
        line,
    ))


def risky_line_context(category: str, line: str) -> bool:
    if category in {"prompt_injection", "installer_hooks", "persistence", "stealth"}:
        return True
    if negated_security_context(line):
        return False
    if category == "credential_access":
        return bool(re.search(
            r"\b(read|collect|capture|export|send|upload|exfiltrat|dump|steal|use|load|sync|copy|reveal|print|get)\b",
            line,
        ))
    if category == "network_exfil":
        return bool(re.search(r"\b(send|upload|post|exfiltrat|webhook|reverse shell|connect)\b", line))
    if category in {"public_scanning", "exploit_execution", "mcp_write_surface"}:
        return not negated_security_context(line)
    return True


def inspect_candidate(root: Path, candidate_type: str, max_files: int, max_bytes: int) -> dict[str, Any]:
    files = iter_files(root, max_files)
    risk_hits: list[dict[str, str]] = []
    risk_counts: dict[str, int] = {}
    package_files: list[str] = []
    binary_files: list[str] = []
    license_files: list[str] = []
    file_hashes: list[dict[str, str]] = []
    total_read = 0

    for path in files:
        rel = path.name if root.is_file() else str(path.relative_to(root))
        suffix = path.suffix.lower()
        size = path.stat().st_size
        if path.name in PACKAGE_FILES or rel in PACKAGE_FILES:
            package_files.append(rel)
        if path.name.lower().startswith(("license", "copying")):
            license_files.append(rel)
        if suffix in BINARY_SUFFIXES:
            binary_files.append(rel)
        if len(file_hashes) < 100:
            file_hashes.append({"path": rel, "sha256": sha256_file(path), "bytes": str(size)})
        if suffix in BINARY_SUFFIXES or total_read >= max_bytes:
            continue
        text = read_text(path, min(50_000, max_bytes - total_read))
        total_read += len(text.encode("utf-8", errors="ignore"))
        lowered = f"{rel}\n{text}".lower()
        for category, patterns in RISK_PATTERNS.items():
            for pattern in patterns:
                for line in lowered.splitlines():
                    if not re.search(pattern, line):
                        continue
                    if not risky_line_context(category, line):
                        continue
                    risk_counts[category] = risk_counts.get(category, 0) + 1
                    if len(risk_hits) < 80:
                        risk_hits.append({
                            "category": category,
                            "path": rel,
                            "pattern": pattern,
                        })
                    break

    script_flags = package_script_flags(root if root.is_dir() else root.parent)
    for flag in script_flags:
        risk_counts["installer_hooks"] = risk_counts.get("installer_hooks", 0) + 1
        risk_hits.append({"category": "installer_hooks", "path": "package.json", "pattern": flag})

    hard_hits = sorted(set(HARD_BLOCK_CATEGORIES) & set(risk_counts))
    score = 0
    weights = {
        "credential_access": 20,
        "prompt_injection": 18,
        "installer_hooks": 12,
        "persistence": 14,
        "stealth": 20,
        "network_exfil": 18,
        "public_scanning": 12,
        "exploit_execution": 20,
        "mcp_write_surface": 10,
    }
    for category, count in risk_counts.items():
        score += min(count, 5) * weights.get(category, 5)
    if binary_files:
        score += min(len(binary_files), 10) * 4
    if package_files:
        score += 8
    if not license_files and candidate_type in {"skill", "mcp", "package"}:
        score += 6

    verdict = "allow"
    next_state = "trusted_candidate"
    reasons: list[str] = []
    if hard_hits and score >= 40:
        verdict = "block"
        next_state = "quarantined"
        reasons.append(f"hard-risk-categories:{','.join(hard_hits)}")
    elif score >= 60 or "installer_hooks" in risk_counts or "mcp_write_surface" in risk_counts:
        verdict = "quarantine"
        next_state = "quarantined"
        reasons.append("requires-isolated-review")
    elif score >= 15 or package_files or binary_files or not license_files:
        verdict = "review"
        next_state = "candidate_review"
        reasons.append("manual-review-required")
    else:
        reasons.append("low-risk-static-review")

    return {
        "candidate_type": candidate_type,
        "path": str(root),
        "file_count_scanned": len(files),
        "bytes_read": total_read,
        "package_files": sorted(set(package_files)),
        "binary_files": sorted(set(binary_files))[:50],
        "license_files": sorted(set(license_files)),
        "git": git_meta(root),
        "risk_score": score,
        "risk_counts": dict(sorted(risk_counts.items())),
        "risk_hits": risk_hits[:80],
        "verdict": verdict,
        "next_state": next_state,
        "reasons": reasons,
        "file_hashes": file_hashes,
    }


def sign_payload(payload: dict[str, Any], secret: str | None) -> dict[str, str]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    if secret:
        sig = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        return {"algorithm": "hmac-sha256", "payload_sha256": digest, "signature": sig}
    return {"algorithm": "sha256", "payload_sha256": digest, "signature": digest}


def render_markdown(report: dict[str, Any]) -> str:
    analysis = report["analysis"]
    lines = [
        f"# Hermes Trust Gate Report - {report['id']}",
        "",
        f"Generated: {report['generated_at']}",
        f"Candidate: `{report['candidate']}`",
        f"Candidate type: `{analysis['candidate_type']}`",
        f"Evaluation state: `{report['input_state']}` -> `{analysis['next_state']}`",
        f"Verdict: `{analysis['verdict']}`",
        f"Risk score: `{analysis['risk_score']}`",
        "",
        "No candidate code, installer, package script, model artifact, or MCP server was executed.",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in analysis["reasons"])
    lines.extend([
        "",
        "## Static Evidence",
        "",
        f"- Files scanned: {analysis['file_count_scanned']}",
        f"- Bytes read: {analysis['bytes_read']}",
        f"- Package files: {', '.join(analysis['package_files']) or 'none'}",
        f"- Binary/model/archive files: {', '.join(analysis['binary_files']) or 'none'}",
        f"- License files: {', '.join(analysis['license_files']) or 'none'}",
        "",
        "## Risk Counts",
        "",
    ])
    if analysis["risk_counts"]:
        for category, count in analysis["risk_counts"].items():
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Risk Hits", ""])
    if analysis["risk_hits"]:
        for hit in analysis["risk_hits"][:30]:
            lines.append(f"- {hit['category']} :: `{hit['path']}` :: `{hit['pattern']}`")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Signature",
        "",
        f"- Algorithm: {report['signature']['algorithm']}",
        f"- Payload SHA256: `{report['signature']['payload_sha256']}`",
        f"- Signature: `{report['signature']['signature']}`",
    ])
    return "\n".join(lines) + "\n"


def record_memory_trajectory(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    if os.environ.get("HERMES_MEMORY_DISABLE") == "1":
        return
    root_dir = Path(__file__).resolve().parents[2]
    memory = root_dir / "src/system/memory-fabric.py"
    if not memory.is_file():
        return
    analysis = report["analysis"]
    evidence_refs = [
        {"type": "trust-gate-json", "path": str(json_path), "sha256": report["signature"]["payload_sha256"]},
        {"type": "trust-gate-md", "path": str(md_path)},
    ]
    envelope = {
        "producer": "trust-gate",
        "objective": "candidate-trust-scan",
        "input_hash": report["signature"]["payload_sha256"],
        "selected_agent": "trust-gate",
        "actions": [
            {
                "type": "static_scan",
                "candidate": report["candidate"],
                "candidate_type": analysis["candidate_type"],
                "input_state": report["input_state"],
            }
        ],
        "predicted_outcome": analysis["next_state"],
        "observed_outcome": f"verdict={analysis['verdict']} risk_score={analysis['risk_score']}",
        "status": analysis["verdict"],
        "failure_class": ",".join(sorted(analysis["risk_counts"])),
        "evidence_refs": evidence_refs,
        "security_classification": "internal",
        "metadata": {
            "candidate": report["candidate"],
            "candidate_type": analysis["candidate_type"],
            "fetch_status": report["fetch_status"],
            "next_state": analysis["next_state"],
            "risk_score": analysis["risk_score"],
            "safety_claim": analysis["verdict"] == "allow",
            "signature": report["signature"],
        },
    }
    proc = subprocess.run(
        [sys.executable, str(memory), "ingest-trajectory", "--json", json.dumps(envelope, sort_keys=True)],
        cwd=root_dir,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 and analysis["verdict"] == "allow" and os.environ.get("HERMES_MEMORY_FAIL_CLOSED_TRUST") == "1":
        raise SystemExit(f"Trust Gate memory persistence failed: {proc.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Trust Gate static analyzer.")
    parser.add_argument("candidate", help="Local path or git URL to evaluate.")
    parser.add_argument("--type", default="skill", choices=["skill", "mcp", "package", "model", "capability"])
    parser.add_argument("--state", default="candidate", choices=["candidate", "quarantined", "trusted", "installed", "active"])
    parser.add_argument("--reports-dir", default=".hermes/reports/trust-gate")
    parser.add_argument("--cache-dir", default=".hermes/trust-gate-cache")
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    candidate = args.candidate
    fetch_status = "local"
    root = Path(candidate)
    if is_url(candidate):
        if not shutil.which("git"):
            print("git is required to evaluate URL candidates", file=sys.stderr)
            return 2
        root, fetch_status = clone_url(candidate, Path(args.cache_dir))
    elif not root.exists():
        print(f"candidate not found: {candidate}", file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_id = f"{stamp}-{slugify(candidate)[:80]}"
    analysis = inspect_candidate(root, args.type, args.max_files, args.max_bytes)
    unsigned = {
        "id": report_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidate": candidate,
        "fetch_status": fetch_status,
        "input_state": args.state,
        "analysis": analysis,
    }
    secret = os.environ.get("HERMES_TRUST_GATE_SECRET")
    report = {**unsigned, "signature": sign_payload(unsigned, secret)}

    json_path = reports_dir / f"{report_id}.json"
    md_path = reports_dir / f"{report_id}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    record_memory_trajectory(report, json_path, md_path)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"verdict={analysis['verdict']}")
        print(f"next_state={analysis['next_state']}")
        print(f"risk_score={analysis['risk_score']}")
        print(f"report={md_path}")
        print(f"json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
