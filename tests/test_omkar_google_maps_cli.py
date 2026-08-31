import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src/system/omkar-google-maps-provider.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def test_normalize_writes_funnel_prospects_and_revenue_cost(tmp_path):
    raw = [
        {"KGMID": "/g/one", "NAME": "Ace Plumbing", "MAIN_CATEGORY": "Plumber", "PHONE": "555-0100", "LINK": "https://maps.example/one", "API_KEY": "never-persist"},
        {"KGMID": "/g/one", "NAME": "Duplicate Ace", "PLACE_ID": "other"},
    ]
    source = tmp_path / "omkar.json"
    output = tmp_path / "prospects.json"
    revenue = tmp_path / "revenue"
    source.write_text(json.dumps(raw))
    result = run_cli("normalize", "--results-file", source, "--out", output,
                     "--city", "Riverside", "--state", "CA",
                     "--allocated-cost-usd", "0.50", "--experiment-id", "exp-1",
                     "--revenue-root", revenue, "--repo-root", ROOT)
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text())
    assert data["schema_version"] == "omkar-google-maps-leads-v1"
    assert data["provider"] == "omkar-google-maps"
    assert data["outreach_performed"] is False
    assert data["metrics"] == {"leads": 1, "tool_cost": 0.5}
    assert len(data["prospects"]) == 1
    assert data["prospects"][0]["business_name"] == "Ace Plumbing"
    assert data["prospects"][0]["city"] == "Riverside"
    assert "never-persist" not in output.read_text()
    events = [json.loads(line) for line in (revenue / "revenue-events.jsonl").read_text().splitlines()]
    assert len(events) == 1
    assert events[0]["event_type"] == "lead"
    assert events[0]["source"] == "omkar-google-maps"
    assert events[0]["metrics"]["leads"] == 1
    assert events[0]["metrics"]["tool_cost"] == 0.5


def test_cli_has_no_outreach_or_send_surface():
    result = run_cli("--help")
    assert result.returncode == 0
    help_text = result.stdout.lower()
    assert "normalize" in help_text and "discover" in help_text
    assert "send" not in help_text
    assert "outreach" not in help_text


def test_discover_rejects_non_loopback_before_network_use(tmp_path):
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"queries": ["plumbers"]}))
    result = run_cli("discover", "--payload-file", payload, "--api-url", "http://10.0.0.4:8000")
    assert result.returncode != 0
    assert "loopback" in result.stderr.lower()
