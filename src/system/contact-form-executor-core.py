#!/usr/bin/env python3
"""Hermes Contact Form Executor v1.

Governed browser execution for official public contact forms.

This component turns a campaign-approved `contact_form` handoff into a browser
submission only when the form URL, public evidence, campaign approval, message
hash, field allowlist, duplicate prevention, and submission evidence checks all
pass. It records `sent` only after a receipt and screenshot are sealed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CONTACT_FORM_CHANNEL = "contact_form"
SENSITIVE_FIELD_PATTERNS = (
    "password",
    "passcode",
    "otp",
    "one time",
    "2fa",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "ssn",
    "social security",
    "credit card",
    "card number",
    "cvv",
    "payment",
    "bank",
    "routing",
    "upload",
    "attachment",
    "file",
    "login",
    "username",
)
CONFIRMATION_PATTERNS = (
    "thank you",
    "thanks",
    "submitted",
    "received",
    "we will be in touch",
    "we'll be in touch",
    "message sent",
    "success",
)


def load_outbound_module() -> Any:
    path = Path(__file__).with_name("outbound-executor.py")
    spec = importlib.util.spec_from_file_location("hermes_outbound_executor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load outbound executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


outbound = load_outbound_module()


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def utc_now() -> str:
    return utc_now_dt().strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return outbound.read_json(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    outbound.write_json(path, data)


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    outbound.append_jsonl(path, data)


def contact_form_root(root: Path) -> Path:
    return root / "contact-form"


def contact_form_receipts_dir(root: Path) -> Path:
    return contact_form_root(root) / "receipts"


def submissions_dir(root: Path) -> Path:
    return contact_form_root(root) / "submissions"


def normalize_host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower().rstrip(".")


COMMON_MULTI_LABEL_PUBLIC_SUFFIXES = frozenset(
    {
        "ac.uk",
        "co.jp",
        "co.nz",
        "co.uk",
        "com.au",
        "com.br",
        "com.cn",
        "com.mx",
        "com.sg",
        "com.tr",
        "com.tw",
        "gov.uk",
        "net.au",
        "net.nz",
        "net.uk",
        "org.au",
        "org.nz",
        "org.uk",
    }
)


def registrable_domain(host: str) -> str:
    """Return the registrable domain using a PSL parser when available.

    The fallback intentionally handles common delegated public suffixes instead
    of blindly comparing the last two labels for every host.
    """
    host = host.lower().rstrip(".")
    if not host:
        return ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        from publicsuffix2 import get_sld  # type: ignore

        return (get_sld(host) or host).lower().rstrip(".")
    except Exception:
        pass
    try:
        import tldextract  # type: ignore

        extractor = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)
        parsed = extractor(host)
        registered = parsed.registered_domain or parsed.fqdn
        return registered.lower().rstrip(".")
    except Exception:
        pass
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return host
    suffix = ".".join(parts[-2:])
    if suffix in COMMON_MULTI_LABEL_PUBLIC_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(candidate_url: str, official_urls: list[str]) -> bool:
    candidate_host = normalize_host(candidate_url)
    if not candidate_host:
        return False
    candidate_base = registrable_domain(candidate_host)
    for official_url in official_urls:
        official_host = normalize_host(official_url)
        if not official_host:
            continue
        if candidate_host == official_host or candidate_host.endswith(f".{official_host}"):
            return True
        if candidate_base == registrable_domain(official_host):
            return True
    return False


def validate_public_url(url: str, *, allow_private_network_for_test: bool = False) -> list[str]:
    errors: list[str] = []
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        errors.append("form URL must use http or https")
    if parsed.username or parsed.password:
        errors.append("form URL must not contain embedded credentials")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        errors.append("form URL must contain a hostname")
        return errors
    if allow_private_network_for_test:
        return errors
    try:
        direct_ip = ipaddress.ip_address(host)
        addresses = [direct_ip]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            errors.append(f"form URL hostname resolution failed: {host}: {exc}")
            return errors
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    if not addresses:
        errors.append("form URL hostname did not resolve")
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            errors.append(f"private or non-routable form target is blocked: {address}")
            break
    return errors


def prospect_official_urls(prospect: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("website", "source_url", "url"):
        value = prospect.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            values.append(value)
    refs = prospect.get("evidence_refs")
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, dict):
                value = item.get("ref") or item.get("url")
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    values.append(value)
    return values


def load_validation(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root)
    policy = outbound.load_policy(args.campaign_policy)
    receipt = outbound.load_approval(root, args.approval_id)
    handoff = read_json(Path(args.handoff))
    if not handoff:
        raise SystemExit(f"handoff not found: {args.handoff}")
    message = outbound.parse_outreach(Path(handoff.get("outreach_draft", "")))
    prospect = outbound.load_prospect(args.prospects_file, str(handoff.get("prospect_id", ""))) if args.prospects_file else {}
    errors = outbound.validate_policy_receipt(policy, receipt)

    policy_expires = outbound.parse_ts(str(policy.get("expires_at") or ""))
    if not policy_expires or policy_expires <= utc_now_dt():
        errors.append("campaign policy expired")
    if handoff.get("experiment_id") != policy.get("experiment_id"):
        errors.append("handoff experiment mismatch")
    if handoff.get("approval_required") is not True:
        errors.append("handoff does not declare approval requirement")
    if handoff.get("allowed_to_send") is True:
        errors.append("handoff should not self-authorize sending")
    if policy.get("offer") and policy.get("offer") != outbound.read_plan_offer(root, str(policy["experiment_id"])):
        errors.append("campaign offer does not match experiment plan offer")

    channel = str(handoff.get("contact_channel") or "")
    autonomous_channels = set(policy.get("allowed_autonomous_channels") or policy.get("allowed_channels", []))
    handoff_only_channels = set(policy.get("handoff_only_channels", []))
    if channel != CONTACT_FORM_CHANNEL:
        errors.append(f"contact-form executor requires contact_channel=contact_form, got: {channel}")
    if channel in autonomous_channels:
        errors.append("contact_form must not be an autonomous email channel")
    if channel not in handoff_only_channels:
        errors.append("contact_form is not allowed as a handoff-only campaign channel")
    if channel in set(policy.get("prohibited_channels", [])):
        errors.append("contact_form is prohibited by campaign policy")

    form_url = str(handoff.get("contact_ref") or "")
    if not form_url:
        errors.append("handoff missing contact form URL")
    else:
        errors.extend(validate_public_url(form_url, allow_private_network_for_test=args.allow_private_network_for_test))

    if not outbound.audit_has_source(Path(handoff.get("audit", ""))) and policy.get("evidence_requirement", {}).get("require_audit_source", True):
        errors.append("audit does not contain a source reference")
    unsupported = outbound.validate_no_unsupported_claims(message)
    if unsupported and policy.get("evidence_requirement", {}).get("forbid_unsupported_claims", True):
        errors.extend(unsupported)

    category = str(prospect.get("category") or "")
    allowed_industries = set(policy.get("allowed_industries", []))
    if allowed_industries:
        if not args.prospects_file:
            errors.append("prospects_file required to verify allowed industry")
        elif category not in allowed_industries:
            errors.append(f"industry not allowed: {category}")

    if prospect:
        official_urls = prospect_official_urls(prospect)
        if not same_site(form_url, official_urls) and not args.allow_private_network_for_test:
            errors.append("contact form URL is not on the prospect's verified official domain")
        source_url = prospect.get("source_url") or prospect.get("url") or ""
        evidence_refs = prospect.get("evidence_refs") if isinstance(prospect.get("evidence_refs"), list) else []
        source_count = int(bool(source_url)) + sum(1 for item in evidence_refs if isinstance(item, dict) and (item.get("ref") or item.get("url")))
        if source_count < int(policy.get("evidence_requirement", {}).get("minimum_public_sources", 1)):
            errors.append("insufficient public source evidence")
    else:
        errors.append("prospect record required for official-domain verification")

    send_rows = outbound.current_sends(root, str(policy["campaign_id"]))
    if len(send_rows) >= int(policy.get("max_sends", 0)):
        errors.append("campaign send limit reached")
    prospect_sends = [row for row in send_rows if row.get("prospect_id") == handoff.get("prospect_id")]
    if prospect_sends and not args.allow_duplicate:
        errors.append("duplicate prospect send attempt")

    return {
        "schema_version": "contact-form-validation-v1",
        "valid": not errors,
        "errors": errors,
        "campaign_id": policy.get("campaign_id"),
        "experiment_id": policy.get("experiment_id"),
        "prospect_id": handoff.get("prospect_id"),
        "business_name": handoff.get("business_name"),
        "form_url": form_url,
        "official_domain": normalize_host(form_url),
        "message_hash": message["message_hash"],
        "message_subject": message["subject"],
        "policy": policy,
        "approval_receipt": receipt,
        "handoff": handoff,
        "message": message,
        "prospect": prospect,
    }


def visible_text_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def field_role(meta: dict[str, str], *, supply_phone: bool) -> str:
    key = visible_text_key(" ".join(meta.values()))
    if any(pattern in key for pattern in SENSITIVE_FIELD_PATTERNS):
        return "sensitive"
    if "email" in key or meta.get("type") == "email":
        return "email"
    if "phone" in key or "tel" in key or meta.get("type") == "tel":
        return "phone" if supply_phone else "unsupported_phone"
    if any(token in key for token in ("company", "business", "organization", "organisation")):
        return "company"
    if any(token in key for token in ("subject", "topic", "reason")):
        return "subject"
    if any(token in key for token in ("message", "comment", "details", "question", "how can we help", "description")):
        return "message"
    if "name" in key:
        return "name"
    return ""


async def element_meta(page: Any, handle: Any) -> dict[str, str]:
    return await page.evaluate(
        """el => {
          const id = el.getAttribute('id') || '';
          let label = '';
          if (id) {
            const direct = document.querySelector(`label[for="${CSS.escape(id)}"]`);
            if (direct) label = direct.innerText || '';
          }
          const parentLabel = el.closest('label');
          if (!label && parentLabel) label = parentLabel.innerText || '';
          return {
            tag: (el.tagName || '').toLowerCase(),
            type: (el.getAttribute('type') || '').toLowerCase(),
            name: el.getAttribute('name') || '',
            id,
            placeholder: el.getAttribute('placeholder') || '',
            aria: el.getAttribute('aria-label') || '',
            label,
          };
        }""",
        handle,
    )


def field_value(role: str, validation: dict[str, Any], args: argparse.Namespace) -> str:
    if role == "name":
        return args.operator_name
    if role == "company":
        return args.operator_company
    if role == "email":
        return args.operator_email
    if role == "phone":
        return args.operator_phone
    if role == "subject":
        return validation["message"]["subject"]
    if role == "message":
        return validation["message"]["body"]
    return ""


def public_field_receipt(meta: dict[str, str], role: str, value: str) -> dict[str, Any]:
    return {
        "role": role,
        "tag": meta.get("tag", ""),
        "type": meta.get("type", ""),
        "name": meta.get("name", ""),
        "id": meta.get("id", ""),
        "value_hash": sha256_text(value),
        "value_length": len(value),
    }


async def submit_with_playwright(validation: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("Playwright is required for contact-form submission") from exc

    form_url = validation["form_url"]
    submitted_fields: list[dict[str, Any]] = []
    screenshot_dir = submissions_dir(Path(args.root))
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    browser_run_id = "browser_" + sha256_json({"url": form_url, "ts": utc_now(), "prospect_id": validation["prospect_id"]})[:16]
    pre_path = screenshot_dir / f"{browser_run_id}-pre.png"
    post_path = screenshot_dir / f"{browser_run_id}-post.png"

    async with async_playwright() as p:
        launch_kwargs: dict[str, Any] = {"headless": not args.browser_headed}
        if args.browser_executable_path:
            launch_kwargs["executable_path"] = args.browser_executable_path
        try:
            browser = await p.chromium.launch(**launch_kwargs)
        except Exception as exc:
            raise SystemExit(
                "Playwright browser runtime unavailable; run "
                "`src/system/jarvis-armory.sh install` or "
                "`.hermes/jarvis/JARVIS-OS-v1.2.0-tool-armory/.venv/bin/python -m playwright install chromium`"
            ) from exc
        context = await browser.new_context(viewport={"width": args.viewport_width, "height": args.viewport_height})
        page = await context.new_page()
        try:
            response = await page.goto(form_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            if response is None:
                raise SystemExit("browser navigation produced no response")
            page_text = visible_text_key(await page.locator("body").inner_text(timeout=args.timeout_ms))
            if any(pattern in page_text for pattern in ("captcha", "recaptcha", "hcaptcha", "cloudflare")):
                raise SystemExit("form appears to require CAPTCHA or anti-bot challenge")
            fields = await page.locator("input, textarea, select").element_handles()
            role_counts: dict[str, int] = {}
            for handle in fields:
                meta = await element_meta(page, handle)
                input_type = meta.get("type", "")
                if input_type in {"hidden", "submit", "button", "reset", "checkbox", "radio"}:
                    continue
                role = field_role(meta, supply_phone=args.supply_phone)
                if role == "sensitive":
                    raise SystemExit(f"form requests blocked sensitive field: {meta}")
                if role in {"", "unsupported_phone"}:
                    continue
                if role_counts.get(role, 0) >= 1 and role not in {"name"}:
                    continue
                value = field_value(role, validation, args)
                if not value:
                    continue
                tag = meta.get("tag", "")
                if tag == "select":
                    continue
                await handle.fill(value, timeout=args.timeout_ms)
                role_counts[role] = role_counts.get(role, 0) + 1
                submitted_fields.append(public_field_receipt(meta, role, value))
            if not role_counts.get("message"):
                raise SystemExit("no allowlisted message/comments field was found")
            if not role_counts.get("email"):
                raise SystemExit("no allowlisted email field was found")
            await page.screenshot(path=str(pre_path), full_page=True, animations="disabled")
            submit = page.locator("button[type=submit], input[type=submit], button:has-text('Submit'), button:has-text('Send'), button:has-text('Contact'), button:has-text('Request')").first
            if await submit.count() == 0:
                raise SystemExit("no allowlisted submit button found")
            await submit.click(timeout=args.timeout_ms)
            with contextlib_suppress_timeout():
                await page.wait_for_load_state("networkidle", timeout=min(args.timeout_ms, 8000))
            await page.wait_for_timeout(args.post_submit_wait_ms)
            await page.screenshot(path=str(post_path), full_page=True, animations="disabled")
            final_url = page.url
            confirmation_text = (await page.locator("body").inner_text(timeout=args.timeout_ms))[:4000]
            confirmation_key = visible_text_key(confirmation_text)
            positive = final_url != form_url or any(pattern in confirmation_key for pattern in CONFIRMATION_PATTERNS)
            if not positive:
                raise SystemExit("positive submission evidence not found")
            return {
                "browser_run_id": browser_run_id,
                "form_url": form_url,
                "confirmation_url": final_url,
                "confirmation_text_hash": sha256_text(confirmation_text),
                "confirmation_text_excerpt": confirmation_text[:240],
                "submitted_fields": submitted_fields,
                "pre_submit_screenshot": str(pre_path),
                "pre_submit_screenshot_hash": hashlib.sha256(pre_path.read_bytes()).hexdigest(),
                "submission_screenshot": str(post_path),
                "submission_screenshot_hash": hashlib.sha256(post_path.read_bytes()).hexdigest(),
            }
        finally:
            await context.close()
            await browser.close()


class contextlib_suppress_timeout:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is None:
            return False
        return "Timeout" in getattr(exc_type, "__name__", "")


def record_sent_stage(validation: dict[str, Any], args: argparse.Namespace, receipt: dict[str, Any]) -> None:
    funnel = Path(args.repo_root) / "src/system/local-service-funnel.py"
    if not funnel.is_file():
        raise SystemExit("local-service-funnel.py not found for sent-stage recording")
    cmd = [
        sys.executable,
        str(funnel),
        "--root",
        str(args.root),
        "--repo-root",
        str(args.repo_root),
        "record-stage",
        "--experiment-id",
        str(validation["experiment_id"]),
        "--prospect-id",
        str(validation["prospect_id"]),
        "--business-name",
        str(validation["business_name"]),
        "--stage",
        "sent",
        "--approval-id",
        str(args.approval_id),
        "--evidence-ref",
        f"contact_form_receipt={receipt['contact_form_receipt_path']}",
        "--evidence-ref",
        f"message_hash={receipt['message_hash']}",
        "--evidence-ref",
        f"screenshot_hash={receipt['submission_screenshot_hash']}",
        "--notes",
        "Contact-form executor recorded positive browser submission evidence",
    ]
    proc = subprocess.run(cmd, cwd=args.repo_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or "failed to record sent stage")


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    contact_form_receipts_dir(root).mkdir(parents=True, exist_ok=True)
    submissions_dir(root).mkdir(parents=True, exist_ok=True)
    outbound.outbound_dir(root).mkdir(parents=True, exist_ok=True)
    outbound.send_receipts_path(root).touch(exist_ok=True)
    print(
        json.dumps(
            {
                "schema_version": "contact-form-executor-init-v1",
                "root": str(root),
                "receipts": str(contact_form_receipts_dir(root)),
                "submissions": str(submissions_dir(root)),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        import playwright  # noqa: F401

        playwright_available = True
    except ImportError:
        playwright_available = False
    print(
        json.dumps(
            {
                "schema_version": "contact-form-executor-doctor-v1",
                "python": sys.executable,
                "playwright_available": playwright_available,
                "jarvis_url": args.jarvis_url,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if playwright_available else 2


def cmd_validate(args: argparse.Namespace) -> int:
    result = load_validation(args)
    public = {k: v for k, v in result.items() if k not in {"policy", "approval_receipt", "handoff", "message", "prospect"}}
    print(json.dumps(public, indent=2, sort_keys=True))
    return 0 if result["valid"] else 2


def cmd_submit(args: argparse.Namespace) -> int:
    validation = load_validation(args)
    if not validation["valid"]:
        raise SystemExit("contact-form validation failed: " + "; ".join(validation["errors"]))
    if not args.operator_name or not args.operator_email:
        raise SystemExit("--operator-name and --operator-email are required")
    browser_result = asyncio.run(submit_with_playwright(validation, args))
    root = Path(args.root)
    submitted_at = utc_now()
    send_id = "send_" + sha256_json(
        {
            "campaign_id": validation["campaign_id"],
            "prospect_id": validation["prospect_id"],
            "message_hash": validation["message_hash"],
            "submitted_at": submitted_at,
            "transport": CONTACT_FORM_CHANNEL,
        }
    )[:20]
    receipt_path = contact_form_receipts_dir(root) / f"{send_id}.json"
    receipt = {
        "schema_version": "contact-form-receipt-v1",
        "send_id": send_id,
        "send_status": "sent",
        "transport": CONTACT_FORM_CHANNEL,
        "submitted_at": submitted_at,
        "campaign_id": validation["campaign_id"],
        "experiment_id": validation["experiment_id"],
        "prospect_id": validation["prospect_id"],
        "business_name": validation["business_name"],
        "approval_id": args.approval_id,
        "campaign_policy_hash": validation["policy"]["campaign_policy_hash"],
        "official_domain": validation["official_domain"],
        "form_url": validation["form_url"],
        "message_hash": validation["message_hash"],
        "message_subject": validation["message_subject"],
        **browser_result,
        "contact_form_receipt_path": str(receipt_path),
    }
    receipt["contact_form_receipt_hash"] = sha256_json(receipt)
    write_json(receipt_path, receipt)
    send_receipt = {
        "schema_version": "outbound-send-receipt-v1",
        "send_id": send_id,
        "send_status": "sent",
        "sent_at": submitted_at,
        "campaign_id": validation["campaign_id"],
        "experiment_id": validation["experiment_id"],
        "prospect_id": validation["prospect_id"],
        "business_name": validation["business_name"],
        "approval_id": args.approval_id,
        "campaign_policy_hash": validation["policy"]["campaign_policy_hash"],
        "message_hash": validation["message_hash"],
        "message_subject": validation["message_subject"],
        "transport": CONTACT_FORM_CHANNEL,
        "transport_receipt": {
            "contact_form_receipt": str(receipt_path),
            "confirmation_url": browser_result["confirmation_url"],
            "submission_screenshot": browser_result["submission_screenshot"],
        },
        "send_receipt_path": str(receipt_path),
    }
    send_receipt["send_receipt_hash"] = sha256_json(send_receipt)
    append_jsonl(outbound.send_receipts_path(root), send_receipt)
    record_sent_stage(validation, args, receipt)
    print(
        json.dumps(
            {
                "schema_version": "contact-form-submit-result-v1",
                "sent": True,
                "send_id": send_id,
                "contact_form_receipt": str(receipt_path),
                "submission_screenshot": browser_result["submission_screenshot"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(outbound.revenue_root()))
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--jarvis-url", default=os.environ.get("JARVIS_URL", "http://127.0.0.1:4700"))


def add_validation_args(parser: argparse.ArgumentParser) -> None:
    add_common(parser)
    parser.add_argument("--campaign-policy", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--prospects-file", default="")
    parser.add_argument("--allow-duplicate", action="store_true")
    parser.add_argument("--allow-private-network-for-test", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes Contact Form Executor v1")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    add_common(init)
    init.set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor")
    add_common(doctor)
    doctor.set_defaults(func=cmd_doctor)

    validate = sub.add_parser("validate-handoff")
    add_validation_args(validate)
    validate.set_defaults(func=cmd_validate)

    submit = sub.add_parser("submit")
    add_validation_args(submit)
    submit.add_argument("--operator-name", default=os.environ.get("HERMES_CONTACT_NAME", ""))
    submit.add_argument("--operator-email", default=os.environ.get("HERMES_CONTACT_EMAIL", ""))
    submit.add_argument("--operator-company", default=os.environ.get("HERMES_CONTACT_COMPANY", "Hermes Automation"))
    submit.add_argument("--operator-phone", default=os.environ.get("HERMES_CONTACT_PHONE", ""))
    submit.add_argument("--supply-phone", action="store_true")
    submit.add_argument("--browser-headed", action="store_true")
    submit.add_argument("--browser-executable-path", default=os.environ.get("HERMES_BROWSER_EXECUTABLE", ""))
    submit.add_argument("--viewport-width", type=int, default=1440)
    submit.add_argument("--viewport-height", type=int, default=900)
    submit.add_argument("--timeout-ms", type=int, default=15000)
    submit.add_argument("--post-submit-wait-ms", type=int, default=1200)
    submit.set_defaults(func=cmd_submit)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
