#!/usr/bin/env python3
"""Deterministic promotion gate for the graph-loop prompt library.

Model workers draft and score prompts. This module alone decides whether a
scored prompt may enter the library, and it re-derives every verdict from the
prompt text and scorecard instead of trusting a verdict passed to it.

All score arithmetic is integer (tenths x hundredths = thousandths) so the
9.5 bar and 9.0 floor are exact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUBRIC = ROOT / "config" / "prompt-rubric.json"
DEFAULT_LIBRARY = ROOT / "prompt-library"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")

PASS = "PASS"
BLOCK_GATE = "BLOCK_GATE"
BLOCK_FLOOR = "BLOCK_FLOOR"
REVISE = "REVISE"
INVALID = "INVALID"


class GateError(ValueError):
    """Input that cannot be evaluated at all (bad rubric, bad slug, bad state)."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_rubric(path: Path = DEFAULT_RUBRIC) -> dict:
    rubric = load_json(path)
    dims = rubric.get("dimensions") or []
    ids = [d["id"] for d in dims]
    if len(ids) != len(set(ids)):
        raise GateError("rubric dimension ids are not unique")
    total = sum(int(d["weight_hundredths"]) for d in dims)
    if total != 100:
        raise GateError(f"rubric weights sum to {total}/100, expected 100")
    gate_ids = [g["id"] for g in rubric.get("gates") or []]
    if len(gate_ids) != len(set(gate_ids)) or not gate_ids:
        raise GateError("rubric gates missing or not unique")
    return rubric


# ---------------------------------------------------------------- N2 audit


def _sections(text: str) -> dict[str, str]:
    """Map normalized heading -> body text up to the next heading."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def lint_gates(text: str, rubric: Mapping[str, Any]) -> list[dict]:
    """Binary gate checks. Necessary, not sufficient: quality is the scorer's job."""
    sections = _sections(text)
    lowered = text.lower()
    results = []
    for gate in rubric["gates"]:
        passed, reason = True, "ok"
        heading = gate.get("required_heading")
        if heading:
            bodies = [body for name, body in sections.items() if heading in name]
            if not bodies:
                passed, reason = False, f"no heading containing '{heading}'"
            elif not any(bodies):
                passed, reason = False, f"heading '{heading}' has an empty body"
        for phrase in gate.get("forbidden_phrases") or []:
            if re.search(r"\b" + re.escape(phrase) + r"\b", lowered):
                passed, reason = False, f"references outside context: '{phrase}'"
                break
        results.append({"id": gate["id"], "label": gate["label"], "passed": passed, "reason": reason})
    return results


# ---------------------------------------------------------------- N3/N4 score + gate


