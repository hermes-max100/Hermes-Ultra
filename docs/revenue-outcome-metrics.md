# Revenue OS Outcome Metrics

Revenue OS allocates attention based on verified business outcomes, not agent activity volume.

## First-class outcome events

`EconomicLedger.record_business_outcome()` accepts only these event types:

- `qualified_lead`
- `appointment_booked`
- `completed_outcome`

Each event is attributed to a `run_id` and `strategy_id`. Callers should provide an idempotency key for externally observed outcomes so retries cannot inflate the scorecard.

`completed_outcome` is the workflow's declared terminal business result. Examples include a paid sale, a completed billable workflow, or another explicitly defined result. The workflow owns that definition; token usage, messages, tool calls, drafts, and agent steps are never completed outcomes.

## Scorecard definitions

`EconomicMetrics.from_ledger()` derives:

- `qualified_leads`: count of verified `qualified_lead` events.
- `appointments_booked`: count of verified `appointment_booked` events.
- `completed_outcomes`: count of verified `completed_outcome` events.
- `conversion_rate`: `completed_outcomes / qualified_leads`; `None` when there are no qualified leads.
- `attributed_revenue`: received revenue attributed to the selected run/strategy.
- `gross_margin`: `(attributed_revenue - cost) / attributed_revenue`; `None` when attributed revenue is zero.
- `cost_per_completed_outcome`: `cost / completed_outcomes`; `None` when there are no completed outcomes.

The existing `revenue`, `cost`, `gross_profit`, and `roi` fields remain available for compatibility.

## Resource allocation signal

`EconomicMetrics.resource_allocation_signal()` is a deterministic policy gate. The caller supplies:

- maximum acceptable cost per completed outcome,
- minimum gross margin,
- minimum conversion rate, and
- minimum number of completed outcomes.

The result is `ResourceAllocationSignal(action="increase" | "hold", reasons=(...))`.

A workflow receives `increase` only when every supplied threshold is satisfied. Missing denominators, insufficient completed outcomes, or a failed threshold produce `hold` with explicit reason codes.

This signal does not grant financial authority, spend money, deploy infrastructure, or mutate treasury limits. It is evidence for a separate governed resource-allocation decision.

## Explicit non-inputs

The allocation signal does not consume token counts, conversation counts, model calls, tool calls, wall-clock activity, generated drafts, or other agent-activity vanity metrics. Those may remain useful for observability and cost accounting, but they cannot substitute for verified business outcomes.
