# Legal Workflows

Standard operating procedures for common legal tasks using the HERMES agent.

## Available Workflows

| Workflow | Description | Agent Command |
|----------|-------------|---------------|
| Contract Review | Review a contract for risks and issues | `simplellms --hermes review` |
| Compliance Audit | Audit against regulatory requirements | `simplellms --hermes compliance` |
| Document Drafting | Generate legal documents from briefs | `simplellms --hermes draft` |
| Risk Assessment | Evaluate legal exposure | `simplellms --hermes risk` |
| Version Comparison | Redline two document versions | `simplellms --hermes compare` |
| Document Summary | Summarize complex documents | `simplellms --hermes summarize` |

## How to Run

Each workflow has a SOP file in this directory. These SOPs can be fed to M.A.R.G.E. as an epic:

```bash
simplellms --marge parse ./workflows/contract-review.md
simplellms --marge execute
```
