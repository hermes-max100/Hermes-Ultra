#!/usr/bin/env python3
"""Two-stage Hermes skill routing: TF-IDF retrieval plus local listwise reranking."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

STOPWORDS = frozenset(
    """
    a an the and or but in on at to for of with by from is are was were be been being
    this that these those it its as if then than which who whom whose what when where
    how why will would can could should may might must shall do does did doing have
    has had having i you he she we they me him her us them my your his our their
    not no nor so too very just only also more most some any all each both few many
    much such own same other into out up down over under again further once here there
    about above below off through during before after between
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._-]*", text.lower())
        if len(token) >= 3 and token not in STOPWORDS
    ]


def load_meta(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def enabled_skills(skills_home: Path) -> list[str]:
    skills_file = skills_home / "skills.txt"
    if not skills_file.is_file():
        return []
    return [line.strip() for line in skills_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def skill_text(skills_home: Path, skill: str) -> str:
    skill_dir = skills_home / "skills.d" / skill
    meta = load_meta(skill_dir / "meta.env")
    parts = [skill]
    for key in ("NAME", "DESCRIPTION", "TAGS", "TRIGGERS", "INPUTS", "OUTPUTS", "RISK_LEVEL"):
        if meta.get(key):
            parts.append(meta[key])
    for name in ("SKILL.md", "tests.md"):
        path = skill_dir / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return " ".join(parts)


def corpus(skills_home: Path) -> dict[str, list[str]]:
    return {
        skill: tokenize(skill_text(skills_home, skill))
        for skill in enabled_skills(skills_home)
        if (skills_home / "skills.d" / skill).is_dir()
    }


def idf_for(corpus_tokens: dict[str, list[str]]) -> dict[str, float]:
    count = max(len(corpus_tokens), 1)
    df: defaultdict[str, int] = defaultdict(int)
    for tokens in corpus_tokens.values():
        for token in set(tokens):
            df[token] += 1
    return {term: math.log((count + 1) / (freq + 1)) + 1 for term, freq in df.items()}


def vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    total = sum(counts.values())
    if not total:
        return {}
    return {term: (value / total) * idf.get(term, 0.0) for term, value in counts.items()}


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[term] * right[term] for term in left.keys() & right.keys())
    left_mag = math.sqrt(sum(value * value for value in left.values()))
    right_mag = math.sqrt(sum(value * value for value in right.values()))
    if not left_mag or not right_mag:
        return 0.0
    return dot / (left_mag * right_mag)


def project_context(skills_home: Path, project: str | None) -> tuple[str, set[str]]:
    if not project:
        return "", set()
    project_dir = skills_home / "projects" / project
    profile = project_dir / "profile.md"
    active = project_dir / "active-skills.txt"
    text = profile.read_text(encoding="utf-8", errors="replace") if profile.is_file() else ""
    active_skills = set(active.read_text(encoding="utf-8").splitlines()) if active.is_file() else set()
    return text, {skill.strip() for skill in active_skills if skill.strip()}


def field_tokens(skills_home: Path, skill: str, field: str) -> set[str]:
    meta = load_meta(skills_home / "skills.d" / skill / "meta.env")
    return set(tokenize(meta.get(field, "")))


def rank(skills_home: Path, query: str, project: str | None, limit: int, retrieve_limit: int) -> list[dict[str, object]]:
    corpus_tokens = corpus(skills_home)
    if not corpus_tokens:
        return []

    project_text, active_skills = project_context(skills_home, project)
    query_tokens = tokenize(f"{query} {project_text}")
    query_set = set(query_tokens)
    idf = idf_for(corpus_tokens)
    query_vec = vector(query_tokens, idf)

    first_stage = []
    for skill, tokens in corpus_tokens.items():
        pointwise = cosine(query_vec, vector(tokens, idf))
        if skill in active_skills:
            pointwise += 0.15
        if pointwise > 0:
            first_stage.append((skill, pointwise))
    first_stage.sort(key=lambda item: item[1], reverse=True)
    candidates = first_stage[: max(retrieve_limit, limit)]

    results = []
    candidate_count = max(len(candidates), 1)
    for position, (skill, pointwise) in enumerate(candidates, start=1):
        trigger_overlap = len(query_set & field_tokens(skills_home, skill, "TRIGGERS"))
        output_overlap = len(query_set & field_tokens(skills_home, skill, "OUTPUTS"))
        tag_overlap = len(query_set & field_tokens(skills_home, skill, "TAGS"))
        active_bonus = 0.18 if skill in active_skills else 0.0
        rank_bonus = (candidate_count - position + 1) / candidate_count * 0.05
        listwise_score = (
            pointwise
            + trigger_overlap * 0.08
            + output_overlap * 0.06
            + tag_overlap * 0.025
            + active_bonus
            + rank_bonus
        )
        results.append(
            {
                "skill": skill,
                "score": round(listwise_score, 4),
                "pointwise": round(pointwise, 4),
                "trigger_overlap": trigger_overlap,
                "output_overlap": output_overlap,
                "tag_overlap": tag_overlap,
                "active_project_skill": skill in active_skills,
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def print_table(results: list[dict[str, object]], explain: bool) -> None:
    if not results:
        print("No matching skills found.")
        raise SystemExit(1)
    if explain:
        print(f"{'SKILL':36} {'LISTWISE':>10} {'POINTWISE':>10} {'TRIG':>5} {'OUT':>5} {'TAGS':>5} {'PROJECT':>7}")
        print(f"{'-' * 36} {'-' * 10:>10} {'-' * 10:>10} {'-' * 5:>5} {'-' * 5:>5} {'-' * 5:>5} {'-' * 7:>7}")
        for result in results:
            print(
                f"{str(result['skill'])[:36]:36} "
                f"{float(result['score']):10.4f} "
                f"{float(result['pointwise']):10.4f} "
                f"{int(result['trigger_overlap']):5d} "
                f"{int(result['output_overlap']):5d} "
                f"{int(result['tag_overlap']):5d} "
                f"{str(bool(result['active_project_skill'])).lower():>7}"
            )
    else:
        for result in results:
            print(f"{result['skill']} score={result['score']} pointwise={result['pointwise']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Listwise Hermes skill reranker.")
    parser.add_argument("--skills-home", default=".skills")
    parser.add_argument("--query", required=True)
    parser.add_argument("--project")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--retrieve-limit", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()

    results = rank(Path(args.skills_home), args.query, args.project, args.limit, args.retrieve_limit)
    if args.json:
        print(json.dumps({"query": args.query, "project": args.project, "results": results}, indent=2))
    else:
        print_table(results, args.explain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
