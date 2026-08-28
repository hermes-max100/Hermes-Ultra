# bash-script-hardener

Use this skill to harden bash scripts by finding quoting errors, missing safety options, injection vectors, and race conditions.

## Rules

- Prefer `set -euo pipefail` for executable scripts.
- Quote variable expansions.
- Check for command injection via unvalidated input.
- Flag use of `eval`, temporary file races, and fragile path handling.
- Provide a hardened version or patch alongside the report.

## Outputs

- security report
- hardened script
- diff patch
- best practice checklist
