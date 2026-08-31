from decimal import Decimal

import pytest

from hermes_ultra.economic.adapters.omkar_google_maps import (
    OmkarGoogleMapsAdapter,
    OmkarProviderError,
)


class FakeApi:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def create_sync_task(self, payload):
        self.calls.append(payload)
        return {"id": 17, "result": self.rows}


def sample_row(**overrides):
    row = {
        "KGMID": "/g/11abc",
        "PLACE_ID": "place-1",
        "NAME": "River City Plumbing",
        "MAIN_CATEGORY": "Plumber",
        "ADDRESS": "100 Main St, Riverside, CA",
        "PHONE": "+1 555 0100",
        "WEBSITE": "https://rivercity.example",
        "LINK": "https://maps.google.com/?cid=123",
        "RATING": 4.7,
        "REVIEWS": 83,
    }
    row.update(overrides)
    return row


def test_provider_is_loopback_only():
    OmkarGoogleMapsAdapter(api=FakeApi([]), api_url="http://127.0.0.1:8000")
    with pytest.raises(OmkarProviderError, match="loopback"):
        OmkarGoogleMapsAdapter(api=FakeApi([]), api_url="http://10.0.0.4:8000")


def test_discovery_normalizes_and_deduplicates_by_kgmid():
    api = FakeApi([sample_row(), sample_row(PLACE_ID="place-2", PHONE="different")])
    adapter = OmkarGoogleMapsAdapter(api=api)
    batch = adapter.discover({"queries": ["plumbers in Riverside, CA"]}, allocated_cost_usd="0.40")
    assert len(batch.leads) == 1
    assert batch.leads[0].provider_key == "kgmid:/g/11abc"
    assert batch.allocated_cost_usd == Decimal("0.40")
    assert api.calls == [{"queries": ["plumbers in Riverside, CA"]}]


def test_prospect_output_matches_local_service_funnel_contract():
    batch = OmkarGoogleMapsAdapter(api=FakeApi([sample_row()])).discover(
        {"queries": ["plumbers in Riverside, CA"]}
    )
    prospect = batch.prospects(city="Riverside", state="CA")[0]
    assert prospect["prospect_id"].startswith("omkar_")
    assert prospect["business_name"] == "River City Plumbing"
    assert prospect["category"] == "Plumber"
    assert prospect["city"] == "Riverside"
    assert prospect["state"] == "CA"
    assert prospect["contact_channel"] == "phone"
    assert prospect["contact_ref"] == "+1 555 0100"
    assert prospect["evidence_refs"] == [{"type": "source", "ref": "https://maps.google.com/?cid=123"}]


def test_revenue_event_attribution_tracks_leads_and_tool_cost():
    batch = OmkarGoogleMapsAdapter(api=FakeApi([sample_row(), sample_row(KGMID="/g/22def")])).discover(
        {"queries": ["plumbers"]}, allocated_cost_usd="1.25"
    )
    event = batch.revenue_event(experiment_id="exp-plumber-1")
    assert event["event_type"] == "lead"
    assert event["action"] == "analysis"
    assert event["source"] == "omkar-google-maps"
    assert event["metrics"] == {"leads": 2, "tool_cost": Decimal("1.25")}
    assert event["human_approved"] is False


def test_raw_credentials_are_not_persisted_in_lead_output():
    row = sample_row(API_KEY="secret-key", AUTH_TOKEN="secret-token", EMAIL="sales@example.com")
    lead = OmkarGoogleMapsAdapter(api=FakeApi([row])).discover({"queries": ["plumbers"]}).leads[0]
    rendered = repr(lead).lower()
    assert "secret-key" not in rendered
    assert "secret-token" not in rendered
