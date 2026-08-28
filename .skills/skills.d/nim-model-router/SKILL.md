# nim-model-router

Use this skill to route inference requests to the optimal NIM-hosted model based on task type, latency, context, and cost.

## Rules

- Match model capability to task type: coding, reasoning, vision, or summary.
- Respect latency budget constraints.
- Prefer smaller models when capability is sufficient.
- Log routing decisions for cost analysis.
- Fall back to a default model if routing is uncertain.

## Outputs

- model selection
- routing table
- cost estimate
- latency estimate
