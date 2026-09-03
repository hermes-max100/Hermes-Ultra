# Voice-Agent Open-Source Review — 2026-09-03

This review records the GitHub projects considered for the Hermes Ultra voice
foundation. No third-party source code was copied into the implementation. The
selected ideas were expressed as new Hermes-owned contracts and tests.

| Project | License | Useful pattern | Hermes decision |
| --- | --- | --- | --- |
| [LiveKit Agents](https://github.com/livekit/agents) | Apache-2.0 | Replaceable STT/LLM/TTS components, semantic turn detection, telephony, MCP, event-level agent tests | Adopt provider boundaries, interruption cancellation, and event-oriented replay tests; do not add the runtime dependency yet |
| [Pipecat](https://github.com/pipecat-ai/pipecat) | BSD-2-Clause | Composable real-time pipelines, structured flows, multiple transports and providers | Keep business state independent from audio transport; evaluate later as a runtime candidate |
| [Anthropic Commerce Agents](https://github.com/anthropics/commerce-agents) | Apache-2.0 | Common governed kernel, typed backends, staged writes, gates that hold across runtimes, cross-package verification | Adopt the kernel/backend separation and staged recovery actions; do not import Claude-specific authority or runtime code |
| [ElevenLabs Python SDK](https://github.com/elevenlabs/elevenlabs-python) | MIT | Current ElevenAgents baseline, client tools, server-side Speech Engine, automatic cancellation when callers interrupt | Keep ElevenLabs as the initial provider; represent interruption cancellation in the provider contract |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT | Current MCP 2026-07-28 server/client contracts and typed tools | Reuse Hermes' existing MCP 2026-07-28 gateway; do not introduce a duplicate control plane |

## What was deliberately not integrated

- No generic standalone voice-agent application. Hermes already owns routing,
  evidence, economic metrics, delegated identity, and MCP policy.
- No provider SDK dependency. The first merge establishes stable contracts before
  credentials or provider-specific event shapes are introduced.
- No autonomous SMS/email execution. Recovery actions are staged and idempotent;
  remote writes remain behind Hermes authority and delegated-scope checks.
- No provider promotion based on latency or nominal per-minute price alone. A
  candidate must preserve completed bookings, critical fields, handoffs, recovery
  performance, safety, and evidence.

## Next integration order

1. Implement an ElevenLabs adapter against `RealtimeVoiceProvider` and normalize
   its event stream into `VoiceProviderEvent`.
2. Build the replay corpus and measure the current baseline.
3. Connect staged SMS, email, CRM, calendar, and dispatch actions through the
   permissioned Home Services MCP surface.
4. Shadow-test Muse transcription and Alma reasoning only after the baseline report
   is reproducible.
5. Evaluate LiveKit or Pipecat only if their runtime improves outcome economics or
   distribution without weakening Hermes authority.