def _tenths(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateError(f"score {value!r} is not a number")
    tenths = round(value * 10)
    if abs(value * 10 - tenths) > 1e-6 or not 0 <= tenths <= 100:
        raise GateError(f"score {value!r} must be 0.0-10.0 in steps of 0.1")
    return tenths


def _scorecard_problems(text: str, scorecard: Mapping[str, Any], rubric: Mapping[str, Any]) -> list[str]:
    if not isinstance(scorecard, Mapping) or not isinstance(scorecard.get("scores"), Mapping):
        return ["scorecard must be an object with a 'scores' object"]
    problems = []
    if scorecard.get("rubric_version") != rubric["version"]:
        problems.append(
            f"scorecard rubric_version {scorecard.get('rubric_version')!r} != rubric {rubric['version']!r}; re-score"
        )
    if scorecard.get("content_sha256") != sha256_text(text):
        problems.append("scorecard content_sha256 does not match this prompt; it scored a different text")
    drafter, scorer = scorecard.get("drafter_context_id"), scorecard.get("scorer_context_id")
    if not drafter or not scorer:
        problems.append("drafter_context_id and scorer_context_id are both required")
    elif drafter == scorer:
        problems.append("scorer_context_id equals drafter_context_id; scoring must run in an independent context")
    expected = {d["id"] for d in rubric["dimensions"]}
    given = set((scorecard.get("scores") or {}).keys())
    if expected - given:
        problems.append(f"missing dimensions: {sorted(expected - given)}")
    if given - expected:
        problems.append(f"unknown dimensions: {sorted(given - expected)}")
    return problems


def evaluate(text: str, scorecard: Mapping[str, Any], rubric: Mapping[str, Any]) -> dict:
    promo = rubric["promotion"]
    gates = lint_gates(text, rubric)
    verdict: dict[str, Any] = {
        "rubric_version": rubric["version"],
        "content_sha256": sha256_text(text),
        "gates": gates,
        "reasons": [],
        "notes": [],
    }
    problems = _scorecard_problems(text, scorecard, rubric)
    scored: list[tuple[int, dict]] = []
    if not problems:
        for dim in rubric["dimensions"]:
            entry = scorecard["scores"][dim["id"]]
            if not isinstance(entry, Mapping):
                problems.append(f"{dim['id']}: expected {{score, justification, evidence}}")
                continue
            try:
                tenths = _tenths(entry.get("score"))
            except GateError as exc:
                problems.append(f"{dim['id']}: {exc}")
                continue
            if not str(entry.get("justification") or "").strip():
                problems.append(f"{dim['id']}: justification is required")
                continue
            cap = int(promo["unevidenced_cap_tenths"])
            if tenths > cap and not str(entry.get("evidence") or "").strip():
                verdict["notes"].append(f"{dim['id']}: {tenths / 10:.1f} capped to {cap / 10:.1f}, no evidence named")
                tenths = cap
            scored.append((tenths, dim))
    if problems:
        verdict.update(status=INVALID, reasons=problems)
        return verdict

    weighted = sum(t * int(d["weight_hundredths"]) for t, d in scored)
    low = sorted(scored, key=lambda pair: (pair[0], -int(pair[1]["weight_hundredths"])))
    verdict["weighted"] = weighted / 1000
    verdict["min"] = low[0][0] / 10
    verdict["weakest"] = [{"id": d["id"], "score": t / 10} for t, d in low[:3]]

    failed_gates = [g for g in gates if not g["passed"]]
    floor = int(promo["floor_tenths"])
    if failed_gates:
        verdict["status"] = BLOCK_GATE
        verdict["reasons"] = [f"{g['id']} {g['label']}: {g['reason']}" for g in failed_gates]
        verdict["reasons"].append("gate failures are absolute; the score is not consulted")
    elif low[0][0] < floor:
        verdict["status"] = BLOCK_FLOOR
        below = [f"{d['id']} {t / 10:.1f}" for t, d in low if t < floor]
        verdict["reasons"] = [f"below the {floor / 10:.1f} floor: {', '.join(below)}"]
    elif weighted >= int(promo["bar_thousandths"]):
        verdict["status"] = PASS
        verdict["reasons"] = [f"all gates green, floor clear, weighted {weighted / 1000:.3f}"]
    else:
        verdict["status"] = REVISE
        gap = (int(promo["bar_thousandths"]) - weighted) / 1000
        verdict["reasons"] = [f"short of the bar by {gap:.3f}; revise only: {[w['id'] for w in verdict['weakest']]}"]
    return verdict


# ---------------------------------------------------------------- N5/N6 guard


def next_action(history: Sequence[Mapping[str, Any]], rubric: Mapping[str, Any]) -> dict:
    """Decide the loop's next step from the attempt history of one node.

    history[0] is the initial draft; history[i>0] is revision i. Each entry has
    "status" (an evaluate() status) and "strategy" (free text naming the approach).

    Failed draft -> revise. 2nd failed revision -> diagnose and change strategy.
    A revision after diagnose that reuses an old strategy, or failure of the
    final permitted revision, escalates to the human.
    """
    promo = rubric["promotion"]
    max_revisions = int(promo["max_revisions"])
    change_after = int(promo["strategy_change_after_failed_revisions"])
    if not history:
        return {"action": "draft", "reason": "no attempts yet"}
    last = history[-1]
    if last.get("status") == PASS:
        return {"action": "promote", "reason": "latest attempt passed"}
    if last.get("status") == INVALID:
        return {"action": "rescore", "reason": "scorecard invalid; fix the scorecard, not the prompt"}

    revisions = list(history[1:])
    failed_revisions = sum(1 for r in revisions if r.get("status") != PASS)
    if failed_revisions > change_after:
        prior = {str(r.get("strategy") or "").strip().lower() for r in history[: change_after + 1]}
        latest = str(revisions[-1].get("strategy") or "").strip().lower()
        if not latest or latest in prior:
            return {"action": "escalate", "reason": "post-diagnose revision reused an earlier strategy"}
    if failed_revisions >= max_revisions:
        return {
            "action": "escalate",
            "reason": f"{failed_revisions} failed revisions; cap is {max_revisions}",
            "surface": "last good state, every failure log, the exact missing item",
        }
    if failed_revisions == change_after:
        return {"action": "diagnose", "reason": f"{change_after} failed revisions; next revision must change strategy"}
    return {"action": "revise", "reason": "targeted diff on the weakest dimensions only", "revision": failed_revisions + 1}


# ---------------------------------------------------------------- N7 promote / rollback / N9 stale


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)
    os.replace(tmp, path)


def _check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise GateError(f"invalid slug {slug!r}; use lowercase letters, digits, hyphens")
    return slug


def _load_index(library: Path) -> dict:
    path = library / "index.json"
    return load_json(path) if path.exists() else {"entries": {}}


