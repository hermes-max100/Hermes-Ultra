#!/usr/bin/env python3
"""Hermes Contact Form Executor hardened execution boundary.

The established validation/form-filling logic remains in an internal core. This
entrypoint removes request-time private-network/duplicate bypass switches,
requires a consumed Containment Gateway capability plus an atomic prospect claim,
and constrains Chromium to same-origin public HTTP(S) requests during submission.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load_module("hermes_contact_form_executor_core", HERE / "contact-form-executor-core.py")
containment = load_module("hermes_contact_form_containment", HERE / "containment-gateway.py")
externalization = load_module("hermes_contact_externalization_claim", HERE / "externalization-claim.py")

_original_build_parser = core.build_parser


def remove_option(parser: argparse.ArgumentParser, option: str) -> None:
    action = next((a for a in parser._actions if option in a.option_strings), None)
    if action is None:
        return
    parser._remove_action(action)
    for group in parser._action_groups:
        if action in group._group_actions:
            group._group_actions.remove(action)
    for group in parser._mutually_exclusive_groups:
        if action in group._group_actions:
            group._group_actions.remove(action)
    for item in action.option_strings:
        parser._option_string_actions.pop(item, None)


def child_parser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action.choices[name]


def hardened_build_parser() -> argparse.ArgumentParser:
    parser = _original_build_parser()
    validate = child_parser(parser, "validate-handoff")
    submit = child_parser(parser, "submit")
    for child in (validate, submit):
        remove_option(child, "--allow-private-network-for-test")
        remove_option(child, "--allow-duplicate")
        child.set_defaults(allow_private_network_for_test=False, allow_duplicate=False)
    submit.add_argument(
        "--containment-token-stdin",
        action="store_true",
        required=True,
        help="Read the single-use signed containment capability from stdin.",
    )
    return parser


def form_origin(form_url: str) -> str:
    parsed = urlsplit(form_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit("invalid contact form origin")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    return containment.canonical_destination(f"{parsed.scheme}://{host}{port}")


def verify_submit_capability(validation: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if not bool(getattr(args, "containment_token_stdin", False)):
        raise SystemExit("containment token from stdin is required")
    form_url = str(validation["form_url"])
    resource = "form-sha256:" + hashlib.sha256(form_url.encode("utf-8")).hexdigest()
    requested = containment.RequestScope.make(
        "revenue-os:contact-form-executor",
        "browser:contact-form",
        form_origin(form_url),
        resource,
        "INTERNAL",
    )
    token = containment.load_json_stdin()
    try:
        receipt = containment.verify_capability(
            token=token,
            secret=containment.require_secret(os.getenv("HERMES_CONTAINMENT_SECRET")),
            requested=requested,
            state_dir=Path(os.getenv("HERMES_CONTAINMENT_STATE_DIR", ".hermes/containment")),
            consume=True,
            max_ttl_seconds=containment.trusted_max_ttl_seconds(),
        )
    except containment.CapabilityError as exc:
        raise SystemExit(f"containment capability denied: {exc}") from exc
    body = token.get("body", {})
    if body.get("purpose") != "contact-form-submit":
        raise SystemExit("containment capability denied: purpose mismatch")
    if body.get("evidence_id") != str(args.approval_id):
        raise SystemExit("containment capability denied: approval evidence mismatch")
    return receipt


def request_is_authorized(url: str, form_url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme in {"data", "blob", "about"}:
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    if not core.same_site(url, [form_url]):
        return False
    return not core.validate_public_url(url, allow_private_network_for_test=False)


async def hardened_submit_with_playwright(validation: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("Playwright is required for contact-form submission") from exc

    form_url = validation["form_url"]
    submitted_fields: list[dict[str, Any]] = []
    screenshot_dir = core.submissions_dir(Path(args.root))
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    browser_run_id = "browser_" + core.sha256_json({"url": form_url, "ts": core.utc_now(), "prospect_id": validation["prospect_id"]})[:16]
    pre_path = screenshot_dir / f"{browser_run_id}-pre.png"
    post_path = screenshot_dir / f"{browser_run_id}-post.png"

    async with async_playwright() as p:
        launch_kwargs: dict[str, Any] = {"headless": not args.browser_headed}
        if args.browser_executable_path:
            launch_kwargs["executable_path"] = args.browser_executable_path
        try:
            browser = await p.chromium.launch(**launch_kwargs)
        except Exception as exc:
            raise SystemExit("Playwright browser runtime unavailable") from exc
        context = await browser.new_context(viewport={"width": args.viewport_width, "height": args.viewport_height})

        async def guard(route: Any, request: Any) -> None:
            if request_is_authorized(request.url, form_url):
                await route.continue_()
            else:
                await route.abort("blockedbyclient")

        await context.route("**/*", guard)
        page = await context.new_page()
        try:
            response = await page.goto(form_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            if response is None:
                raise SystemExit("browser navigation produced no response")
            if not request_is_authorized(page.url, form_url):
                raise SystemExit("browser navigation left the authorized public origin")
            page_text = core.visible_text_key(await page.locator("body").inner_text(timeout=args.timeout_ms))
            if any(pattern in page_text for pattern in ("captcha", "recaptcha", "hcaptcha", "cloudflare")):
                raise SystemExit("form appears to require CAPTCHA or anti-bot challenge")
            fields = await page.locator("input, textarea, select").element_handles()
            role_counts: dict[str, int] = {}
            for handle in fields:
                meta = await core.element_meta(page, handle)
                input_type = meta.get("type", "")
                if input_type in {"hidden", "submit", "button", "reset", "checkbox", "radio"}:
                    continue
                role = core.field_role(meta, supply_phone=args.supply_phone)
                if role == "sensitive":
                    raise SystemExit(f"form requests blocked sensitive field: {meta}")
                if role in {"", "unsupported_phone"}:
                    continue
                if role_counts.get(role, 0) >= 1 and role not in {"name"}:
                    continue
                value = core.field_value(role, validation, args)
                if not value:
                    continue
                if meta.get("tag", "") == "select":
                    continue
                await handle.fill(value, timeout=args.timeout_ms)
                role_counts[role] = role_counts.get(role, 0) + 1
                submitted_fields.append(core.public_field_receipt(meta, role, value))
            if not role_counts.get("message"):
                raise SystemExit("no allowlisted message/comments field was found")
            if not role_counts.get("email"):
                raise SystemExit("no allowlisted email field was found")
            await page.screenshot(path=str(pre_path), full_page=True, animations="disabled")
            submit = page.locator("button[type=submit], input[type=submit], button:has-text('Submit'), button:has-text('Send'), button:has-text('Contact'), button:has-text('Request')").first
            if await submit.count() == 0:
                raise SystemExit("no allowlisted submit button found")
            await submit.click(timeout=args.timeout_ms)
            with core.contextlib_suppress_timeout():
                await page.wait_for_load_state("networkidle", timeout=min(args.timeout_ms, 8000))
            await page.wait_for_timeout(args.post_submit_wait_ms)
            if not request_is_authorized(page.url, form_url):
                raise SystemExit("submission redirected outside the authorized public origin")
            await page.screenshot(path=str(post_path), full_page=True, animations="disabled")
            final_url = page.url
            confirmation_text = (await page.locator("body").inner_text(timeout=args.timeout_ms))[:4000]
            confirmation_key = core.visible_text_key(confirmation_text)
            positive = final_url != form_url or any(pattern in confirmation_key for pattern in core.CONFIRMATION_PATTERNS)
            if not positive:
                raise SystemExit("positive submission evidence not found")
            return {
                "browser_run_id": browser_run_id,
                "form_url": form_url,
                "confirmation_url": final_url,
                "confirmation_text_hash": core.sha256_text(confirmation_text),
                "confirmation_text_excerpt": confirmation_text[:240],
                "submitted_fields": submitted_fields,
                "pre_submit_screenshot": str(pre_path),
                "pre_submit_screenshot_hash": hashlib.sha256(pre_path.read_bytes()).hexdigest(),
                "submission_screenshot": str(post_path),
                "submission_screenshot_hash": hashlib.sha256(post_path.read_bytes()).hexdigest(),
                "network_policy": "same-site-public-http-only",
            }
        finally:
            await context.close()
            await browser.close()


def acquire_claim(validation: dict[str, Any]) -> dict[str, Any]:
    try:
        return externalization.acquire(
            core.CONTACT_FORM_CHANNEL,
            str(validation["campaign_id"]),
            str(validation["prospect_id"]),
        )
    except externalization.ExternalizationClaimError as exc:
        raise SystemExit(f"externalization claim denied: {exc}") from exc


def hardened_cmd_submit(args: argparse.Namespace) -> int:
    # One immutable-in-memory validation snapshot is used for authorization,
    # browser execution, receipts, and sent-stage attribution. Caller-writable
    # handoff/policy files are never re-read after capability consumption.
    validation = core.load_validation(args)
    if not validation["valid"]:
        raise SystemExit("contact-form validation failed: " + "; ".join(validation["errors"]))
    if not args.operator_name or not args.operator_email:
        raise SystemExit("--operator-name and --operator-email are required")
    containment_receipt = verify_submit_capability(validation, args)
    claim = acquire_claim(validation)
    browser_result = asyncio.run(core.submit_with_playwright(validation, args))
    root = Path(args.root)
    submitted_at = core.utc_now()
    send_id = "send_" + core.sha256_json(
        {
            "campaign_id": validation["campaign_id"],
            "prospect_id": validation["prospect_id"],
            "message_hash": validation["message_hash"],
            "submitted_at": submitted_at,
            "transport": core.CONTACT_FORM_CHANNEL,
        }
    )[:20]
    receipt_path = core.contact_form_receipts_dir(root) / f"{send_id}.json"
    receipt = {
        "schema_version": "contact-form-receipt-v1",
        "send_id": send_id,
        "send_status": "sent",
        "transport": core.CONTACT_FORM_CHANNEL,
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
        "containment_grant_id": containment_receipt["grant_id"],
        "containment_token_sha256": containment_receipt["token_sha256"],
        "externalization_claim_id": claim["claim_id"],
        **browser_result,
        "contact_form_receipt_path": str(receipt_path),
    }
    receipt["contact_form_receipt_hash"] = core.sha256_json(receipt)
    core.write_json(receipt_path, receipt)
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
        "transport": core.CONTACT_FORM_CHANNEL,
        "containment_grant_id": containment_receipt["grant_id"],
        "containment_token_sha256": containment_receipt["token_sha256"],
        "externalization_claim_id": claim["claim_id"],
        "transport_receipt": {
            "contact_form_receipt": str(receipt_path),
            "confirmation_url": browser_result["confirmation_url"],
            "submission_screenshot": browser_result["submission_screenshot"],
        },
        "send_receipt_path": str(receipt_path),
    }
    send_receipt["send_receipt_hash"] = core.sha256_json(send_receipt)
    core.append_jsonl(core.outbound.send_receipts_path(root), send_receipt)
    core.record_sent_stage(validation, args, receipt)
    try:
        externalization.complete(claim, str(receipt_path), receipt["contact_form_receipt_hash"])
    except externalization.ExternalizationClaimError as exc:
        raise SystemExit(f"submission completed but claim finalization failed: {exc}") from exc
    print(
        core.json.dumps(
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


core.build_parser = hardened_build_parser
core.submit_with_playwright = hardened_submit_with_playwright
core.cmd_submit = hardened_cmd_submit

for _name in dir(core):
    if not _name.startswith("_"):
        globals()[_name] = getattr(core, _name)

build_parser = hardened_build_parser
submit_with_playwright = hardened_submit_with_playwright
cmd_submit = hardened_cmd_submit


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
