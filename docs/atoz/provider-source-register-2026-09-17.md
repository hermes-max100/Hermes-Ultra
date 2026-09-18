# Provider Source Register — 2026-09-17

Documentation facts do not establish live access. Every adapter remains disabled until credentials, tenant scope, data policy, and a controlled verification gate are satisfied.

| Provider | Verified API/model | Current documented economics / access | Limitation recorded for pilot | Official source |
| --- | --- | --- | --- | --- |
| OpenAI | `gpt-realtime-2.1` | Audio $32/1M input tokens, $64/1M output tokens | Account access and call economics not measured | https://developers.openai.com/api/docs/models/gpt-realtime-2.1 |
| OpenAI | `gpt-live-transcribe` | $0.017 per realtime audio minute | Account access not measured | https://developers.openai.com/api/docs/models/gpt-live-transcribe |
| Google | `gemini-3.8-live` | GA 2026-09-15; paid audio input ~$0.005/min, output ~$0.018/min | Real telephone latency/tool behavior not measured | https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live and https://ai.google.dev/gemini-api/docs/pricing |
| Speechmatics | Realtime Standard / Enhanced | $0.24/hr / $0.43/hr; $100 starting credit; 2 free realtime sessions | Model-training discount is opt-in and changes data-use terms; left off | https://www.speechmatics.com/pricing |
| Speechmatics | pricing transition | From 2026-10-01 PAYG remains; >500hr PAYG discount ends and discounts move to packs/subscriptions | Re-read pricing after 2026-10-01 | https://www.speechmatics.com/company/articles-and-news/scale-more-easily-with-speechmatics |
| Murf | `falcon-2` streaming TTS | $0.01/1k chars; `/v1/speech/stream`; documented ~100ms first audio; default concurrency 5 US-East / 2 other regions | TTS only; no measured telephone result | https://murf.ai/api/docs/text-to-speech-models/falcon-2 |
| xAI | `grok-voice-latest` | `wss://api.x.ai/v1/realtime`; $0.08/min audio sent or received + $0.004 text input; 10 sessions/team; 120-min max | Live access not measured | https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech and https://docs.x.ai/developers/pricing |

`config/atoz/providers.json` sets every provider `enabled: false`. Enablement requires authorized credentials, exact scope, a data-retention decision, controlled replay evidence, reconciled costs, and no safety/task-accuracy regression.