def promote(text: str, scorecard: Mapping[str, Any], rubric: Mapping[str, Any], library: Path, slug: str) -> dict:
    """The only library writer. Re-evaluates; never trusts a caller's verdict."""
    _check_slug(slug)
    if rubric.get("status") != "signed_off":
        return {"status": "refused", "reason": f"rubric {rubric['version']} is {rubric.get('status')!r}, not signed_off"}
    verdict = evaluate(text, scorecard, rubric)
    if verdict["status"] != PASS:
        return {"status": "refused", "reason": f"verdict {verdict['status']}", "verdict": verdict}

    index = _load_index(library)
    entry = index["entries"].setdefault(slug, {"current": None, "versions": []})
    digest = verdict["content_sha256"]
    current = next((v for v in entry["versions"] if v["version"] == entry["current"]), None)
    if current and current["sha256"] == digest:
        return {"status": "skipped", "reason": "identical content already current", "version": current["version"]}

    version = max((v["version"] for v in entry["versions"]), default=0) + 1
    _atomic_write(library / "entries" / slug / f"v{version}.md", text)
    _atomic_write(
        library / "evidence" / slug / f"v{version}.scorecard.json",
        json.dumps({"scorecard": scorecard, "verdict": verdict}, indent=2, sort_keys=True) + "\n",
    )
    entry["versions"].append(
        {
            "version": version,
            "parent": entry["current"],
            "sha256": digest,
            "rubric_version": rubric["version"],
            "weighted": verdict["weighted"],
        }
    )
    entry["current"] = version
    _atomic_write(library / "index.json", json.dumps(index, indent=2, sort_keys=True) + "\n")
    return {"status": "promoted", "slug": slug, "version": version, "sha256": digest}


def rollback(library: Path, slug: str) -> dict:
    """Repoint current to its parent. Files are never deleted."""
    _check_slug(slug)
    index = _load_index(library)
    entry = index["entries"].get(slug)
    if not entry or entry["current"] is None:
        raise GateError(f"no current version for {slug!r}")
    current = next(v for v in entry["versions"] if v["version"] == entry["current"])
    entry["current"] = current["parent"]
    _atomic_write(library / "index.json", json.dumps(index, indent=2, sort_keys=True) + "\n")
    return {"status": "rolled_back", "slug": slug, "from": current["version"], "to": current["parent"]}


def stale(library: Path, rubric: Mapping[str, Any]) -> dict:
    """N9 regression: current entries scored under another rubric version must be re-scored."""
    out = []
    for slug, entry in sorted(_load_index(library)["entries"].items()):
        current = next((v for v in entry["versions"] if v["version"] == entry["current"]), None)
        if current and current["rubric_version"] != rubric["version"]:
            out.append({"slug": slug, "version": current["version"], "scored_under": current["rubric_version"]})
    return {"rubric_version": rubric["version"], "stale": out}


# ---------------------------------------------------------------- CLI


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Graph-loop prompt library gate")
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-rubric")
    p = sub.add_parser("lint")
    p.add_argument("--prompt", type=Path, required=True)
    p = sub.add_parser("hash")
    p.add_argument("--prompt", type=Path, required=True)
    p = sub.add_parser("evaluate")
    p.add_argument("--prompt", type=Path, required=True)
    p.add_argument("--scorecard", type=Path, required=True)
    p = sub.add_parser("guard")
    p.add_argument("--history", type=Path, required=True)
    p = sub.add_parser("promote")
    p.add_argument("--prompt", type=Path, required=True)
    p.add_argument("--scorecard", type=Path, required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    p = sub.add_parser("rollback")
    p.add_argument("--slug", required=True)
    p.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    p = sub.add_parser("stale")
    p.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_cli().parse_args(argv)
    try:
        rubric = load_rubric(args.rubric)
        if args.command == "check-rubric":
            result, ok = {"status": "valid", "version": rubric["version"], "signoff": rubric.get("status")}, True
        elif args.command == "hash":
            result, ok = {"content_sha256": sha256_text(args.prompt.read_text(encoding="utf-8"))}, True
        elif args.command == "lint":
            gates = lint_gates(args.prompt.read_text(encoding="utf-8"), rubric)
            result, ok = {"gates": gates}, all(g["passed"] for g in gates)
        elif args.command == "evaluate":
            result = evaluate(args.prompt.read_text(encoding="utf-8"), load_json(args.scorecard), rubric)
            ok = result["status"] == PASS
        elif args.command == "guard":
            result = next_action(load_json(args.history), rubric)
            ok = result["action"] != "escalate"
        elif args.command == "promote":
            text = args.prompt.read_text(encoding="utf-8")
            result = promote(text, load_json(args.scorecard), rubric, args.library, args.slug)
            ok = result["status"] in {"promoted", "skipped"}
        elif args.command == "rollback":
            result, ok = rollback(args.library, args.slug), True
        else:
            result = stale(args.library, rubric)
            ok = not result["stale"]
    except (GateError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
