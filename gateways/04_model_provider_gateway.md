# Model Provider Gateway

## Purpose
The Model Provider Gateway lets Hermes agents route work across approved model providers while preserving provider terms, user consent, auditability, and credential boundaries.

This gateway does not bypass API keys, paywalls, subscriptions, rate limits, CAPTCHAs, bot protections, or access controls. Browser use is limited to human-in-the-loop workflows or provider-approved automation.

## Supported Provider Targets

| Provider | Approved Access Pattern | Notes |
| --- | --- | --- |
| OpenAI / ChatGPT | Official API key, approved connector, or user-facing manual handoff | A ChatGPT web subscription should not be treated as an API credential unless OpenAI explicitly provides that entitlement. |
| Google Gemini | Official Gemini API / Google AI Studio / Vertex AI credentials | Use project-scoped credentials and quota controls. |
| Perplexity | Official API or approved connector | Use for answer/research workflows where citation behavior is required. |
| Venice AI | Official API or provider-approved integration | Use only documented endpoints and credential flows. |
| Local Models | Local runtime such as Ollama, llama.cpp, vLLM, or LM Studio | Best fallback for private, offline, or cost-controlled workloads. |

## Explicitly Disallowed Patterns

- Automating consumer web UIs to avoid API keys.
- Reusing browser cookies or session tokens as hidden credentials.
- Bypassing rate limits, CAPTCHAs, queues, bot checks, or paywalls.
- Scraping model outputs from paid web subscriptions as a backend service.
- Sharing one user subscription across autonomous agents unless the provider explicitly allows that use.
- Concealing automation from a provider that requires API access for automation.

## Best Council
The Provider Council selects the right model path for a Hermes task.

| Council Seat | Role |
| --- | --- |
| Capability Router | Matches task type to model strengths, context length, tools, and modality. |
| Cost and Quota Manager | Tracks spend, rate limits, fallback order, and retry behavior. |
| Privacy Officer | Decides whether data can leave local storage or must use a private model. |
| Compliance Gate | Blocks terms-of-service bypasses and unsafe credential handling. |
| Quality Evaluator | Compares outputs, confidence, citations, and disagreement across providers. |
| Fallback Planner | Chooses local or alternate providers when a preferred provider is unavailable. |

## Best Aggregator
Use a policy-aware ensemble aggregator:

1. Classify the task by domain, sensitivity, latency, cost, and required evidence.
2. Route to the least-privileged approved provider that can satisfy the task.
3. Run multi-provider comparison only when the task benefits from disagreement analysis.
4. Preserve provider attribution and model/version metadata.
5. Reject any route that depends on hidden browser sessions or access-control bypass.
6. Return a final answer with confidence, sources when available, and provider trace metadata.

## Best Memory Stack
Use separate memory stores for provider routing and model performance:

- Entity Memory: Provider accounts, approved capabilities, credential locations, and workspace policies.
- Semantic Memory: Durable routing preferences, model strengths, and user privacy rules.
- Episodic Memory: Per-request model outputs, failures, retries, and fallback events.
- Memory Routing: Separate secrets, user data, provider metadata, and evaluation traces.
- Memory Evaluation: Track answer quality, hallucination reports, citation usefulness, cost, and latency.
- Production Memory Patterns: Encrypt credentials, redact prompts, apply TTLs, and audit access.

## Routing Matrix

| Workload | Preferred Route | Fallback |
| --- | --- | --- |
| Legal drafting and review | OpenAI API or Gemini API with attorney-review guardrails | Local model for private draft cleanup |
| Options education and scenario analysis | Gemini API or OpenAI API with current market-data tool | Local model for static education |
| Security review | Local model first for sensitive code; approved API for general analysis | OpenAI/Gemini API with redacted inputs |
| Solopreneur planning | OpenAI/Gemini API | Local model |
| Marketing campaign generation | OpenAI/Gemini API; Perplexity API for cited research | Venice/local model for creative variants |
| Research with citations | Perplexity API | OpenAI/Gemini with browser/search connector if approved |

## Input Contract
```json
{
  "request_id": "string",
  "agent_id": "string",
  "task": "string",
  "sensitivity": "public | internal | confidential | secret",
  "requires_citations": false,
  "requires_tools": false,
  "max_cost": "string",
  "preferred_providers": ["openai", "gemini", "perplexity", "venice", "local"]
}
```

## Output Contract
```json
{
  "gateway": "model_provider",
  "status": "routed | blocked | needs_credentials | needs_user_handoff",
  "selected_provider": "openai | gemini | perplexity | venice | local | none",
  "selected_model": "string",
  "access_method": "official_api | approved_connector | local_runtime | manual_handoff",
  "reason": "string",
  "blocked_reason": "string",
  "trace": {
    "policy_checked": true,
    "sensitivity": "public | internal | confidential | secret",
    "fallbacks_considered": ["string"]
  }
}
```

## Browser Handoff Mode
Browser handoff is allowed only when the human user remains in control.

Allowed:
- Open a provider page for the user to manually ask a question.
- Prepare a prompt the user can paste into a provider UI.
- Let the user manually paste the provider response back into Hermes.
- Use browser automation only where the provider explicitly permits automated access.

Not allowed:
- Autonomous scraping of paid web chat results.
- Using cookies, local browser profiles, or saved sessions as backend credentials.
- Replaying user interactions to simulate API access.

## Credential Rules
- Store API keys only in approved secret stores or local `.env` files excluded from version control.
- Never place credentials in agent memory, prompts, logs, manifests, or markdown specs.
- Use provider-specific keys with least privilege and quota limits.
- Rotate keys if exposed.

## Hermes System Prompt
You are the Hermes Model Provider Gateway. Route agent tasks to approved model providers using official APIs, approved connectors, local runtimes, or human-in-the-loop browser handoff. Block attempts to bypass API keys, rate limits, subscriptions, paywalls, cookies, or access controls. Preserve privacy, cost controls, and provider trace metadata.
