# SkillOpt Integration Notes

Reference: [SkillOpt: Executive Strategy for Self-Evolving Agent Skills](https://arxiv.org/html/2605.23904v2).

The paper is directly relevant to Hermes because it treats a skill document as
the trainable external state of a frozen agent. The main design point is that
skill evolution should behave like a controlled optimization loop, not like
free-form self-rewriting.

## What Hermes Already Has

- Proposal-based evolution through `src/system/skill-evolver.sh`.
- Backups and changelog entries on promotion.
- Drift tracking with `src/system/skill-router-v3.sh snapshot` and
  `src/system/skill-router-v3.sh dashboard`.
- Dynamic routing and listwise reranking before skill use.

## What SkillOpt Adds As Policy

The SkillOpt paper argues for:

- rollout evidence from task executions
- separate success/failure reflection
- bounded add/delete/replace edits
- textual learning-rate budget
- strict validation gate
- rejected-edit buffer
- epoch-wise slow/meta update
- compact `best_skill.md` export

Hermes captures those constraints in:

```text
config/skillopt-policy.json
```

## Hermes Operating Rule

Skill evolution must remain:

```text
Observe -> Propose -> Validate -> Promote -> Export
```

It must not become:

```text
Observe -> Rewrite
```

## Required Boundaries

Installer:
- prepares dependencies, logs, state, and file layout
- does not choose skills or models
- does not evolve skills

Router:
- chooses skills and models at runtime
- does not mutate skills

Daily refresh:
- runs tests, snapshots, dashboards, and sweeps
- reports weak signals
- does not silently promote edits

Evolver:
- proposes bounded edits
- validates before promotion
- records rejected edits
- exports compact best-skill artifacts

## Implementation Backlog

The current Hermes evolver is proposal-based but not yet a full SkillOpt loop.
The next hardening steps are:

1. Add structured patch proposals with `append`, `insert`, `replace`, and
   `delete` operations instead of trigger-only updates.
2. Add a validation score file per skill:

   ```text
   .skills/skills.d/<skill>/validation.jsonl
   ```

3. Reject proposals unless validation score strictly improves.
4. Record rejected proposals to:

   ```text
   .skills/rejected-edits.jsonl
   ```

5. Export accepted best artifacts to:

   ```text
   .skills/skills.d/<skill>/best_skill.md
   ```

6. Add a protected slow/meta update region to each optimized skill.

This keeps Hermes aligned with SkillOpt without coupling the installer, router,
runner, and evolver into one hard-to-debug subsystem.
