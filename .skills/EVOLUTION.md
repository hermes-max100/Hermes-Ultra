# Skill Evolution Policy

Skills may evolve only through this process:

1. Observe
- Log the task, selected skill, result, and success/failure note.

2. Diagnose
- Identify whether the weakness is missing triggers, weak instruction, missing output format, bad project context, bad routing, missing test coverage, or a model failure unrelated to the skill.

3. Propose
- Draft a small change to `meta.env`, `SKILL.md`, or `tests.md`.

4. Test
- Run known test prompts and ensure the new version improves the target behavior without breaking old behavior.

5. Promote
- Increment `VERSION`, update `changelog.md`, and keep a backup.

Forbidden:
- Silent self-modification.
- Untested skill mutation.
- Overwriting skill files without a changelog entry.
- Deleting prior constraints without a reason.
