---
name: hermes-trust-gate
description: Static trust gate for external skills, MCP servers, packages, model artifacts, and capability bundles before Hermes/JARVIS promotion.
---

# Hermes Trust Gate

Use before importing, installing, activating, or promoting external skills, MCP
servers, packages, model artifacts, or capability bundles.

Driver:

```bash
src/system/trust-gate.sh scan PATH_OR_GIT_URL --type skill
src/system/trust-gate.sh scan PATH_OR_GIT_URL --type mcp
src/system/trust-gate.sh scan PATH_OR_GIT_URL --type package
src/system/trust-gate.sh scan PATH_OR_GIT_URL --type model
src/system/trust-gate.sh scan PATH_OR_GIT_URL --type capability
```

The gate is read-only and writes signed local reports under
`.hermes/reports/trust-gate`. It never executes candidate code.

Scout discovers; Trust Gate evaluates; governance promotes.
