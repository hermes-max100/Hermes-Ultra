---
name: web-design-guidelines
description: >
  Audit changed web UI against the current official Vercel Web Interface Guidelines.
  Fetches the current rule source at review time, reports concrete findings, and feeds
  unresolved applicable findings back into the design-engineer repair loop.
triggers:
  - review my UI
  - check accessibility
  - audit design
  - review UX
  - web design guidelines
  - Vercel interface guidelines
---

# Web Design Guidelines

Hermes wrapper for the official Vercel Web Interface Guidelines.

## Authority

Official rule source:

`https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md`

Project:

`https://github.com/vercel-labs/web-interface-guidelines`

Always fetch the current official rule source when network access is available. Do not treat this wrapper as a frozen copy of Vercel's rules.

## Review procedure

1. Identify the exact UI files/components/routes changed.
2. Fetch the current official rule source.
3. Apply all relevant rules to the changed interface and its rendered behavior.
4. Where a rule depends on runtime behavior, verify it in a real browser instead of guessing from source.
5. Report concrete findings using `path:line` when source location is known; otherwise use `route > component/state`.
6. Classify each finding as `FAIL`, `PASS`, or `NOT_APPLICABLE` with a short reason.
7. Send `FAIL` items back to `design-engineer` for repair and re-audit after the repair.

## Required runtime checks

When applicable, verify at least:

- keyboard operation;
- visible/unobscured focus;
- semantic labels and control names;
- usable hit/touch targets;
- responsive overflow/clipping;
- loading, empty, validation, error, and recovery states;
- motion/reduced-motion behavior;
- clear interaction labels and feedback;
- text/layout quality at target viewports.

## Evidence format

```text
WEB_INTERFACE_GUIDELINES_AUDIT
source: <official URL>
source_revision_or_retrieval_time: <value when available>
targets: <paths/routes>

FAIL
- path:line — rule — evidence — repair

PASS
- rule/category — evidence

NOT_APPLICABLE
- rule/category — reason

RESULT: PASS | FAIL
```

Do not return `PASS` while an applicable `FAIL` remains unresolved.
