#!/usr/bin/env python3
"""Dynamic skill evolution dashboard for Hermes."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def load_jsonl(path: Path, since: str | None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since and str(row.get("ts", ""))[:10] < since:
            continue
        rows.append(row)
    return rows


def load_skill_metas(skills_home: Path) -> dict[str, dict[str, str]]:
    skills_file = skills_home / "skills.txt"
    skills_dir = skills_home / "skills.d"
    metas: dict[str, dict[str, str]] = {}
    if not skills_file.is_file():
        return metas
    for line in skills_file.read_text(encoding="utf-8").splitlines():
        skill = line.strip()
        if not skill:
            continue
        meta_path = skills_dir / skill / "meta.env"
        meta: dict[str, str] = {}
        if meta_path.is_file():
            for raw in meta_path.read_text(encoding="utf-8", errors="replace").splitlines():
                raw = raw.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, _, value = raw.partition("=")
                meta[key.strip()] = value.strip().strip('"').strip("'")
        metas[skill] = meta
    return metas


def compute_skill_health(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    health: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"success": 0, "failure": 0, "partial": 0, "blocked": 0, "total": 0}
    )
    for event in events:
        skill = str(event.get("skill", "")).strip()
        if not skill:
            continue
        outcome = str(event.get("outcome", "unknown"))
        if outcome in health[skill]:
            health[skill][outcome] += 1
        health[skill]["total"] += 1
    return dict(health)


def compute_routing_accuracy(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_project: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "total": 0})
    by_day: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "total": 0})

    for event in events:
        project = str(event.get("project") or "default")
        outcome = str(event.get("outcome", ""))
        day = str(event.get("ts", ""))[:10]
        by_project[project]["total"] += 1
        if day:
            by_day[day]["total"] += 1
        if outcome == "success":
            by_project[project]["success"] += 1
            if day:
                by_day[day]["success"] += 1

    total = sum(item["total"] for item in by_project.values())
    success = sum(item["success"] for item in by_project.values())
    per_project = {
        project: round(item["success"] / item["total"], 4) if item["total"] else 0.0
        for project, item in by_project.items()
    }
    trend = [
        {
            "date": day,
            "accuracy": round(item["success"] / item["total"], 4) if item["total"] else 0.0,
            "tasks": item["total"],
        }
        for day, item in sorted(by_day.items())
    ]
    return {
        "overall": round(success / total, 4) if total else 0.0,
        "total": total,
        "success": success,
        "per_project": per_project,
        "trend": trend,
    }


def compute_rubric_drift(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    histories: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        skill = str(snapshot.get("skill", "")).strip()
        rubric = str(snapshot.get("rubric", "unknown")).strip() or "unknown"
        if not skill or snapshot.get("score") is None:
            continue
        try:
            score = float(snapshot["score"])
        except (TypeError, ValueError):
            continue
        histories[(skill, rubric)].append({"ts": str(snapshot.get("ts", "")), "score": score})

    drift: dict[str, dict[str, Any]] = {}
    for (skill, rubric), history in histories.items():
        history.sort(key=lambda item: item["ts"])
        if len(history) < 2:
            continue
        first = history[0]["score"]
        last = history[-1]["score"]
        scores = [item["score"] for item in history]
        delta = last - first
        volatility = max(scores) - min(scores)
        key = f"{skill}:{rubric}"
        drift[key] = {
            "skill": skill,
            "rubric": rubric,
            "first_score": round(first, 2),
            "last_score": round(last, 2),
            "delta": round(delta, 2),
            "volatility": round(volatility, 2),
            "snapshots": len(history),
            "drifting": abs(delta) >= 5.0 or volatility >= 10.0,
        }
    return drift


def compute_evolution_pressure(events: list[dict[str, Any]], threshold: int = 2) -> dict[str, dict[str, Any]]:
    failures: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for event in events:
        if event.get("outcome") not in {"failure", "partial", "blocked"}:
            continue
        skill = str(event.get("skill", "")).strip()
        if not skill:
            continue
        failures[skill].append(
            {
                "ts": str(event.get("ts", "")),
                "project": str(event.get("project", "")),
                "note": str(event.get("note", "")),
            }
        )

    pressure: dict[str, dict[str, Any]] = {}
    stop = {"missed", "needed", "skill", "terms", "trigger", "failure", "partial", "blocked"}
    for skill, items in failures.items():
        word_freq: Counter[str] = Counter()
        for item in items:
            words = re.findall(r"[a-z][a-z0-9._-]{3,}", item["note"].lower())
            word_freq.update(word for word in words if word not in stop)
        pressure[skill] = {
            "failure_count": len(items),
            "latest_note": items[-1]["note"],
            "themes": [word for word, _ in word_freq.most_common(5)],
            "needs_proposal": len(items) >= threshold,
        }
    return pressure


def dashboard_rows(
    metas: dict[str, dict[str, str]],
    health: dict[str, dict[str, int]],
    drift: dict[str, dict[str, Any]],
    pressure: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    drift_by_skill: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in drift.values():
        drift_by_skill[str(item["skill"])].append(item)

    skills = sorted(set(metas) | set(health) | set(drift_by_skill) | set(pressure))
    rows = []
    for skill in skills:
        h = health.get(skill, {"success": 0, "failure": 0, "partial": 0, "blocked": 0, "total": 0})
        p = pressure.get(skill, {"failure_count": 0, "needs_proposal": False, "themes": [], "latest_note": ""})
        drift_items = drift_by_skill.get(skill, [])
        worst_drift = max(drift_items, key=lambda item: abs(float(item["delta"])), default={})
        total = h["total"]
        rows.append(
            {
                "skill": skill,
                "version": metas.get(skill, {}).get("VERSION", ""),
                "risk_level": metas.get(skill, {}).get("RISK_LEVEL", ""),
                "total": total,
                "success": h["success"],
                "failure": h["failure"],
                "partial": h["partial"],
                "blocked": h["blocked"],
                "success_rate": round(h["success"] / total, 4) if total else 0.0,
                "weak_signals": h["failure"] + h["partial"] + h["blocked"],
                "drift_delta": worst_drift.get("delta", 0.0),
                "drift_volatility": worst_drift.get("volatility", 0.0),
                "drift_rubric": worst_drift.get("rubric", ""),
                "drifting": any(bool(item["drifting"]) for item in drift_items),
                "needs_proposal": bool(p["needs_proposal"]),
                "failure_themes": ",".join(p["themes"]),
                "latest_note": p["latest_note"],
            }
        )
    rows.sort(key=lambda row: (bool(row["needs_proposal"]), bool(row["drifting"]), int(row["weak_signals"]), int(row["total"])), reverse=True)
    return rows


def render_markdown(
    metas: dict[str, dict[str, str]],
    events: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    routing: dict[str, Any],
    health: dict[str, dict[str, int]],
    drift: dict[str, dict[str, Any]],
    pressure: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    since: str | None,
) -> str:
    lines = ["# Skill Evolution Dashboard", ""]
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if since:
        lines.append(f"Since: {since}")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Total skills registered | {len(metas)} |")
    lines.append(f"| Total logged tasks | {len(events)} |")
    lines.append(f"| Score snapshots | {len(snapshots)} |")
    lines.append(f"| Overall routing accuracy | {routing['overall']:.1%} |")
    lines.append(f"| Skills with drift detected | {sum(1 for item in drift.values() if item['drifting'])} |")
    lines.append(f"| Skills needing evolution proposals | {sum(1 for item in pressure.values() if item['needs_proposal'])} |")
    lines.append("")

    if routing["trend"]:
        lines.append("## Routing Accuracy Trend")
        lines.append("")
        lines.append("| Date | Accuracy | Tasks |")
        lines.append("|---|---:|---:|")
        for item in routing["trend"]:
            lines.append(f"| {item['date']} | {item['accuracy']:.1%} | {item['tasks']} |")
        lines.append("")

    if routing["per_project"]:
        lines.append("## Per-Project Routing Accuracy")
        lines.append("")
        lines.append("| Project | Accuracy |")
        lines.append("|---|---:|")
        for project, accuracy in sorted(routing["per_project"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"| {project} | {accuracy:.1%} |")
        lines.append("")

    lines.append("## Skill Health")
    lines.append("")
    lines.append("| Skill | Version | Risk | Total | Success | Failure | Partial | Blocked | Success Rate |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        if not row["total"]:
            continue
        lines.append(
            f"| {row['skill']} | {row['version']} | {row['risk_level']} | {row['total']} | "
            f"{row['success']} | {row['failure']} | {row['partial']} | {row['blocked']} | {row['success_rate']:.1%} |"
        )
    if not any(row["total"] for row in rows):
        lines.append("| No logged task outcomes yet. |  |  | 0 | 0 | 0 | 0 | 0 | 0.0% |")
    lines.append("")

    lines.append("## Rubric Drift Detection")
    lines.append("")
    lines.append("Drift is flagged when score delta is at least 5 points or volatility is at least 10 points.")
    lines.append("")
    if drift:
        lines.append("| Skill | Rubric | First | Last | Delta | Volatility | Snapshots | Drifting |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---|")
        for item in sorted(drift.values(), key=lambda entry: (bool(entry["drifting"]), abs(float(entry["delta"]))), reverse=True):
            flag = "YES" if item["drifting"] else "no"
            lines.append(
                f"| {item['skill']} | {item['rubric']} | {item['first_score']} | {item['last_score']} | "
                f"{float(item['delta']):+.1f} | {item['volatility']} | {item['snapshots']} | {flag} |"
            )
    else:
        lines.append("No score snapshots with enough history to measure drift.")
    lines.append("")

    lines.append("## Evolution Pressure")
    lines.append("")
    if pressure:
        lines.append("| Skill | Weak Signals | Themes | Latest Note | Needs Proposal |")
        lines.append("|---|---:|---|---|---|")
        for skill, item in sorted(pressure.items(), key=lambda entry: (entry[1]["needs_proposal"], entry[1]["failure_count"]), reverse=True):
            themes = ", ".join(item["themes"][:4])
            note = item["latest_note"][:90]
            lines.append(f"| {skill} | {item['failure_count']} | {themes} | {note} | {'YES' if item['needs_proposal'] else 'no'} |")
    else:
        lines.append("No weak skill signals logged.")
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    recommendations = []
    drifting = sorted({str(item["skill"]) for item in drift.values() if item["drifting"]})
    needs_proposal = sorted(skill for skill, item in pressure.items() if item["needs_proposal"])
    if drifting:
        recommendations.append(f"- Review rubric drift for: {', '.join(drifting[:5])}.")
    if needs_proposal:
        recommendations.append(f"- Run `src/system/skill-evolver.sh propose <project>` for repeated weak signals: {', '.join(needs_proposal[:5])}.")
    if routing["overall"] < 0.7 and routing["total"] >= 5:
        recommendations.append("- Routing accuracy is below 70%; add missing trigger/output terms or split overloaded skills.")
    if not recommendations:
        recommendations.append("- System is stable. Keep collecting events and score snapshots.")
    lines.extend(recommendations)
    lines.append("")
    return "\n".join(lines)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "skill",
        "version",
        "risk_level",
        "total",
        "success",
        "failure",
        "partial",
        "blocked",
        "success_rate",
        "weak_signals",
        "drift_delta",
        "drift_volatility",
        "drift_rubric",
        "drifting",
        "needs_proposal",
        "failure_themes",
        "latest_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Hermes skill evolution dashboard.")
    parser.add_argument("--skills-home", default=".skills")
    parser.add_argument("--since", help="YYYY-MM-DD lower bound")
    parser.add_argument("--csv", help="Optional CSV output path")
    args = parser.parse_args()

    if args.since:
        date.fromisoformat(args.since)
    skills_home = Path(args.skills_home)
    events = load_jsonl(skills_home / "logs" / "skill-events.jsonl", args.since)
    snapshots = load_jsonl(skills_home / "logs" / "score-snapshots.jsonl", args.since)
    metas = load_skill_metas(skills_home)
    routing = compute_routing_accuracy(events)
    health = compute_skill_health(events)
    drift = compute_rubric_drift(snapshots)
    pressure = compute_evolution_pressure(events)
    rows = dashboard_rows(metas, health, drift, pressure)

    print(render_markdown(metas, events, snapshots, routing, health, drift, pressure, rows, args.since))
    if args.csv:
        write_csv(rows, Path(args.csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
