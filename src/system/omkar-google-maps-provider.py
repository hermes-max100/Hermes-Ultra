#!/usr/bin/env python3
"""Private Google Maps lead discovery bridge for Hermes Revenue OS."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hermes_ultra.economic.adapters.omkar_google_maps import (  # noqa: E402
    OmkarGoogleMapsAdapter,
    OmkarProviderError,
)


class StaticResultsApi:
    def __init__(self, rows):
        self.rows = rows

    def create_sync_task(self, payload):
        return {"id": "file", "result": self.rows}

    def get_task_results(self, task_id):
        return self.rows


def load_json(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OmkarProviderError(f"cannot read JSON input: {exc}") from exc
    return value


def rows_from_file(path: Path) -> list[Mapping[str, object]]:
    value = load_json(path)
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("result", "results", "data", "prospects"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, Mapping)]
    raise OmkarProviderError("results file must contain a list of business records")


def write_output(path: Path, *, batch, city: str, state: str) -> dict[str, object]:
    payload = {
        "schema_version": "omkar-google-maps-leads-v1",
        "provider": "omkar-google-maps",
        "prospects": batch.prospects(city=city, state=state),
        "metrics": {"leads": len(batch.leads), "tool_cost": float(batch.allocated_cost_usd)},
        "outreach_performed": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def record_revenue_event(args, payload: Mapping[str, object]) -> None:
    if not args.experiment_id:
        return
    ledger = ROOT / "src/system/revenue-ledger.py"
    metrics = payload["metrics"]
    cmd = [
        sys.executable, str(ledger), "record-event",
        "--root", str(args.revenue_root),
        "--repo-root", str(args.repo_root),
        "--experiment-id", str(args.experiment_id),
        "--event-type", "lead",
        "--action", "analysis",
        "--source", "omkar-google-maps",
        "--leads", str(metrics["leads"]),
        "--tool-cost", str(metrics["tool_cost"]),
        "--metadata", "provider=omkar-google-maps",
    ]
    subprocess.run(cmd, check=True, cwd=ROOT, capture_output=True, text=True)


def finalize(args, batch) -> int:
    payload = write_output(Path(args.out), batch=batch, city=args.city, state=args.state)
    record_revenue_event(args, payload)
    print(json.dumps({"provider": "omkar-google-maps", "leads": len(batch.leads), "output": str(args.out)}, sort_keys=True))
    return 0


def cmd_normalize(args) -> int:
    rows = rows_from_file(Path(args.results_file))
    adapter = OmkarGoogleMapsAdapter(api=StaticResultsApi(rows))
    batch = adapter.discover({"source": "exported-results"}, allocated_cost_usd=args.allocated_cost_usd)
    return finalize(args, batch)


def cmd_discover(args) -> int:
    payload = load_json(Path(args.payload_file))
    if not isinstance(payload, Mapping) or not payload:
        raise OmkarProviderError("task payload must be a JSON object")
    adapter = OmkarGoogleMapsAdapter.from_api_url(args.api_url)
    batch = adapter.discover(payload, allocated_cost_usd=args.allocated_cost_usd)
    return finalize(args, batch)


def add_output_args(parser):
    parser.add_argument("--out", default="omkar-prospects.json")
    parser.add_argument("--city", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--allocated-cost-usd", default="0")
    parser.add_argument("--experiment-id", default="")
    parser.add_argument("--revenue-root", default=str(Path(".hermes/revenue-os")))
    parser.add_argument("--repo-root", default=str(ROOT))


def build_parser():
    parser = argparse.ArgumentParser(description="Hermes Revenue OS Google Maps lead discovery provider")
    sub = parser.add_subparsers(dest="command", required=True)

    normalize = sub.add_parser("normalize", help="normalize exported business results")
    normalize.add_argument("--results-file", required=True)
    add_output_args(normalize)
    normalize.set_defaults(func=cmd_normalize)

    discover = sub.add_parser("discover", help="run a private local discovery task")
    discover.add_argument("--payload-file", required=True)
    discover.add_argument("--api-url", default="http://127.0.0.1:8000")
    add_output_args(discover)
    discover.set_defaults(func=cmd_discover)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except OmkarProviderError as exc:
        print(f"omkar provider error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
