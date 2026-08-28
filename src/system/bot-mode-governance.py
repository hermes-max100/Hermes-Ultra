#!/usr/bin/env python3
"""Governed Hermes Bot Mode contracts.

Bots are profile overlays, not authorities. This module validates the repo-owned
Bot roster, creates/validates untrusted inter-Bot messages, and creates/validates
proposal-only council artifacts. It deliberately contains no network,
credential, install, promotion, model-routing, or execution primitive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

POLICY_SCHEMA = "hermes-bot-mode-policy-v1"
MESSAGE_SCHEMA = "hermes-bot-message-v1"
PROPOSAL_SCHEMA = "hermes-council-proposal-v1"
MAX_BODY_BYTES = 64 * 1024
MAX_JSON_BYTES = 256 * 1024
DATA_CLASSES = {
    "PUBLIC",
    "INTERNAL",
    "CONFIDENTIAL",
    "LEGAL_PRIVILEGED",
    "FINANCIAL",
    "CREDENTIAL",
    "SECURITY_SENSITIVE",
}
BOT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:/@+=,-]{1,256}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
MSG_ID_RE = re.compile(r"^msg_[0-9a-f]{32}$")
PROPOSAL_ID_RE = re.compile(r"^proposal_[0-9a-f]{32}$")

TOP_LEVEL_FIELDS = {
    "schema_version", "version", "bot_primitive", "model_policy",
    "credential_policy", "forbidden_bot_ids", "bots", "councils",
    "runtime_boundaries",
}
BOT_FIELDS = {
    "id", "profile", "title", "description", "role", "credential_mode",
    "shared_credentials", "externalization_authority", "allowed_data_classes",
    "allowed_entrypoints", "active",
}
COUNCIL_FIELDS = {
    "id", "title", "members", "allowed_data_classes", "min_members",
    "max_members", "max_rounds", "max_messages_per_turn", "output_status",
    "authority", "externalization_authorized", "requires_governance_review",
}
CREDENTIAL_POLICY_FIELDS = {"mode", "standing_shared_credentials"}
RUNTIME_BOUNDARY_FIELDS = {
    "trust_authority", "network_authority", "externalization",
    "interbot_trust", "council_output",
}
MESSAGE_FIELDS = {
    "schema_version", "message_id", "sender", "recipient", "classification",
    "purpose", "body", "body_sha256", "evidence_parent", "created_at",
    "trust", "authority", "externalization_authorized",
}
PROPOSAL_FIELDS = {
    "schema_version", "proposal_id", "council_id", "members", "classification",
    "rounds", "message_count", "proposal", "proposal_sha256",
    "deliberation_sha256", "evidence_parents", "created_at", "status", "trust",
    "authority", "externalization_authorized", "requires_governance_review",
}


class GovernanceError(ValueError):
    """Fail-closed Bot Mode governance validation error."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reject_duplicate_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GovernanceError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _load_json_bytes(data: bytes) -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise GovernanceError("json_input_too_large")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except UnicodeDecodeError as exc:
        raise GovernanceError("json_not_utf8") from exc
    except json.JSONDecodeError as exc:
        raise GovernanceError("invalid_json") from exc


def load_policy(path: Path | str) -> dict[str, Any]:
    policy_path = Path(path)
    if policy_path.is_symlink():
        raise GovernanceError("policy_symlink_rejected")
    try:
        payload = _load_json_bytes(policy_path.read_bytes())
    except OSError as exc:
        raise GovernanceError(f"policy_read_failed:{exc.__class__.__name__}") from exc
    if not isinstance(payload, dict):
        raise GovernanceError("policy_must_be_object")
    return payload


