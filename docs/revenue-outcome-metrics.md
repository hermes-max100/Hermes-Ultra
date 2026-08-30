# Revenue OS Outcome Metrics

Revenue OS allocates attention based on verified business outcomes, not agent activity volume.

## First-class outcome events

`EconomicLedger.record_business_outcome()` accepts only these event types:

- `qualified_lead`
- `appointment_booked`
- `completed_outcome`

Each event is attributed to a `run_id` and `strategy_id` and must include a non-empty idempotency key. Retries with the same outcome type and idempotency key resolve to the existing ledger event instead of inflating the scorecard.

`completed_outcome` is the workflow's declared terminal business result. Examples include a paid sale, a completed billable workflow, or another explicitly defined result. The workflow owns that definition; token usage, messages, tool calls, drafts, and agent steps are never completed outcomes.

## Scorecard definitions

`EconomicMetrics.from_ledger()` derives:

- `qualified_leads`: count of verified `qualified_lead` events.
- `appointments_booked`: count of verified `appointment_booked` events.
- `completed_outcomes`: count of verified `completed_outcome` events.
- `conversion_rate`: `completed_outcomes / qualified_leads`; `None` when there are no qualified leads.
- `attributed_revenue`: received revenue attributed to the selected run/strategy.
- `gross_margin`: `(attributed_revenue - cost) / attributed_revenue`; `None` when attributed revenue is zero or negative.
- `cost_per_completed_outcome`: `cost / completed_outcomes`; `None` when there are no completed outcomes.

The existing `revenue`, `cost`, `gross_profit`, and `roi` fields remain available for compatibility.

### Currency boundary

A scorecard never combines raw monetary values from different currencies. If a selected run or strategy contains more than one currency, `from_ledger()` fails closed unless the caller supplies an explicit `currency=` scope. The scope filters revenue, cost, and business-outcome events to that currency before deriving ratios.

## Resource allocation signal

`EconomicMetrics.resource_allocation_signal()` is a deterministic policy gate. The caller supplies:

- maximum acceptable cost per completed outcome,
- minimum gross margin,
- minimum conversion rate, and
- minimum number of completed outcomes.

The result is `ResourceAllocationSignal(action="increase" | "hold", reasons=(...))`.

A workflow receives `increase` only when every supplied threshold is satisfied and the evidence is internally consistent. The signal fails closed to `hold` when any of these conditions apply:

- attributed revenue is zero or negative,
- completed outcomes exceed qualified leads,
- conversion rate is outside the range `0..1`,
- a required denominator is unavailable,
- completed outcomes are below the minimum, or
- any configured threshold fails.

Negative revenue is rejected by `EconomicEngine` before the payment adapter is called, so a malformed revenue event cannot produce an external payment-side effect through the normal Revenue OS engine path.

This signal does not grant financial authority, spend money, deploy infrastructure, or mutate treasury limits. It is evidence for a separate governed resource-allocation decision.

## Explicit non-inputs

The allocation signal does not consume token counts, conversation counts, model calls, tool calls, wall-clock activity, generated drafts, or other agent-activity vanity metrics. Those may remain useful for observability and cost accounting, but they cannot substitute for verified business outcomes.
