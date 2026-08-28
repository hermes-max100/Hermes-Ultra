# Hermes Profiles

These files define local Hermes profile artifacts while keeping provider and execution access governed.

## Profiles

Existing profiles include:

- `legal`: legal council with strict aggregation, citation grounding, privilege boundaries, and review requirements.
- `trading`: options/trading council focused on education, scenario analysis, and risk discipline.
- `security_research`: authorized defensive security research profile with scope checks and defensive aggregation.
- `cyberkimi_quarantine`: report-only quarantined security profile.
- `direct`: direct-but-bounded profile for concise answers and local governed execution.

Governed Bot Mode adds real profile-backed specialists:

- `research`: public-source research through the hardened Agent Reach wrapper.
- `coding`: repository/code engineering through governed patch/test/static-analysis boundaries.
- `revenue`: Revenue OS analysis, drafts, handoffs, and ledger artifacts; no autonomous externalization.
- `creator`: AI-disclosed virtual-creator research/planning/compliance/analytics; no autonomous posting or messaging.
- `legal` is reused directly as the Legal Bot rather than duplicated.

## Governed Bot Mode

`config/bot-mode-policy.json` is the Bot roster contract. A Bot is a Hermes profile overlay, not a new agent primitive or authority.

The policy deliberately requires:

- capability-brokered credentials and no standing shared Bot credential pool
- no Bot externalization authority
- inheritance of the existing profile/router layer rather than a second router
- untrusted, digest-bound, evidence-linked inter-Bot messages
- proposal-only bounded Council output
- Trust Gate / Containment Gateway / proof-before-success remaining above Bot collaboration

Use `src/system/bot-mode-governance.py` for message and Council artifact contracts. Bots must never use inter-Bot messages as proof of authorization.

## Provider Access

Use official APIs, approved connectors, local runtimes, or manual handoff. Do not use subscription cookies, session tokens, saved browser profiles, CAPTCHA bypasses, or web-UI scraping as autonomous backend access.

## Manifest

`profiles/profile_manifest.json` lists each profile, council roles, research agent, aggregator, memory pattern, and review boundary.

Direct Mode policy lives in `config/hermes-direct-mode-policy.json`.
