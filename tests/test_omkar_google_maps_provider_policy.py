import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text())


def test_omkar_provider_is_private_revenue_os_discovery_only():
    policy = load("config/omkar-google-maps-provider.json")
    assert policy["schema_version"] == 1
    assert policy["provider_id"] == "omkar-google-maps"
    assert policy["profile"] == "REVENUE_OS"
    assert policy["network"]["api_url"] == "http://127.0.0.1:8000"
    assert policy["network"]["public_ingress"] is False
    assert policy["network"]["bind_scope"] == "loopback"


def test_omkar_provider_has_pinned_client_and_no_outreach_authority():
    policy = load("config/omkar-google-maps-provider.json")
    assert policy["authority"]["outreach"] == "none"
    assert policy["authority"]["external_messages"] is False
    assert policy["identity"]["unique_identifier_order"] == ["KGMID", "PLACE_ID", "DATA_ID", "CID"]
    assert policy["client"]["package"] == "botasaurus-api"
    assert policy["client"]["version"] == "4.0.10"
    assert policy["client"]["sdist_sha256"] == "009fd7f59abba11725fe02d61b985757e9239a57afb6595b48b4da6ad4ed0a94"
    assert policy["cost_attribution"]["metric"] == "tool_cost"
    assert policy["downstream"] == ["local-service-funnel", "revenue-ledger"]


def test_revenue_os_policy_admits_discovery_and_tracks_completed_outcomes():
    policy = load("config/revenue-os-policy.example.json")
    assert "discover_public_leads" in policy["allowed_without_approval"]
    secondary = set(policy["metrics"]["secondary"])
    assert {"appointments_booked", "attributed_revenue", "gross_margin", "cost_per_completed_outcome"} <= secondary
    assert "send" in policy["approval_required"]
    assert "post" in policy["approval_required"]
