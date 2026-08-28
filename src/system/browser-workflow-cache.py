#!/usr/bin/env python3
"""Governed deterministic browser workflow compiler/cache for Hermes.

Successful evidence-backed browser traces can be compiled into immutable,
parameterized Playwright workflows. Dry-runs are local and side-effect free.
Live replay requires the existing Hermes containment gateway capability before
Playwright starts and never performs cross-site navigation or sensitive-field
automation.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "hermes-browser-workflow-v1"
ALLOWED_ACTIONS = {"navigate", "fill", "click", "assert_url", "assert_text"}
WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
PARAM_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_.-]{0,79})\}\}")
SENSITIVE_RE = re.compile(
    r"(password|passcode|otp|one.?time|2fa|captcha|recaptcha|hcaptcha|ssn|social.?security|credit.?card|card.?number|cvv|payment|bank|routing|upload|attachment|file|login|username|api.?key|secret|token|credential)",
    re.I,
)
DANGEROUS_CLICK_RE = re.compile(
    r"(delete|remove|purchase|buy|checkout|pay|unsubscribe|logout|sign.?out|close.?account|confirm.?order|place.?order|transfer|wire)",
    re.I,
)
COMMON_MULTI_LABEL_PUBLIC_SUFFIXES = frozenset(
    {"ac.uk", "co.jp", "co.nz", "co.uk", "com.au", "com.br", "com.cn", "com.mx", "com.sg", "gov.uk", "net.au", "net.nz", "net.uk", "org.au", "org.nz", "org.uk"}
)
SHARED_HOSTING_SUFFIXES = frozenset(
    {
        "github.io",
        "pages.dev",
        "vercel.app",
        "netlify.app",
        "workers.dev",
        "web.app",
        "firebaseapp.com",
        "appspot.com",
        "azurewebsites.net",
    }
)


class WorkflowSecurityError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def normalize_classification(value: str | None) -> str:
    raw = (value or "INTERNAL").strip().replace("-", "_").replace(" ", "_").upper()
    aliases = {
        "PUBLIC": "PUBLIC", "INTERNAL": "INTERNAL", "CONFIDENTIAL": "CONFIDENTIAL",
        "LEGAL": "LEGAL_PRIVILEGED", "LEGAL_PRIVILEGED": "LEGAL_PRIVILEGED",
        "FINANCIAL": "FINANCIAL", "CREDENTIAL": "CREDENTIAL", "CREDENTIALS": "CREDENTIAL",
        "SECURITY": "SECURITY_SENSITIVE", "SECURITY_SENSITIVE": "SECURITY_SENSITIVE", "RESTRICTED": "SECURITY_SENSITIVE",
    }
    if raw not in aliases:
        raise WorkflowSecurityError(f"unsupported security classification: {value}")
    return aliases[raw]


def registrable_domain(host: str) -> str:
    host = host.lower().rstrip(".")
    if not host:
        return ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host
    suffix = ".".join(parts[-2:])
    if suffix in COMMON_MULTI_LABEL_PUBLIC_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    if suffix in SHARED_HOSTING_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def origin(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise WorkflowSecurityError("URL must contain a hostname")
    default_port = 443
    port = parsed.port or default_port
    suffix = "" if port == default_port else f":{port}"
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{parsed.scheme}://{bracketed}{suffix}"


def validate_url_syntax(url: str) -> None:
    if not isinstance(url, str) or len(url) > 2048:
        raise WorkflowSecurityError("URL must be a bounded string")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise WorkflowSecurityError("browser workflows require https")
    if parsed.username or parsed.password:
        raise WorkflowSecurityError("browser workflow URLs must not embed credentials")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise WorkflowSecurityError("browser workflow URL must contain a hostname")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
        raise WorkflowSecurityError(f"private or non-routable browser target is blocked: {address}")


def validate_live_public_url(url: str) -> None:
    validate_url_syntax(url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WorkflowSecurityError(f"browser hostname resolution failed: {host}: {exc}") from exc
    addresses: list[ipaddress._BaseAddress] = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not addresses:
        raise WorkflowSecurityError("browser hostname did not resolve")
    for address in addresses:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise WorkflowSecurityError(f"private or non-routable browser target is blocked: {address}")


def is_same_site(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower().rstrip(".")
    candidate_host = (urlparse(candidate_url).hostname or "").lower().rstrip(".")
    if not base_host or not candidate_host:
        return False
    if candidate_host == base_host or candidate_host.endswith(f".{base_host}"):
        return True
    return registrable_domain(candidate_host) == registrable_domain(base_host)


def _validate_selector(selector: Any, *, click: bool = False) -> str:
    if not isinstance(selector, str) or not selector.strip() or len(selector) > 500:
        raise WorkflowSecurityError("selector must be a non-empty string <= 500 characters")
    if SENSITIVE_RE.search(selector):
        raise WorkflowSecurityError(f"sensitive browser field/action is blocked: {selector}")
    if click and DANGEROUS_CLICK_RE.search(selector):
        raise WorkflowSecurityError(f"dangerous browser click is blocked: {selector}")
    return selector


def _validate_template(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 10000:
        raise WorkflowSecurityError("workflow text values must be strings <= 10000 characters")
    for name in PARAM_RE.findall(value):
        if SENSITIVE_RE.search(name):
            raise WorkflowSecurityError(f"sensitive browser parameter is blocked: {name}")
    return value


def validate_actions(source_url: str, actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list) or not 1 <= len(actions) <= 100:
        raise WorkflowSecurityError("workflow actions must contain 1..100 steps")
    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(actions):
        if not isinstance(raw, dict):
            raise WorkflowSecurityError(f"action {index} must be an object")
        action_type = str(raw.get("type") or "")
        if action_type not in ALLOWED_ACTIONS:
            raise WorkflowSecurityError(f"action {index} type is not allowed: {action_type}")
        action: dict[str, Any] = {"type": action_type}
        if action_type == "navigate":
            target = _validate_template(raw.get("url"))
            if PARAM_RE.search(target):
                raise WorkflowSecurityError("navigation URLs cannot be parameterized")
            validate_url_syntax(target)
            if not is_same_site(source_url, target):
                raise WorkflowSecurityError(f"cross-site navigation is blocked: {target}")
            action["url"] = target
        elif action_type == "fill":
            action["selector"] = _validate_selector(raw.get("selector"))
            action["value"] = _validate_template(raw.get("value"))
        elif action_type == "click":
            action["selector"] = _validate_selector(raw.get("selector"), click=True)
        elif action_type == "assert_url":
            target = _validate_template(raw.get("url"))
            if PARAM_RE.search(target):
                raise WorkflowSecurityError("asserted URLs cannot be parameterized")
            validate_url_syntax(target)
            if not is_same_site(source_url, target):
                raise WorkflowSecurityError(f"cross-site URL assertion is blocked: {target}")
            action["url"] = target
        elif action_type == "assert_text":
            action["selector"] = _validate_selector(raw.get("selector"))
            action["contains"] = _validate_template(raw.get("contains"))
        validated.append(action)
    return validated


def _safe_workflow_path(root: Path, workflow_id: str) -> Path:
    if not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise WorkflowSecurityError("unsafe workflow_id")
    root = root.expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise WorkflowSecurityError("workflow root must not be a symlink")
    return root / f"{workflow_id}.json"


def compile_workflow(trace: dict[str, Any], root: Path) -> dict[str, Any]:
    if not isinstance(trace, dict):
        raise WorkflowSecurityError("browser trace must be an object")
    workflow_id = str(trace.get("workflow_id") or "")
    if str(trace.get("status") or "").lower() != "success":
        raise WorkflowSecurityError("only successful browser traces can be compiled")
    evidence_refs = trace.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise WorkflowSecurityError("successful browser trace requires evidence_refs")
    source_url = str(trace.get("source_url") or "")
    validate_url_syntax(source_url)
    classification = normalize_classification(str(trace.get("security_classification") or "INTERNAL"))
    actions = validate_actions(source_url, trace.get("actions"))
    parameter_names = sorted({name for action in actions for value in action.values() if isinstance(value, str) for name in PARAM_RE.findall(value)})
    workflow = {
        "schema_version": SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "source_url": source_url,
        "origin": origin(source_url),
        "registrable_domain": registrable_domain((urlparse(source_url).hostname or "").lower()),
        "security_classification": classification,
        "actions": actions,
        "parameter_names": parameter_names,
        "evidence_refs_hash": "sha256:" + sha256_json(evidence_refs),
        "compiled_from_trace_hash": "sha256:" + sha256_json(trace),
    }
    workflow_hash = "sha256:" + sha256_json(workflow)
    workflow["workflow_hash"] = workflow_hash
    path = _safe_workflow_path(root, workflow_id)
    if path.exists():
        if path.is_symlink():
            raise WorkflowSecurityError("workflow path must not be a symlink")
        existing = json.loads(path.read_text(encoding="utf-8"))
        validate_workflow(existing)
        if existing.get("workflow_hash") != workflow_hash:
            raise WorkflowSecurityError("workflow_id already exists with different immutable content")
        return {"workflow_id": workflow_id, "workflow_hash": workflow_hash, "workflow_path": str(path), "created": False}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, (json.dumps(workflow, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"workflow_id": workflow_id, "workflow_hash": workflow_hash, "workflow_path": str(path), "created": True}


def validate_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    if workflow.get("schema_version") != SCHEMA_VERSION:
        raise WorkflowSecurityError("unsupported workflow schema")
    workflow_id = str(workflow.get("workflow_id") or "")
    if not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise WorkflowSecurityError("unsafe workflow_id")
    source_url = str(workflow.get("source_url") or "")
    validate_url_syntax(source_url)
    if workflow.get("origin") != origin(source_url):
        raise WorkflowSecurityError("workflow origin mismatch")
    classification = normalize_classification(str(workflow.get("security_classification") or ""))
    actions = validate_actions(source_url, workflow.get("actions"))
    expected_params = sorted({name for action in actions for value in action.values() if isinstance(value, str) for name in PARAM_RE.findall(value)})
    if workflow.get("parameter_names") != expected_params:
        raise WorkflowSecurityError("workflow parameter list mismatch")
    base = {k: v for k, v in workflow.items() if k != "workflow_hash"}
    expected_hash = "sha256:" + sha256_json(base)
    if workflow.get("workflow_hash") != expected_hash:
        raise WorkflowSecurityError("workflow hash mismatch")
    if classification == "CREDENTIAL":
        raise WorkflowSecurityError("credential-class browser workflows are prohibited")
    return workflow


def _render_text(value: str, params: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise WorkflowSecurityError(f"missing workflow parameter: {name}")
        if SENSITIVE_RE.search(name):
            raise WorkflowSecurityError(f"sensitive browser parameter is blocked: {name}")
        rendered = params[name]
        if not isinstance(rendered, (str, int, float, bool)):
            raise WorkflowSecurityError(f"workflow parameter must be scalar: {name}")
        text = str(rendered)
        if len(text) > 10000:
            raise WorkflowSecurityError(f"workflow parameter too large: {name}")
        return text
    return PARAM_RE.sub(replace, value)


def render_workflow(workflow: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    validate_workflow(workflow)
    if not isinstance(params, dict):
        raise WorkflowSecurityError("workflow parameters must be an object")
    rendered: list[dict[str, Any]] = []
    for action in workflow["actions"]:
        item: dict[str, Any] = {}
        for key, value in action.items():
            item[key] = _render_text(value, params) if isinstance(value, str) else value
        rendered.append(item)
    return {"workflow_id": workflow["workflow_id"], "steps": rendered}


def build_replay_receipt(workflow: dict[str, Any], rendered_steps: list[dict[str, Any]], *, status: str, final_url: str, duration_ms: int | float) -> dict[str, Any]:
    validate_workflow(workflow)
    public_steps: list[dict[str, Any]] = []
    hashes: list[str] = []
    for step in rendered_steps:
        hashes.append("sha256:" + sha256_json(step))
        public = {"type": step.get("type", "")}
        if "selector" in step:
            public["selector_hash"] = "sha256:" + hashlib.sha256(str(step["selector"]).encode()).hexdigest()
        if step.get("type") in {"navigate", "assert_url"}:
            public["url"] = step.get("url", "")
        public_steps.append(public)
    receipt = {
        "schema_version": "hermes-browser-replay-receipt-v1",
        "workflow_id": workflow["workflow_id"],
        "workflow_hash": workflow["workflow_hash"],
        "status": status,
        "source_url": workflow["source_url"],
        "final_url": final_url,
        "duration_ms": round(float(duration_ms), 3),
        "rendered_step_hashes": hashes,
        "public_steps": public_steps,
    }
    receipt["receipt_hash"] = "sha256:" + sha256_json(receipt)
    return receipt


def require_execution_authorization(workflow: dict[str, Any], *, capability_path: Path | None, principal: str, data_class: str, repo_root: Path) -> None:
    validate_workflow(workflow)
    if capability_path is None:
        raise WorkflowSecurityError("live browser replay requires a containment capability")
    if not capability_path.is_file() or capability_path.is_symlink():
        raise WorkflowSecurityError("containment capability file is missing or unsafe")
    gateway = repo_root / "src/system/containment-gateway.sh"
    if not gateway.is_file():
        raise WorkflowSecurityError("Hermes containment gateway is unavailable")
    command = [
        "bash", str(gateway), "verify", "--token-stdin",
        "--principal", principal,
        "--tool", "browser:workflow",
        "--destination", str(workflow["origin"]),
        "--resource", f"workflow:{workflow['workflow_id']}",
        "--data-class", normalize_classification(data_class),
    ]
    proc = subprocess.run(command, input=capability_path.read_text(encoding="utf-8"), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=repo_root, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "containment verification denied").strip()[:300]
        raise WorkflowSecurityError(f"browser replay containment authorization denied: {detail}")


async def replay_with_playwright(workflow: dict[str, Any], steps: list[dict[str, Any]], *, headed: bool, timeout_ms: int) -> tuple[str, list[dict[str, Any]]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise WorkflowSecurityError("Playwright is required for live browser workflow replay") from exc
    source_url = workflow["source_url"]
    assertions: list[dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            for index, step in enumerate(steps):
                action_type = step["type"]
                if action_type == "navigate":
                    target = step["url"]
                    validate_live_public_url(target)
                    if not is_same_site(source_url, target):
                        raise WorkflowSecurityError("cross-site live navigation denied")
                    await page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
                elif action_type == "fill":
                    await page.locator(step["selector"]).fill(step["value"], timeout=timeout_ms)
                elif action_type == "click":
                    await page.locator(step["selector"]).click(timeout=timeout_ms)
                    await page.wait_for_timeout(250)
                elif action_type == "assert_url":
                    if page.url != step["url"]:
                        raise WorkflowSecurityError(f"URL assertion failed at step {index}")
                    assertions.append({"step": index, "type": "assert_url", "passed": True})
                elif action_type == "assert_text":
                    text = await page.locator(step["selector"]).inner_text(timeout=timeout_ms)
                    if step["contains"] not in text:
                        raise WorkflowSecurityError(f"text assertion failed at step {index}")
                    assertions.append({"step": index, "type": "assert_text", "passed": True})
                if page.url:
                    validate_live_public_url(page.url)
                    if not is_same_site(source_url, page.url):
                        raise WorkflowSecurityError(f"workflow escaped same-site boundary after step {index}")
            return page.url or source_url, assertions
        finally:
            await context.close()
            await browser.close()


def _load_json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise WorkflowSecurityError(f"JSON file must contain an object: {path}")
    return value


def _write_receipt(root: Path, receipt: dict[str, Any]) -> Path:
    receipts = root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = f"replay_{workflow_safe(receipt['workflow_id'])}_{receipt['receipt_hash'].split(':', 1)[1][:16]}.json"
    path = receipts / name
    if path.exists():
        return path
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def workflow_safe(value: str) -> str:
    if not WORKFLOW_ID_RE.fullmatch(value):
        raise WorkflowSecurityError("unsafe workflow id")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes deterministic browser workflow cache")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_cmd = sub.add_parser("compile")
    compile_cmd.add_argument("--trace", required=True)
    compile_cmd.add_argument("--root", default=".hermes/browser-workflows")

    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("--workflow", required=True)

    replay = sub.add_parser("replay")
    replay.add_argument("--workflow", required=True)
    replay.add_argument("--root", default=".hermes/browser-workflows")
    replay.add_argument("--params-json", default="{}")
    replay.add_argument("--params-file", default="")
    mode = replay.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    replay.add_argument("--capability-file", default="")
    replay.add_argument("--principal", default="agent:hermes")
    replay.add_argument("--data-class", default="INTERNAL")
    replay.add_argument("--repo-root", default=".")
    replay.add_argument("--headed", action="store_true")
    replay.add_argument("--timeout-ms", type=int, default=15000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "compile":
        result = compile_workflow(_load_json_file(Path(args.trace)), Path(args.root))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "validate":
        workflow = validate_workflow(_load_json_file(Path(args.workflow)))
        print(json.dumps({"valid": True, "workflow_id": workflow["workflow_id"], "workflow_hash": workflow["workflow_hash"]}, sort_keys=True))
        return 0

    workflow = validate_workflow(_load_json_file(Path(args.workflow)))
    params = _load_json_file(Path(args.params_file)) if args.params_file else json.loads(args.params_json)
    if not isinstance(params, dict):
        raise WorkflowSecurityError("workflow params must be an object")
    rendered = render_workflow(workflow, params)["steps"]
    started = time.monotonic()
    if args.dry_run:
        final_url = workflow["source_url"]
        status = "dry_run"
        assertions: list[dict[str, Any]] = []
    else:
        capability = Path(args.capability_file) if args.capability_file else None
        require_execution_authorization(
            workflow,
            capability_path=capability,
            principal=args.principal,
            data_class=args.data_class,
            repo_root=Path(args.repo_root).resolve(),
        )
        final_url, assertions = asyncio.run(replay_with_playwright(workflow, rendered, headed=args.headed, timeout_ms=args.timeout_ms))
        status = "success"
    duration_ms = (time.monotonic() - started) * 1000
    receipt = build_replay_receipt(workflow, rendered, status=status, final_url=final_url, duration_ms=duration_ms)
    receipt["assertions"] = assertions
    receipt["receipt_hash"] = "sha256:" + sha256_json({k: v for k, v in receipt.items() if k != "receipt_hash"})
    receipt_path = _write_receipt(Path(args.root), receipt)
    print(json.dumps({"status": status, "workflow_id": workflow["workflow_id"], "workflow_hash": workflow["workflow_hash"], "receipt": str(receipt_path)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WorkflowSecurityError, json.JSONDecodeError) as exc:
        print(f"browser workflow error: {exc}", file=sys.stderr)
        raise SystemExit(2)
