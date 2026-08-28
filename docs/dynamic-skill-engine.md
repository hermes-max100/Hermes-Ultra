# Hermes Dynamic Skill Engine

Hermes now has a local dynamic skill layer:

- `.skills/skills.txt` is the enabled skill registry.
- `.skills/skills.d/<skill>/meta.env` makes each skill discoverable.
- `.skills/skills.d/<skill>/SKILL.md` contains the operating instructions.
- `.skills/projects/<project>/profile.md` adds project-specific routing context.
- `.skills/logs/skill-events.jsonl` records what worked and what failed.
- `src/system/skill-router.sh` selects skills per query.
- `src/system/skill-router-v3.sh` adds TF-IDF retrieval plus local listwise reranking.
- `src/system/skill-evolver.sh` creates reviewable evolution proposals.

The design rule is:

```text
Observe -> Propose -> Test -> Promote
```

Skills do not silently rewrite themselves.

Hermes Agent runs the self-evolving JARVIS system, which controls the evolution
loop. External skills in `.agents/skills` are project-visible inputs and
references unless JARVIS promotes them into `.skills/skills.d` through
validation. See:

```text
docs/hermes-jarvis-operating-model.md
config/hermes-jarvis-policy.json
```

External skill repositories are tracked in:

```text
config/external-skill-sources.json
```

These sources are discovery inputs for sweep/evolution work, not automatic
installs. Repositories such as `Neeeophytee/finding-unknowns-skills` are marked
`review_before_install` so Hermes can surface them during daily refresh without
silently importing new instructions into the live skill set.

The SkillOpt paper formalizes the same boundary with a stronger optimization
loop: bounded add/delete/replace edits, a textual learning-rate budget, strict
held-out validation, rejected-edit memory, and compact `best_skill.md` export.
Hermes stores that policy in `config/skillopt-policy.json`; see
`docs/skillopt-integration.md`.

## Daily Use

Find skills for a task:

```bash
src/system/skill-router.sh find "red team this appeal filing and build evidence matrix from PDFs"
src/system/skill-router-v3.sh find "red team this appeal filing and build evidence matrix from PDFs"
```

Use a project overlay:

```bash
src/system/skill-router.sh project amazon-appeal "find contradictions in the investigation timeline"
src/system/skill-router-v3.sh project amazon-appeal "find contradictions in the investigation timeline"
```

Generate an LLM context bundle:

```bash
src/system/skill-router.sh bundle amazon-appeal --limit 3 "find contradictions in the investigation timeline" > skill-context.md
```

Log performance:

```bash
src/system/skill-router.sh log amazon-appeal legal-evidence-os failure "Missed service deadline and record designation trigger terms."
```

Create a proposal:

```bash
src/system/skill-evolver.sh propose amazon-appeal
src/system/skill-evolver.sh list-proposals
src/system/skill-evolver.sh show-proposal <proposal-id>
src/system/skill-evolver.sh promote <proposal-id>
```

Dashboard:

```bash
src/system/skill-router-v3.sh snapshot
src/system/skill-router-v3.sh dashboard
src/system/skill-router-v3.sh dashboard --since 2026-07-01 --csv .skills/reports/dashboard.csv
```

The dashboard tracks:

- routing accuracy by project and day
- per-skill success/failure/partial/blocked counts
- evolution pressure from repeated weak outcomes
- rubric drift from `.skills/logs/score-snapshots.jsonl`

Drift is flagged when a skill's rubric score moves by at least 5 points or its
observed volatility reaches at least 10 points.

## Why Listwise Reranking Helps

Pointwise scoring asks: "How relevant is this one skill to the query?" That is
fast, but it becomes poorly calibrated when the top candidates are all
topically plausible.

Listwise reranking asks: "Given these plausible candidates together, which one
is the best fit relative to the rest?" Hermes v3 does this after TF-IDF
retrieval by comparing trigger overlap, output overlap, tag overlap, project
activation, and the first-stage score across the candidate set.

The practical effect is better discrimination between similar skills. For
example, an appeal query may match `legal-evidence-os`,
`appellate-filing-red-team`, and `citation-integrity-checker`; listwise
reranking can put the procedural filing skill above the general legal evidence
skill when the query says `deadline`, `service`, `record designation`, or
`formatting`.

## Dispatch Integration

`src/system/hermes-dispatch.sh` calls the skill router before model routing. Manual model and thinking choices remain explicit user controls:

```bash
src/system/hermes-dispatch.sh \
  --project amazon-appeal \
  --thinking high \
  --model-key nvidia-nim \
  --model-id meta/llama-3.3-70b-instruct \
  "red team this appeal filing"
```

The JSON output includes:

- `skills`
- `skill_source`
- `thinking_level`
- `model`
- `provider_model_id`

The report footnote includes the same attribution fields.
