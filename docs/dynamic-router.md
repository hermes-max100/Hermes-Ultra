# Hermes Dynamic Router

`src/system/dynamic-router.sh` is a sourceable Bash router for Hermes profile orchestration. It turns a user request into routing metadata without calling any model provider.

## What It Uses From The Pasted Text

- Model and skill registries
- Profile-to-skill mapping
- Request complexity scoring
- Intent classification
- Thinking-level selection
- Attribution footer output
- CLI entry points for evaluation and reporting
- Cost-control metadata for history, background work, skill budgets, and heartbeat intervals

## What It Intentionally Drops

- Hardcoded speculative model names
- Autonomous subscription-browser access
- Cookie or session-token based routing
- Offensive or unrestricted hacking routes
- Emoji-heavy attribution and non-portable integrations

## Policy

The router only emits compliant access methods:

- `official_api`
- `local_runtime`
- `manual_handoff_or_configure_api`

It does not scrape web UIs, use browser profiles, reuse cookies, bypass rate limits, or call providers directly.

## Cost Controls

The router reads `config/cost-policy.json` and emits cost-control metadata with every route:

- `max_history_messages`: caps conversation history at 20 messages by default.
- `mode`: marks heartbeat, cron, status, and classification requests as `background`.
- `heartbeat_interval_minutes`: gives each profile a slower polling interval.
- `enabled_skill_count`: counts the profile-scoped skills being sent with the route.
- `skill_budget`: defaults to 6 enabled skills per route.

Background tasks route through `HERMES_BACKGROUND_MODEL` when set to a registered model key. If it is not set, the router chooses the cheapest approved available path in this order: Gemini Flash when configured, OpenAI Fast when configured, then local runtime.

Interactive Direct Mode routes can use ZenMux when `ZENMUX_API_KEY` is present.
ZenMux is represented as `zenmux-router` and uses the documented
OpenAI-compatible endpoint `https://zenmux.ai/api/v1/`.

Interactive Direct Mode routes can also use NVIDIA NIM when `NVIDIA_API_KEY` is
present. NVIDIA NIM is represented as `nvidia-nim` and uses the documented
OpenAI-compatible endpoint `https://integrate.api.nvidia.com/v1`.

## Config Templates

- `config/hermes-cost-controls.example.json`: framework-neutral Hermes-style target config for history caps, background model routing, skill budgets, and heartbeat intervals.
- `config/openclaw-cost-controls.example.json`: OpenClaw-style template based on the same policy. Treat it as a mapping guide and confirm exact schema support in the OpenClaw version you run.
- `config/cloud-models.env.example`: local API-key template for OpenAI, Gemini, Perplexity, Venice, OpenRouter, ZenMux, and NVIDIA NIM.

## Cost Audit

Run the audit to verify the four cost controls are present and to preview the background heartbeat route:

```bash
src/system/cost-audit.sh
src/system/cost-audit.sh --json
```

## Usage

```bash
source src/system/dynamic-router.sh --source
hardwire_route "review this vendor contract" "legal"
print_attribution "review this vendor contract" "legal"
```

```bash
src/system/dynamic-router.sh --evaluate "threat model my owned SaaS API" security
src/system/dynamic-router.sh --json "analyze an options spread" trading
src/system/dynamic-router.sh --json "heartbeat poll anything new" legal
src/system/dynamic-router.sh --json "fix this failing test" direct
src/system/dynamic-router.sh --report legal "daily matter sweep"
```

Use `src/system/cloud-model-picker.sh` to set `HERMES_MODEL_KEY_OVERRIDE` and
`HERMES_MODEL_OVERRIDE` before routing when you want a specific provider model.
Use `src/system/hermes-dispatch.sh` as the normal front door when you want the
router attribution footnote on every query.

## YOLO Retrieval Gates

`src/system/yolo-gate.sh` adds a separate gate lane for unavailable-human
retrieval work:

```bash
export HERMES_YOLO_MODE=retrieval
src/system/yolo-gate.sh check "search GitHub, Reddit, X threads, skills.sh, and Skill Hub"
```

When enabled, a configured high-quality model may approve retrieval/source
expansion gates. Human approval is still required for send/post/delete/purchase,
credential/OTP entry, security/privacy changes, app installs, destructive shell,
private indexing, exploit execution, and public-target scanning.

## Profiles

- `legal`: legal review, legal research, citation validation, memory retrieval, provider routing.
- `trading`: options analysis, market research, risk management, memory retrieval, provider routing.
- `security-research`: authorized security review, threat modeling, remediation planning, memory retrieval, provider routing.
- `solopreneur`: income generation, product launch, marketing analysis, memory retrieval, provider routing.
- `marketing`: marketing analysis, product launch, web research, memory retrieval, provider routing.
- `direct`: coding review, web research, memory retrieval, provider routing, direct-but-bounded response policy.

## Verification

```bash
bash tests/test_dynamic_router.sh
bash tests/test_cost_audit.sh
bash tests/test_direct_mode_policy.sh
```
