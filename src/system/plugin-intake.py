#!/usr/bin/env python3
"""Governed Agent Plugins 1.0 intake for Hermes.

This is an inspection boundary, not an installer. It discovers fixed plugin
surfaces, validates/fingerprints them, performs bounded static capability scans,
and emits immutable evidence for the existing Trust Gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
REPORT_SCHEMA = "hermes-plugin-intake-v1"
PLUGIN_FIELDS = {"$schema","name","version","description","author","homepage","repository","license","keywords","extensions"}
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SECRET_KEY_RE = re.compile(r"(authorization|api[_-]?key|cookie|credential|password|secret|token)", re.I)
SECRET_VALUE_RE = re.compile(r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]{8,}|sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,})")
PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")
ALLOWED_PLACEHOLDERS = {"PLUGIN_ROOT", "PLUGIN_DATA"}
MAX_FILES = 500
MAX_BYTES = 2_000_000


class IntakeError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def secure_root(root: Path) -> Path:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise IntakeError("plugin root must be a directory")
    return root


def _safe_file(root: Path, path: Path) -> Path:
    if path.is_symlink():
        raise IntakeError(f"symlink is not allowed in plugin intake: {path}")
    resolved = path.resolve(strict=True)
    if not _inside(root, resolved) or not resolved.is_file():
        raise IntakeError(f"plugin path escapes root or is not a file: {path}")
    return resolved


def _safe_relative(root: Path, value: str, *, must_exist: bool = False) -> Path:
    if not value.startswith("./"):
        raise IntakeError("plugin-relative path must begin with ./")
    if "${" in value:
        raise IntakeError("plugin-relative command path cannot contain placeholders")
    target = (root / value[2:]).resolve(strict=must_exist)
    if not _inside(root, target):
        raise IntakeError("plugin-relative path escapes plugin root")
    return target


def _validate_placeholders(value: str) -> None:
    for name in PLACEHOLDER_RE.findall(value):
        if name not in ALLOWED_PLACEHOLDERS:
            raise IntakeError(f"unsupported plugin placeholder: {name}")


def _valid_plugin_name(name: Any) -> bool:
    return isinstance(name, str) and 1 <= len(name) <= 64 and NAME_RE.fullmatch(name) is not None and "--" not in name and ".." not in name


def load_json_object(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 512_000:
        raise IntakeError(f"JSON file too large: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntakeError(f"{path.name} must contain a JSON object")
    return value


def validate_manifest(root: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = root / "plugin.json"
    try:
        _safe_file(root, path)
        manifest = load_json_object(path)
    except (OSError, json.JSONDecodeError, IntakeError) as exc:
        return {}, [f"plugin.json invalid: {exc}"], warnings
    if manifest.get("$schema") != PLUGIN_SCHEMA:
        errors.append("unsupported plugin schema; expected Agent Plugins 1.0 canonical schema")
    if not _valid_plugin_name(manifest.get("name")):
        errors.append("invalid plugin name")
    unknown = sorted(set(manifest) - PLUGIN_FIELDS)
    if unknown:
        warnings.append("unknown plugin manifest fields ignored: " + ",".join(unknown))
    for field in ("version","description","homepage","repository","license"):
        if field in manifest and not isinstance(manifest[field], str):
            errors.append(f"manifest field {field} must be a string")
    if "keywords" in manifest and (not isinstance(manifest["keywords"], list) or any(not isinstance(x, str) for x in manifest["keywords"])):
        errors.append("manifest keywords must be a string list")
    if "author" in manifest:
        author = manifest["author"]
        if not isinstance(author, dict) or set(author) - {"name","email","url"} or any(not isinstance(v, str) for v in author.values()):
            errors.append("manifest author must contain only string name/email/url fields")
    if "extensions" in manifest and not isinstance(manifest["extensions"], dict):
        warnings.append("non-object extensions ignored")
    return manifest, errors, warnings


def discover_skills(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    skills_dir = root / "skills"
    if not skills_dir.exists():
        return [], []
    if skills_dir.is_symlink() or not skills_dir.is_dir():
        return [], ["skills must be a real directory"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for child in sorted(skills_dir.iterdir(), key=lambda p: p.name):
        if child.is_symlink() or not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            safe = _safe_file(root, skill_file)
            text = safe.read_text(encoding="utf-8", errors="replace")[:128_000]
        except (OSError, IntakeError) as exc:
            errors.append(f"skill {child.name} invalid: {exc}")
            continue
        name_match = re.search(r"(?m)^name:\s*([^\n]+)$", text)
        desc_match = re.search(r"(?m)^description:\s*([^\n]+)$", text)
        if not name_match or not desc_match:
            errors.append(f"skill {child.name} missing name/description frontmatter")
            continue
        rows.append({
            "name": name_match.group(1).strip().strip('"\''),
            "description": desc_match.group(1).strip().strip('"\''),
            "path": str(safe.relative_to(root)),
            "sha256": sha256_bytes(safe.read_bytes()),
        })
    return rows, errors


def _validate_remote_url(url: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(url, str) or len(url) > 2048:
        return ["remote MCP URL must be a bounded string"]
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        errors.append("remote MCP URL cannot contain userinfo/fragment and must have a host")
        return errors
    host = parsed.hostname.lower()
    loopback = host in {"localhost","127.0.0.1","::1"}
    if not loopback and parsed.scheme != "https":
        errors.append("remote MCP endpoint must use HTTPS")
    if loopback and parsed.scheme not in {"http","https"}:
        errors.append("loopback MCP endpoint must use HTTP or HTTPS")
    return errors


def _validate_headers(headers: Any) -> list[str]:
    if headers is None:
        return []
    if not isinstance(headers, dict):
        return ["MCP headers must be an object"]
    errors: list[str] = []
    seen: set[str] = set()
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            errors.append("MCP configured headers must be string pairs")
            continue
        low = key.lower()
        if low in seen:
            errors.append("duplicate MCP header name ignoring case")
        seen.add(low)
        if SECRET_KEY_RE.search(key) or SECRET_VALUE_RE.search(value):
            errors.append(f"configured MCP header embeds secret-like material: {key}")
    return errors


def validate_mcp_server(root: Path, name: str, config: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not SERVER_NAME_RE.fullmatch(name) or not isinstance(config, dict):
        return {"name": name, "valid": False, "errors": ["invalid MCP server name/config"], "warnings": []}
    server_type = config.get("type")
    if server_type == "stdio":
        allowed = {"type","command","args","env","cwd"}
        if set(config) - allowed:
            errors.append("stdio MCP server has unknown fields")
        command = config.get("command")
        if not isinstance(command, str) or not command or any(ch.isspace() for ch in command):
            errors.append("stdio command must be one executable token")
        elif command.startswith("./"):
            try:
                _safe_relative(root, command, must_exist=True)
            except (OSError, IntakeError) as exc:
                errors.append(f"plugin-relative command invalid: {exc}")
        elif "/" in command or "\\" in command:
            errors.append("stdio command must be bare executable or plugin-relative ./ path")
        for value in config.get("args", []):
            if not isinstance(value, str): errors.append("stdio args must be strings")
            else:
                try: _validate_placeholders(value)
                except IntakeError as exc: errors.append(str(exc))
        env = config.get("env", {})
        if not isinstance(env, dict):
            errors.append("stdio env must be an object")
        else:
            for key, value in env.items():
                if key in ALLOWED_PLACEHOLDERS:
                    errors.append(f"stdio env cannot override {key}")
                if not isinstance(key, str) or not isinstance(value, str):
                    errors.append("stdio env must contain string pairs")
                    continue
                try: _validate_placeholders(value)
                except IntakeError as exc: errors.append(str(exc))
                if SECRET_KEY_RE.search(key) or SECRET_VALUE_RE.search(value):
                    errors.append(f"stdio env embeds secret-like material: {key}")
        cwd = config.get("cwd")
        if cwd is not None:
            if not isinstance(cwd, str): errors.append("stdio cwd must be a string")
            elif cwd in {"${PLUGIN_ROOT}","${PLUGIN_DATA}"}: pass
            elif cwd.startswith("./"):
                try: _safe_relative(root, cwd, must_exist=False)
                except IntakeError as exc: errors.append(f"plugin-relative cwd invalid: {exc}")
            else: errors.append("stdio cwd must be ./ relative, ${PLUGIN_ROOT}, or ${PLUGIN_DATA}")
    elif server_type in {"streamable-http","sse"}:
        allowed = {"type","url","headers"}
        if set(config) - allowed: errors.append("remote MCP server has unknown fields")
        errors.extend(_validate_remote_url(config.get("url")))
        errors.extend(_validate_headers(config.get("headers")))
        if server_type == "sse": warnings.append("SSE transport is deprecated; prefer streamable-http")
    else:
        errors.append("unsupported MCP server type")
    return {"name": name, "type": server_type, "valid": not errors, "errors": errors, "warnings": warnings}


def discover_mcp(root: Path) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    path = root / "mcp.json"
    if not path.exists():
        return [], [], []
    errors: list[str] = []
    warnings: list[str] = []
    try:
        _safe_file(root, path); value = load_json_object(path)
    except (OSError, json.JSONDecodeError, IntakeError) as exc:
        return [], [f"mcp.json invalid: {exc}"], warnings
    if value.get("$schema") != MCP_SCHEMA: errors.append("unsupported mcp.json schema")
    if set(value) - {"$schema","mcpServers"}: errors.append("mcp.json has unknown top-level fields")
    servers = value.get("mcpServers")
    if not isinstance(servers, dict): return [], errors + ["mcpServers must be an object"], warnings
    rows = [validate_mcp_server(root, name, config) for name, config in sorted(servers.items())]
    for row in rows: warnings.extend(row.get("warnings", []))
    return rows, errors, warnings


def _scan_capabilities(root: Path) -> tuple[list[str], int, list[str]]:
    patterns = {
        "credential_access": re.compile(r"(?i)(\.ssh/|id_rsa|aws/credentials|api[_-]?key|password|secret|token)"),
        "network": re.compile(r"(?i)\b(curl|wget|requests\.|urllib\.|fetch\(|https?://|socket\.)"),
        "filesystem_write": re.compile(r"(?i)(\brm\s|unlink\(|write_text\(|write_bytes\(|open\([^\n]*['\"]?[wa]['\"]?)"),
        "process_spawn": re.compile(r"(?i)(subprocess\.|os\.system\(|child_process|exec\(|spawn\()"),
        "shell_execution": re.compile(r"(?im)^#!.*\b(sh|bash|zsh)\b|\b(shell=True|bash\s+-c|sh\s+-c)"),
    }
    weights = {"credential_access":40,"network":15,"filesystem_write":15,"process_spawn":20,"shell_execution":20}
    found: set[str] = set(); scanned = 0; total = 0; warnings: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda p: str(p)):
        if scanned >= MAX_FILES or total >= MAX_BYTES: break
        if path.is_symlink():
            warnings.append(f"symlink skipped: {path.relative_to(root)}"); continue
        if not path.is_file(): continue
        try:
            safe=_safe_file(root,path); size=safe.stat().st_size
            if size > 256_000: continue
            raw=safe.read_bytes(); total += len(raw); scanned += 1
            text=raw.decode("utf-8", errors="ignore")
        except (OSError, IntakeError): continue
        for name, pattern in patterns.items():
            if pattern.search(text): found.add(name)
    risk=min(100,sum(weights[name] for name in found))
    return sorted(found), risk, warnings


def inspect_skill_candidate(root: Path) -> dict[str, Any]:
    """Inspect one standalone skill using the existing plugin intake scanner.

    Standalone skills are always candidates. Static inspection can raise risk or
    reject an unsafe package, but it never grants installation/activation.
    """
    root = secure_root(Path(root))
    for path in root.rglob("*"):
        if path.is_symlink():
            raise IntakeError(f"symlink is not allowed in skill intake: {path}")
    skill_file = root / "SKILL.md"
    try:
        safe = _safe_file(root, skill_file)
        text = safe.read_text(encoding="utf-8", errors="replace")[:128_000]
    except (OSError, IntakeError) as exc:
        raise IntakeError(f"SKILL.md invalid: {exc}") from exc
    name_match = re.search(r"(?m)^name:\s*([^\n]+)$", text)
    desc_match = re.search(r"(?m)^description:\s*([^\n]+)$", text)
    errors: list[str] = []
    if not name_match:
        errors.append("SKILL.md missing name frontmatter")
    if not desc_match:
        errors.append("SKILL.md missing description frontmatter")
    capabilities, risk_score, warnings = _scan_capabilities(root)
    report = {
        "schema_version": "hermes-skill-intake-v1",
        "state": "CANDIDATE",
        "valid": not errors,
        "name": name_match.group(1).strip().strip('"\'') if name_match else root.name,
        "description": desc_match.group(1).strip().strip('"\'') if desc_match else "",
        "skill_file": str(safe),
        "skill_sha256": sha256_bytes(safe.read_bytes()),
        "package_hash": package_hash(root),
        "observed_capabilities": capabilities,
        "risk_score": risk_score,
        "errors": errors,
        "warnings": warnings,
        "activation_allowed": False,
        "next_gate": "trust-gate",
    }
    return report


def package_hash(root: Path) -> str:
    rows: list[tuple[str,str]] = []
    count=0; total=0
    for path in sorted(root.rglob("*"), key=lambda p: str(p)):
        if path.is_symlink():
            rows.append((str(path.relative_to(root)),"SYMLINK_REJECTED")); continue
        if not path.is_file(): continue
        safe=_safe_file(root,path); raw=safe.read_bytes(); count += 1; total += len(raw)
        if count > MAX_FILES or total > MAX_BYTES: raise IntakeError("plugin exceeds bounded intake limits")
        rows.append((str(safe.relative_to(root)),hashlib.sha256(raw).hexdigest()))
    return sha256_bytes(canonical_json(rows))


def inspect_plugin(root: Path) -> dict[str, Any]:
    root=secure_root(Path(root))
    manifest, errors, warnings=validate_manifest(root)
    skills, skill_errors=discover_skills(root); errors.extend(skill_errors)
    servers, mcp_errors, mcp_warnings=discover_mcp(root); errors.extend(mcp_errors); warnings.extend(mcp_warnings)
    if any(not row.get("valid",False) for row in servers): errors.append("one or more MCP server entries failed validation")
    caps, risk, scan_warnings=_scan_capabilities(root); warnings.extend(scan_warnings)
    try: digest=package_hash(root)
    except IntakeError as exc: errors.append(str(exc)); digest=""
    if any(row.get("type")=="sse" for row in servers): risk=min(100,risk+10)
    report_id="plugin_" + (digest.split(":",1)[-1][:24] if digest else hashlib.sha256(str(root).encode()).hexdigest()[:24])
    return {
        "schema_version": REPORT_SCHEMA,
        "report_id": report_id,
        "state": "DISCOVERED",
        "valid": not errors,
        "activation_allowed": False,
        "next_gate": "trust-gate",
        "plugin_root": str(root),
        "manifest": manifest,
        "skills": skills,
        "mcp_servers": servers,
        "observed_capabilities": caps,
        "risk_score": risk,
        "package_hash": digest,
        "errors": errors,
        "warnings": sorted(set(warnings)),
    }


def write_report_create_only(report: dict[str, Any], reports_dir: Path) -> Path:
    reports_dir=Path(reports_dir); reports_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if reports_dir.is_symlink(): raise IntakeError("reports directory cannot be a symlink")
    path=reports_dir / f"{report['report_id']}.json"
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,"O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    fd=os.open(path,flags,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            json.dump(report,handle,indent=2,sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True); raise
    return path


def trust_gate_command(root: Path, report: dict[str, Any], trust_gate_path: Path) -> list[str]:
    if not report.get("valid"): raise IntakeError("invalid plugin cannot be handed to Trust Gate")
    return [sys.executable,str(trust_gate_path),str(Path(root).resolve()),"--type","package","--state","candidate"]


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("plugin_root"); p.add_argument("--reports-dir",default=".hermes/reports/plugin-intake"); p.add_argument("--handoff",action="store_true"); p.add_argument("--trust-gate",default="src/system/trust-gate.py"); return p


def main(argv: list[str] | None=None) -> int:
    args=parser().parse_args(argv)
    try:
        root=Path(args.plugin_root); report=inspect_plugin(root); path=write_report_create_only(report,Path(args.reports_dir))
        result={"report":str(path),"valid":report["valid"],"state":report["state"],"risk_score":report["risk_score"],"activation_allowed":False,"next_gate":report["next_gate"]}
        if args.handoff and report["valid"]: result["trust_gate_command"]=trust_gate_command(root,report,Path(args.trust_gate))
        print(json.dumps(result,indent=2,sort_keys=True)); return 0 if report["valid"] else 2
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print(json.dumps({"error":str(exc)},sort_keys=True),file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
