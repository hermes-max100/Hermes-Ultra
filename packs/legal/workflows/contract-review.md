# Workflow: Contract Review

> **SOP**: Standard contract review process using HERMES.

## Overview

Review incoming contracts for legal risks, compliance gaps, and negotiation points.

## Steps

### Step 1 — Classify Document
- Determine document type (NDA, MSA, SOW, License, etc.)
- Identify parties, jurisdiction, and effective date
- Check if it's a template or bespoke agreement

### Step 2 — Run HERMES Review
```bash
simplellms --hermes review "$(cat ./contract.md)"
```

### Step 3 — Review Output
- Check risk assessment and red flags
- Note items requiring human review
- Extract key terms for negotiation

### Step 4 — Negotiation Prep
- Identify must-have changes
- Identify nice-to-have changes
- Identify fallback positions

### Step 5 — Document Changes
- Save review to `./reviews/` with date stamp
- If redlines needed, compare versions with:
```bash
simplellms --hermes compare ./contract-v1.md ./contract-v2.md
```

## Output
- Review report saved to `./reviews/YYYY-MM-DD-contract-review.md`
- Negotiation brief
- Recommended actions (sign / negotiate / reject)
