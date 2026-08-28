---
name: premortem
description: Run a premortem on a plan, launch, product, hire, strategy, partnership, pricing change, or high-cost decision. Mandatory triggers include "premortem this", "premortem my", "run a premortem", "what could kill this", "future-proof this", "stress test this plan", "what am I missing here", and "find the blind spots". Strong triggers include "what could go wrong", "am I missing anything", "poke holes in this", "where will this break", and "devil's advocate this" when a concrete plan or commitment is present.
---

# Premortem

Run this skill when the user wants to stress-test a concrete plan before acting.
A premortem assumes the plan has already failed six months from now and works
backward to identify why.

Do not use this skill for simple factual questions, generic feedback requests,
or vague ideas with no concrete plan. If the user wants multiple current
perspectives rather than future-failure analysis, suggest an LLM council instead.

## Minimum Context

Before running the premortem, collect enough context to answer:

1. What is the plan, launch, decision, or strategy?
2. Who is it for, or who does it affect?
3. What does success look like?

First scan available context:

- current conversation
- files the user referenced or attached
- relevant workspace docs such as `CLAUDE.md`, `AGENTS.md`, `memory/`, project
  briefs, launch plans, or business docs

If one of the three context elements is missing, ask only the most important
missing question. Do not ask a long intake form.

## Workflow

### 1. Set the Frame

State the premise explicitly:

```text
It is six months from now. This plan has failed. We are looking back to
understand what went wrong.
```

### 2. Generate Raw Failure Reasons

List every genuine reason the plan could have died. Each reason should be:

- specific to the actual plan
- grounded in provided context
- a real threat, not padding
- concise, usually one or two sentences

Do not force a fixed number of reasons. Use however many are real.

### 3. Deep-Dive Each Failure

For each failure reason, analyze it independently. When subagents are available
and appropriate, run one independent deep-dive per failure reason in parallel.
When subagents are not available, perform the same independent analysis yourself.

Each deep-dive must include:

1. `THE FAILURE STORY` - a specific two- to three-paragraph account of how the
   failure happened.
2. `THE UNDERLYING ASSUMPTION` - the one assumption that made the failure
   possible.
3. `EARLY WARNING SIGNS` - one or two observable signals that the failure is
   starting.

Keep each deep-dive under 300 words.

### 4. Synthesize

Produce a `PREMORTEM REPORT` with:

1. `The Most Likely Failure` - the most probable failure and why.
2. `The Most Dangerous Failure` - the most damaging failure, even if less likely.
3. `The Hidden Assumption` - the biggest unquestioned assumption across the
   analysis.
4. `The Revised Plan` - concrete changes mapped to the failure modes.
5. `The Pre-Launch Checklist` - three to five specific checks to run before
   execution.

The revised plan must be concrete. Prefer "run a $47 pilot with 20 people before
launching the $297 workshop" over "consider testing pricing."

### 5. Write Artifacts

Create both files in the current workspace or the most relevant project folder:

```text
premortem-report-YYYYMMDDTHHMMSSZ.html
premortem-transcript-YYYYMMDDTHHMMSSZ.md
```

The HTML report must be self-contained with inline CSS and should include:

- dark background
- synthesis prominently at the top
- one visual card per failure reason
- severity or likelihood indicators
- a grid/card summary of all deep-dives
- timestamp and subject in the footer

The transcript must include:

- gathered context
- raw failure reasons
- all deep-dives
- final synthesis

Open or point the user to the HTML report after generating it.

## Chat Summary

After writing the artifacts, reply in at most three sentences:

- most likely failure
- hidden assumption
- single most important revision

The report contains the full details.

## Quality Rules

- Be direct; do not sugarcoat.
- Be comprehensive but do not pad.
- Ground every failure in the actual plan.
- Watch for economic, operational, distribution, positioning, trust, compliance,
  audience, and execution failures where relevant.
- Respect the minimum context threshold; bad context produces useless
  premortems.
