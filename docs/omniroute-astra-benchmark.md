# OmniRoute: bounded Direct Astra vs Bedrock Astra benchmark

This benchmark compares the same GPT-6 Astra repository-scale workload through two access routes without changing Hermes production routing:

- `direct-astra`: OpenAI API, model `gpt-6-astra`
- `bedrock-astra-us`: Amazon Bedrock Runtime US geographic cross-Region inference, model `us.openai.gpt-6-astra`

Both routes are explicitly `benchmark_only=true` and `primary_eligible=false`. A benchmark result may nominate Bedrock as a candidate, but it never changes the primary route automatically; human approval remains required.

## Why the Bedrock route is bounded

The benchmark planner does not call either provider, write model-selection state, or expose credentials. It only emits an immutable comparison manifest keyed to the repository base SHA and task text. Actual executor runs must use isolated worktrees at the same base commit and report observations against the same task fingerprint.

The comparison measures:

- completion quality;
- context retention;
- browser reliability;
- tool reliability;
- wall-clock latency;
- auditability and audit-evidence completeness;
- effective token/tool cost;
- test pass rate and regressions.

At least three runs per route are required by default. Bedrock is blocked as a candidate if quality, context, browser/tool reliability, tests, regressions, latency, effective cost, or audit evidence breach the configured guardrails.

## Current route facts

The benchmark values below were verified against official provider documentation on 2026-09-18.

| Route | Endpoint/model | Short context <=272K | Long context >272K |
| --- | --- | --- | --- |
| Direct OpenAI | `https://api.openai.com/v1` / `gpt-6-astra` | input $10.00, cache write $12.50, cache read $1.00, output $50.00 | input $20.00, cache write $25.00, cache read $2.00, output $75.00 |
| Bedrock US Geo CRIS | `https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1` / `us.openai.gpt-6-astra` | input $11.00, cache write $13.75, cache read $1.10, output $55.00 | input $22.00, cache write $27.50, cache read $2.20, output $82.50 |

All prices are USD per 1 million tokens for standard processing. The observation field `input_tokens` means billable uncached input tokens; do not also count cached tokens inside that field.

Official references:

- OpenAI model/pricing: https://developers.openai.com/api/docs/models/gpt-6-astra
- AWS model card: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html

## Generate the frozen benchmark manifest

```bash
src/system/omniroute.sh benchmark-astra plan \
  --repo-path "$PWD" \
  --base-sha "$(git rev-parse HEAD)" \
  --task 'THE EXACT REPOSITORY-SCALE TASK'
```

Save the output as evidence before either route executes. Both route runs must use its `task_fingerprint` unchanged.

## Observation format

Collect one row per independent run. Do not put API keys, bearer tokens, cookies, or raw sensitive prompts into the observation file.

```json
{
  "runs": [
    {
      "route": "direct-astra",
      "run_id": "direct-001",
      "task_fingerprint": "<sha256 from plan>",
      "completion_quality": 0.98,
      "context_retention": 0.97,
      "browser_reliability": 1.0,
      "tool_reliability": 0.99,
      "latency_seconds": 418.2,
      "input_tokens": 185000,
      "cache_write_tokens": 0,
      "cache_read_tokens": 25000,
      "output_tokens": 14000,
      "extra_cost_usd": 0.0,
      "audit_score": 0.80,
      "audit_evidence_complete": true,
      "success": true,
      "tests_passed": true,
      "regression": false
    }
  ]
}
```

Use the same browser/tool harness for both routes. The purpose is to compare provider routing, not accidentally compare two different tool stacks.

For auditability, Direct Astra evidence should include provider request/usage metadata available to the harness. Bedrock evidence should additionally retain the corresponding Bedrock invocation logging and CloudTrail authorization/API-event evidence when those controls are enabled. Store evidence references, not credentials.

## Evaluate

```bash
src/system/omniroute.sh benchmark-astra evaluate \
  --repo-path "$PWD" \
  --base-sha "$(git rev-parse HEAD)" \
  --task 'THE EXACT REPOSITORY-SCALE TASK' \
  --observations evidence/astra-route-runs.json
```

Exit status `0` means Bedrock qualifies as a benchmark candidate under the current policy. Exit status `3` means it does not. Neither result changes OmniRoute's selected production model.

## Promotion rule

A `candidate=true` report is evidence for a separate routing decision, not authority to modify production. Primary-route promotion must occur through the normal Hermes governance/release process after reviewing the raw run artifacts, tests, cost calculation, provider limits, and audit evidence.
