---
name: hermes-opportunity-engine
description: Normalize, validate, rank, and queue Revenue OS opportunities from source-linked findings.
---

# Hermes Opportunity Engine

Use this skill to convert public/source findings into ranked local Revenue OS
opportunity records.

## Driver

```bash
src/system/opportunity-engine.sh init
src/system/opportunity-engine.sh normalize --source-file findings.jsonl [--write-ledger]
src/system/opportunity-engine.sh rank
src/system/opportunity-engine.sh report
```

## Boundary

Local queue/report artifacts only. No sending, posting, purchases, account
changes, credential entry, permission changes, deletion, or irreversible actions.
