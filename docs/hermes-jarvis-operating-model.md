# Hermes Agent Self-Evolving JARVIS Operating Model

Hermes Agent is the runtime agent. JARVIS is the self-evolving system we built
around it. JARVIS is the system that should decide whether external skills,
model-routing changes, browser harnesses, MCP servers, or agent packs become
part of Hermes runtime.

## Core Rule

External skills are not the agent. Hermes Agent running self-evolving JARVIS is
the agent system and evolution authority.

Downloaded skills and repositories may inform JARVIS, but they do not get
to rewrite runtime behavior, install services, start background processes, or
change model/tool policy by themselves.

## Registry Split

| Registry | Role |
|---|---|
| `.skill-sources/` | Pinned source downloads and review receipts |
| `.agents/skills/` | Project/Codex-visible skills and reference workflows |
| `.skills/skills.d/` | Hermes runtime skills selected by the local router |

The current external skills are activated in `.agents/skills`. They are not
Hermes runtime skills until JARVIS promotes them through the adapter path.

## JARVIS Promotion Path

1. Observe a repeated task, failure, or opportunity.
2. Compare local skills, external skills, logs, tests, and project needs.
3. Draft a bounded proposal.
4. Validate against tests, promptfoo checks, approval-boundary checks, and
   regression prompts.
5. Promote only if the result improves and does not violate policy.
6. Record changelog, validation evidence, and rejected edits.

## External Packages Currently Runtime-Gated

- SkillClaw evolution server, session capture, cloud sync, and self-writing.
- Composio shell-pipe bootstrap.
- Mission Control daemon/database maintenance.
- Oh My Hermes autopilot/Ralph execution.
- Browser Harness live browser-profile attachment and helper self-editing.
- Agent Reach cookie/session-adjacent backends.
- Defuddle package install and CLI execution.
- Codebase Memory MCP install, indexing, daemon, and MCP config writes.
- Full OpenMontage application runtime and provider setup.

These can be used after a specific JARVIS activation plan, but skill
activation alone does not authorize runtime execution.

## Practical Behavior

When asked to improve Hermes, JARVIS should:

- prefer first-party policies and existing router scripts
- use external skills as comparison material
- generate small controlled patches
- run local validation before promotion
- keep all mutating phone, app, browser, MCP, and account actions
  approval-gated

When asked to do something risky, JARVIS should state the concern and
offer the approval-gated version that still moves the build forward.