def _require_exact_fields(obj: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(obj)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise GovernanceError(f"{label}_schema_mismatch:missing={missing}:unknown={unknown}")


def _require_nonempty_string(value: Any, label: str, *, max_chars: int = 2048) -> str:
    if not isinstance(value, str):
        raise GovernanceError(f"{label}_must_be_string")
    text = value.strip()
    if not text or len(text) > max_chars:
        raise GovernanceError(f"invalid_{label}")
    return text


def _canonical_identity(value: str) -> str:
    return re.sub(r"[ _]+", "-", value.strip().lower())


def _require_bot_id(value: Any, label: str = "bot_id") -> str:
    text = _require_nonempty_string(value, label, max_chars=64)
    if not BOT_ID_RE.fullmatch(text):
        raise GovernanceError(f"invalid_{label}")
    return text


def _require_profile_id(value: Any) -> str:
    text = _require_nonempty_string(value, "profile", max_chars=64)
    if not PROFILE_ID_RE.fullmatch(text):
        raise GovernanceError("invalid_profile")
    return text


def _require_token(value: Any, label: str) -> str:
    text = _require_nonempty_string(value, label, max_chars=256)
    if not SAFE_TOKEN_RE.fullmatch(text):
        raise GovernanceError(f"invalid_{label}")
    return text


def _require_timestamp(value: Any) -> str:
    text = _require_nonempty_string(value, "created_at", max_chars=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GovernanceError("invalid_created_at") from exc
    if parsed.tzinfo is None:
        raise GovernanceError("created_at_requires_timezone")
    return text


def _require_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise GovernanceError(f"{label}_must_be_bool")
    return value


def _require_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise GovernanceError(f"invalid_{label}")
    return value


def _validate_data_class_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise GovernanceError(f"{label}_must_be_nonempty_list")
    if len(value) != len(set(value)):
        raise GovernanceError(f"duplicate_{label}")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or item != item.strip().upper() or item not in DATA_CLASSES:
            raise GovernanceError(f"invalid_{label}")
        if item == "CREDENTIAL":
            raise GovernanceError("credential_data_cannot_flow_between_bots")
        result.append(item)
    return result


def _policy_bot_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {bot["id"]: bot for bot in policy["bots"]}


def _policy_council_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {council["id"]: council for council in policy["councils"]}


def _unsafe_symlink_component(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _validate_profile_manifest(root: Path, bots: list[dict[str, Any]]) -> None:
    manifest_path = root / "profiles/profile_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise GovernanceError("missing_or_unsafe_profile_manifest")
    try:
        manifest = _load_json_bytes(manifest_path.read_bytes())
    except OSError as exc:
        raise GovernanceError(f"profile_manifest_read_failed:{exc.__class__.__name__}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("profiles"), list):
        raise GovernanceError("invalid_profile_manifest")
    profile_entries: dict[str, dict[str, Any]] = {}
    for entry in manifest["profiles"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise GovernanceError("invalid_profile_manifest_entry")
        profile_id = entry["id"]
        if profile_id in profile_entries:
            raise GovernanceError("duplicate_profile_manifest_id")
        profile_entries[profile_id] = entry

    for bot in bots:
        profile_id = bot["profile"]
        entry = profile_entries.get(profile_id)
        if entry is None:
            raise GovernanceError(f"bot_profile_not_registered:{profile_id}")
        expected_soul = f"profiles/{profile_id}/SOUL.md"
        if entry.get("soul") != expected_soul:
            raise GovernanceError(f"bot_profile_soul_manifest_mismatch:{profile_id}")
        relative = Path(expected_soul)
        soul = root / relative
        if _unsafe_symlink_component(root, relative) or not soul.is_file():
            raise GovernanceError(f"missing_or_unsafe_profile_soul:{profile_id}")


def validate_policy(policy: dict[str, Any], *, root: Path | str | None = None) -> None:
    _require_exact_fields(policy, TOP_LEVEL_FIELDS, "policy")
    if policy["schema_version"] != POLICY_SCHEMA:
        raise GovernanceError("unsupported_policy_schema")
    if policy["version"] != "1.0.0":
        raise GovernanceError("unsupported_policy_version")
    if policy["bot_primitive"] != "hermes_profile":
        raise GovernanceError("bot_primitive_must_be_hermes_profile")
    if policy["model_policy"] != "inherit_existing_profile_router":
        raise GovernanceError("bot_mode_cannot_define_model_router")

    credential_policy = policy["credential_policy"]
    if not isinstance(credential_policy, dict):
        raise GovernanceError("credential_policy_must_be_object")
    _require_exact_fields(credential_policy, CREDENTIAL_POLICY_FIELDS, "credential_policy")
    if credential_policy["mode"] != "capability_brokered":
        raise GovernanceError("credential_policy_must_be_capability_brokered")
    if _require_bool(credential_policy["standing_shared_credentials"], "standing_shared_credentials"):
        raise GovernanceError("standing_shared_credentials_forbidden")

    forbidden_raw = policy["forbidden_bot_ids"]
    if not isinstance(forbidden_raw, list) or not forbidden_raw:
        raise GovernanceError("forbidden_bot_ids_required")
    forbidden: set[str] = set()
    for item in forbidden_raw:
        text = _require_nonempty_string(item, "forbidden_bot_id", max_chars=64)
        canonical = _canonical_identity(text)
        if canonical in forbidden:
            raise GovernanceError("duplicate_forbidden_bot_id")
        forbidden.add(canonical)
    required_forbidden = {
        "trust-gate", "containment-gateway", "canary-controller",
        "evidence-ledger", "omniroute", "scout", "memory-fabric",
    }
    if not required_forbidden.issubset(forbidden):
        raise GovernanceError("required_infrastructure_ids_not_forbidden")

    bots = policy["bots"]
    if not isinstance(bots, list) or not bots:
        raise GovernanceError("bots_required")
    seen_ids: set[str] = set()
    seen_profiles: set[str] = set()
    bot_classes: dict[str, set[str]] = {}
    bot_active: dict[str, bool] = {}
    for bot in bots:
        if not isinstance(bot, dict):
            raise GovernanceError("bot_must_be_object")
        _require_exact_fields(bot, BOT_FIELDS, "bot")
        raw_id = _require_nonempty_string(bot["id"], "bot_id", max_chars=64)
        if _canonical_identity(raw_id) in forbidden:
            raise GovernanceError("infrastructure_identity_cannot_be_bot")
        bot_id = _require_bot_id(raw_id)
        profile = _require_profile_id(bot["profile"])
        if bot_id in seen_ids or profile in seen_profiles:
            raise GovernanceError("duplicate_bot_or_profile")
        seen_ids.add(bot_id)
        seen_profiles.add(profile)
        _require_nonempty_string(bot["title"], "title", max_chars=120)
        _require_nonempty_string(bot["description"], "description", max_chars=1000)
        _require_nonempty_string(bot["role"], "role", max_chars=1000)
        if bot["credential_mode"] != "capability_brokered":
            raise GovernanceError("bot_credentials_must_be_capability_brokered")
        if _require_bool(bot["shared_credentials"], "shared_credentials"):
            raise GovernanceError("bot_shared_credentials_forbidden")
        if _require_bool(bot["externalization_authority"], "externalization_authority"):
            raise GovernanceError("bot_externalization_authority_forbidden")
        bot_active[bot_id] = _require_bool(bot["active"], "active")
        bot_classes[bot_id] = set(_validate_data_class_list(bot["allowed_data_classes"], "allowed_data_classes"))
        entrypoints = bot["allowed_entrypoints"]
        if not isinstance(entrypoints, list):
            raise GovernanceError("allowed_entrypoints_must_be_list")
        if len(entrypoints) != len(set(entrypoints)):
            raise GovernanceError("duplicate_allowed_entrypoint")
        for entrypoint in entrypoints:
            _require_nonempty_string(entrypoint, "allowed_entrypoint", max_chars=256)
        if bot_id == "research" and entrypoints != ["src/system/agent-reach.sh"]:
            raise GovernanceError("research_must_use_hardened_agent_reach_entrypoint")

    councils = policy["councils"]
    if not isinstance(councils, list) or not councils:
        raise GovernanceError("councils_required")
    seen_councils: set[str] = set()
    for council in councils:
        if not isinstance(council, dict):
            raise GovernanceError("council_must_be_object")
        _require_exact_fields(council, COUNCIL_FIELDS, "council")
        council_id = _require_bot_id(council["id"], "council_id")
        if council_id in seen_councils or council_id in seen_ids or _canonical_identity(council_id) in forbidden:
            raise GovernanceError("invalid_or_duplicate_council_id")
        seen_councils.add(council_id)
        _require_nonempty_string(council["title"], "council_title", max_chars=120)
        min_members = _require_int(council["min_members"], "min_members", 2, 6)
        max_members = _require_int(council["max_members"], "max_members", 2, 6)
        if min_members > max_members:
            raise GovernanceError("invalid_council_member_bounds")
        members = council["members"]
        if not isinstance(members, list) or len(members) != len(set(members)):
            raise GovernanceError("council_members_must_be_unique_list")
        if not (min_members <= len(members) <= max_members):
            raise GovernanceError("council_member_count_out_of_bounds")
        for member in members:
            member_id = _require_bot_id(member)
            if member_id not in seen_ids:
                raise GovernanceError("unknown_council_member")
            if not bot_active[member_id]:
                raise GovernanceError("inactive_bot_cannot_be_council_member")
        council_classes = set(_validate_data_class_list(council["allowed_data_classes"], "council_allowed_data_classes"))
        member_intersection = set.intersection(*(bot_classes[member] for member in members))
        if council_classes != member_intersection:
            raise GovernanceError("council_data_classes_must_equal_member_intersection")
        _require_int(council["max_rounds"], "max_rounds", 1, 3)
        _require_int(council["max_messages_per_turn"], "max_messages_per_turn", 1, 10)
        if council["output_status"] != "PROPOSAL":
            raise GovernanceError("council_output_must_be_proposal")
        if council["authority"] != "none":
            raise GovernanceError("council_authority_forbidden")
        if _require_bool(council["externalization_authorized"], "externalization_authorized"):
            raise GovernanceError("council_externalization_forbidden")
        if not _require_bool(council["requires_governance_review"], "requires_governance_review"):
            raise GovernanceError("council_governance_review_required")

    boundaries = policy["runtime_boundaries"]
    if not isinstance(boundaries, dict):
        raise GovernanceError("runtime_boundaries_must_be_object")
    _require_exact_fields(boundaries, RUNTIME_BOUNDARY_FIELDS, "runtime_boundaries")
    expected_boundaries = {
        "trust_authority": "governance-trust-gate",
        "network_authority": "containment-gateway",
        "externalization": "proof-before-success",
        "interbot_trust": "untrusted",
        "council_output": "proposal_only",
    }
    if boundaries != expected_boundaries:
        raise GovernanceError("runtime_boundaries_cannot_be_weakened")

    if root is not None:
        _validate_profile_manifest(Path(root), bots)


def _known_recipient(policy: dict[str, Any], recipient: str) -> bool:
    return recipient in _policy_bot_map(policy) or recipient in _policy_council_map(policy)


def _validate_classification(value: Any) -> str:
    if not isinstance(value, str) or value != value.strip().upper() or value not in DATA_CLASSES:
        raise GovernanceError("invalid_or_noncanonical_classification")
    return value


def _enforce_message_flow(policy: dict[str, Any], sender: str, recipient: str, classification: str) -> None:
    bot_map = _policy_bot_map(policy)
    council_map = _policy_council_map(policy)
    sender_bot = bot_map.get(sender)
    if sender_bot is None:
        raise GovernanceError("unknown_sender")
    if not sender_bot["active"]:
        raise GovernanceError("inactive_sender")
    if classification not in sender_bot["allowed_data_classes"]:
        raise GovernanceError("sender_classification_not_allowed")
    recipient_bot = bot_map.get(recipient)
    if recipient_bot is not None:
        if not recipient_bot["active"]:
            raise GovernanceError("inactive_recipient")
        target = recipient_bot
    else:
        target = council_map.get(recipient)
    if target is None:
        raise GovernanceError("unknown_recipient")
    if classification not in target["allowed_data_classes"]:
        raise GovernanceError("recipient_classification_not_allowed")


def _validate_body(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise GovernanceError(f"{label}_must_be_nonempty_string")
    if len(value.encode("utf-8")) > MAX_BODY_BYTES:
        raise GovernanceError(f"{label}_too_large")
    return value


def create_message(
    policy: dict[str, Any], *, sender: str, recipient: str, classification: str,
    purpose: str, body: str, evidence_parent: str,
) -> dict[str, Any]:
    validate_policy(policy)
    sender_id = _require_bot_id(sender, "sender")
    recipient_id = _require_bot_id(recipient, "recipient")
    if sender_id not in _policy_bot_map(policy):
        raise GovernanceError("unknown_sender")
    if not _known_recipient(policy, recipient_id):
        raise GovernanceError("unknown_recipient")
    classification = _validate_classification(classification)
    _enforce_message_flow(policy, sender_id, recipient_id, classification)
    purpose = _require_token(purpose, "purpose")
    evidence_parent = _require_token(evidence_parent, "evidence_parent")
    body = _validate_body(body, "body")
    return {
        "schema_version": MESSAGE_SCHEMA,
        "message_id": f"msg_{uuid.uuid4().hex}",
        "sender": sender_id,
        "recipient": recipient_id,
        "classification": classification,
        "purpose": purpose,
        "body": body,
        "body_sha256": sha256_text(body),
        "evidence_parent": evidence_parent,
        "created_at": utc_now(),
        "trust": "untrusted",
        "authority": "none",
        "externalization_authorized": False,
    }


def verify_message(policy: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    if not isinstance(message, dict):
        raise GovernanceError("message_must_be_object")
    _require_exact_fields(message, MESSAGE_FIELDS, "message")
    if message["schema_version"] != MESSAGE_SCHEMA:
        raise GovernanceError("unsupported_message_schema")
    if not isinstance(message["message_id"], str) or not MSG_ID_RE.fullmatch(message["message_id"]):
        raise GovernanceError("invalid_message_id")
    sender = _require_bot_id(message["sender"], "sender")
    recipient = _require_bot_id(message["recipient"], "recipient")
    if sender not in _policy_bot_map(policy):
        raise GovernanceError("unknown_sender")
    if not _known_recipient(policy, recipient):
        raise GovernanceError("unknown_recipient")
    classification = _validate_classification(message["classification"])
    _enforce_message_flow(policy, sender, recipient, classification)
    _require_token(message["purpose"], "purpose")
    _require_token(message["evidence_parent"], "evidence_parent")
    body = _validate_body(message["body"], "body")
    if not isinstance(message["body_sha256"], str) or not HEX64_RE.fullmatch(message["body_sha256"]):
        raise GovernanceError("invalid_body_digest")
    if message["body_sha256"] != sha256_text(body):
        raise GovernanceError("message_digest_mismatch")
    _require_timestamp(message["created_at"])
    if message["trust"] != "untrusted":
        raise GovernanceError("interbot_message_must_be_untrusted")
    if message["authority"] != "none":
        raise GovernanceError("interbot_message_has_no_authority")
    if _require_bool(message["externalization_authorized"], "externalization_authorized"):
        raise GovernanceError("interbot_message_cannot_authorize_externalization")
    return {
        "decision": "ACCEPT_AS_UNTRUSTED_DATA",
        "message_id": message["message_id"],
        "body_sha256": message["body_sha256"],
        "evidence_parent": message["evidence_parent"],
    }


def _deliberation_digest(
    *, council_id: str, members: list[str], classification: str, rounds: int,
    message_count: int, proposal_sha256: str, evidence_parents: list[str],
) -> str:
    payload = {
        "council_id": council_id,
        "members": members,
        "classification": classification,
        "rounds": rounds,
        "message_count": message_count,
        "proposal_sha256": proposal_sha256,
        "evidence_parents": evidence_parents,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def create_council_proposal(
    policy: dict[str, Any], *, council_id: str, rounds: int, message_count: int,
    proposal: str, evidence_parents: list[str], classification: str = "INTERNAL",
) -> dict[str, Any]:
    validate_policy(policy)
    council_id = _require_bot_id(council_id, "council_id")
    council = _policy_council_map(policy).get(council_id)
    if council is None:
        raise GovernanceError("unknown_council")
    classification = _validate_classification(classification)
    if classification not in council["allowed_data_classes"]:
        raise GovernanceError("council_proposal_classification_not_allowed")
    rounds = _require_int(rounds, "rounds", 1, council["max_rounds"])
    message_count = _require_int(message_count, "message_count", 1, council["max_messages_per_turn"])
    proposal = _validate_body(proposal, "proposal")
    if not isinstance(evidence_parents, list) or not evidence_parents:
        raise GovernanceError("evidence_parents_required")
    if len(evidence_parents) != len(set(evidence_parents)):
        raise GovernanceError("duplicate_evidence_parent")
    parents = [_require_token(value, "evidence_parent") for value in evidence_parents]
    members = list(council["members"])
    proposal_sha = sha256_text(proposal)
    return {
        "schema_version": PROPOSAL_SCHEMA,
        "proposal_id": f"proposal_{uuid.uuid4().hex}",
        "council_id": council_id,
        "members": members,
        "classification": classification,
        "rounds": rounds,
        "message_count": message_count,
        "proposal": proposal,
        "proposal_sha256": proposal_sha,
        "deliberation_sha256": _deliberation_digest(
            council_id=council_id, members=members, classification=classification,
            rounds=rounds, message_count=message_count,
            proposal_sha256=proposal_sha, evidence_parents=parents,
        ),
        "evidence_parents": parents,
        "created_at": utc_now(),
        "status": "PROPOSAL",
        "trust": "untrusted",
        "authority": "none",
        "externalization_authorized": False,
        "requires_governance_review": True,
    }


def verify_council_proposal(policy: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    if not isinstance(proposal, dict):
        raise GovernanceError("proposal_must_be_object")
    _require_exact_fields(proposal, PROPOSAL_FIELDS, "proposal")
    if proposal["schema_version"] != PROPOSAL_SCHEMA:
        raise GovernanceError("unsupported_proposal_schema")
    if not isinstance(proposal["proposal_id"], str) or not PROPOSAL_ID_RE.fullmatch(proposal["proposal_id"]):
        raise GovernanceError("invalid_proposal_id")
    council_id = _require_bot_id(proposal["council_id"], "council_id")
    council = _policy_council_map(policy).get(council_id)
    if council is None:
        raise GovernanceError("unknown_council")
    if proposal["members"] != council["members"] or len(set(proposal["members"])) != len(proposal["members"]):
        raise GovernanceError("proposal_members_must_match_governed_council")
    classification = _validate_classification(proposal["classification"])
    if classification not in council["allowed_data_classes"]:
        raise GovernanceError("council_proposal_classification_not_allowed")
    _require_int(proposal["rounds"], "rounds", 1, council["max_rounds"])
    _require_int(proposal["message_count"], "message_count", 1, council["max_messages_per_turn"])
    body = _validate_body(proposal["proposal"], "proposal")
    if not isinstance(proposal["proposal_sha256"], str) or not HEX64_RE.fullmatch(proposal["proposal_sha256"]):
        raise GovernanceError("invalid_proposal_digest")
    expected_proposal_sha = sha256_text(body)
    if proposal["proposal_sha256"] != expected_proposal_sha:
        raise GovernanceError("proposal_digest_mismatch")
    parents = proposal["evidence_parents"]
    if not isinstance(parents, list) or not parents or len(parents) != len(set(parents)):
        raise GovernanceError("invalid_evidence_parents")
    validated_parents = [_require_token(value, "evidence_parent") for value in parents]
    expected_deliberation = _deliberation_digest(
        council_id=council_id, members=proposal["members"], classification=classification,
        rounds=proposal["rounds"], message_count=proposal["message_count"],
        proposal_sha256=expected_proposal_sha, evidence_parents=validated_parents,
    )
    if not isinstance(proposal["deliberation_sha256"], str) or not HEX64_RE.fullmatch(proposal["deliberation_sha256"]):
        raise GovernanceError("invalid_deliberation_digest")
    if proposal["deliberation_sha256"] != expected_deliberation:
        raise GovernanceError("deliberation_digest_mismatch")
    _require_timestamp(proposal["created_at"])
    if proposal["status"] != "PROPOSAL":
        raise GovernanceError("council_status_must_be_proposal")
    if proposal["trust"] != "untrusted":
        raise GovernanceError("council_output_must_be_untrusted")
    if proposal["authority"] != "none":
        raise GovernanceError("council_has_no_execution_authority")
    if _require_bool(proposal["externalization_authorized"], "externalization_authorized"):
        raise GovernanceError("council_cannot_authorize_externalization")
    if not _require_bool(proposal["requires_governance_review"], "requires_governance_review"):
        raise GovernanceError("council_requires_governance_review")
    return {
        "decision": "PROPOSAL_ONLY",
        "proposal_id": proposal["proposal_id"],
        "classification": classification,
        "deliberation_sha256": proposal["deliberation_sha256"],
        "requires_governance_review": True,
    }


def _read_text_file(path: str, label: str) -> str:
    target = Path(path)
    if target.is_symlink():
        raise GovernanceError(f"{label}_symlink_rejected")
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise GovernanceError(f"{label}_read_failed:{exc.__class__.__name__}") from exc
    if len(data) > MAX_BODY_BYTES:
        raise GovernanceError(f"{label}_too_large")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GovernanceError(f"{label}_not_utf8") from exc


def _read_json_file(path: str) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink():
        raise GovernanceError("input_symlink_rejected")
    try:
        payload = _load_json_bytes(target.read_bytes())
    except OSError as exc:
        raise GovernanceError(f"input_read_failed:{exc.__class__.__name__}") from exc
    if not isinstance(payload, dict):
        raise GovernanceError("input_must_be_object")
    return payload


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_policy() -> dict[str, Any]:
    root = _repo_root()
    policy = load_policy(root / "config/bot-mode-policy.json")
    validate_policy(policy, root=root)
    return policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes governed Bot Mode contracts")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-policy", help="validate the repo-owned Bot Mode policy")

    msg_create = sub.add_parser("message-create", help="create an untrusted inter-Bot message envelope")
    msg_create.add_argument("--sender", required=True)
    msg_create.add_argument("--recipient", required=True)
    msg_create.add_argument("--classification", required=True, choices=sorted(DATA_CLASSES))
    msg_create.add_argument("--purpose", required=True)
    msg_create.add_argument("--body-file", required=True)
    msg_create.add_argument("--evidence-parent", required=True)

    msg_verify = sub.add_parser("message-verify", help="verify an inter-Bot message as untrusted data")
    msg_verify.add_argument("--input", required=True)

    council_create = sub.add_parser("council-create", help="create a proposal-only Council artifact")
    council_create.add_argument("--council", default="hermes-council")
    council_create.add_argument("--classification", required=True, choices=sorted(DATA_CLASSES))
    council_create.add_argument("--rounds", required=True, type=int)
    council_create.add_argument("--message-count", required=True, type=int)
    council_create.add_argument("--proposal-file", required=True)
    council_create.add_argument("--evidence-parent", action="append", required=True)

    council_verify = sub.add_parser("council-verify", help="verify a proposal-only Council artifact")
    council_verify.add_argument("--input", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        policy = _runtime_policy()
        if args.command == "validate-policy":
            output: Any = {
                "valid": True, "schema_version": policy["schema_version"],
                "bots": len(policy["bots"]), "councils": len(policy["councils"]),
            }
        elif args.command == "message-create":
            output = create_message(
                policy, sender=args.sender, recipient=args.recipient,
                classification=args.classification, purpose=args.purpose,
                body=_read_text_file(args.body_file, "body_file"),
                evidence_parent=args.evidence_parent,
            )
        elif args.command == "message-verify":
            output = verify_message(policy, _read_json_file(args.input))
        elif args.command == "council-create":
            output = create_council_proposal(
                policy, council_id=args.council, classification=args.classification,
                rounds=args.rounds, message_count=args.message_count,
                proposal=_read_text_file(args.proposal_file, "proposal_file"),
                evidence_parents=args.evidence_parent,
            )
        elif args.command == "council-verify":
            output = verify_council_proposal(policy, _read_json_file(args.input))
        else:  # pragma: no cover
            parser.error("unknown command")
            return 2
    except GovernanceError as exc:
        print(json.dumps({"decision": "DENY", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
