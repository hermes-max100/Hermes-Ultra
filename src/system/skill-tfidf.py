#!/usr/bin/env python3
"""TF-IDF cosine scorer for Hermes skills."""

from __future__ import annotations

import argparse
import json
import math
import os
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
    tokens = re.findall(r"[a-z0-9][a-z0-9._-]*", text.lower())
    return [token for token in tokens if len(token) >= 3 and token not in STOPWORDS]


def load_meta(meta_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not meta_path.is_file():
        return values
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_enabled_skills(skills_home: Path) -> list[str]:
    skills_file = skills_home / "skills.txt"
    if not skills_file.is_file():
        return []
    skills = []
    for line in skills_file.read_text(encoding="utf-8").splitlines():
        skill = line.strip()
        if skill:
            skills.append(skill)
    return skills


def load_skill_text(skills_home: Path, skill: str) -> str:
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


def build_corpus(skills_home: Path) -> dict[str, list[str]]:
    corpus: dict[str, list[str]] = {}
    for skill in load_enabled_skills(skills_home):
        if (skills_home / "skills.d" / skill).is_dir():
            corpus[skill] = tokenize(load_skill_text(skills_home, skill))
    return corpus


def compute_idf(corpus: dict[str, list[str]]) -> dict[str, float]:
    document_count = max(len(corpus), 1)
    frequencies: defaultdict[str, int] = defaultdict(int)
    for tokens in corpus.values():
        for term in set(tokens):
            frequencies[term] += 1
    return {
        term: math.log((document_count + 1) / (frequency + 1)) + 1
        for term, frequency in frequencies.items()
    }


def vectorize(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    total = sum(counts.values())
    if total == 0:
        return {}
    return {term: (count / total) * idf.get(term, 0.0) for term, count in counts.items()}


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[term] * right[term] for term in left.keys() & right.keys())
    left_mag = math.sqrt(sum(value * value for value in left.values()))
    right_mag = math.sqrt(sum(value * value for value in right.values()))
    if not left_mag or not right_mag:
        return 0.0
    return dot / (left_mag * right_mag)


def rank(skills_home: Path, query: str, project: str | None, limit: int) -> list[dict[str, object]]:
    corpus = build_corpus(skills_home)
    if not corpus:
        return []
    idf = compute_idf(corpus)
    query_text = query
    active_skills: set[str] = set()
    if project:
        profile = skills_home / "projects" / project / "profile.md"
        if profile.is_file():
            query_text += " " + profile.read_text(encoding="utf-8", errors="replace")
        active = skills_home / "projects" / project / "active-skills.txt"
        if active.is_file():
            active_skills = {line.strip() for line in active.read_text(encoding="utf-8").splitlines() if line.strip()}

    query_vector = vectorize(tokenize(query_text), idf)
    results = []
    for skill, tokens in corpus.items():
        score = cosine(query_vector, vectorize(tokens, idf))
        if skill in active_skills:
            score += 0.15
        if score > 0:
            results.append({"skill": skill, "score": round(score, 4)})
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank Hermes skills with TF-IDF cosine similarity.")
    parser.add_argument("--skills-home", default=".skills")
    parser.add_argument("--query", required=True)
    parser.add_argument("--project")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = rank(Path(args.skills_home), args.query, args.project, args.limit)
    if args.json:
        print(json.dumps({"query": args.query, "project": args.project, "results": results}, indent=2))
    else:
        if not results:
            print("No matching skills found.")
            return 1
        for result in results:
            print(f"{result['skill']} score={result['score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
