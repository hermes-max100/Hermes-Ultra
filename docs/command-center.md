# Lane Command Center

The operator's view of the whole machine: one channel per lane, an orchestrator council you can talk to, Mission Control for running/queued/blocked/backlog work, and an R&D tab for Arena and Hermes. It gives an overview first and is never more than one or two clicks from the logs.

Code: `src/hermes_ultra/command_center/`. It is standard-library Python with a single-page UI and has no build step. Claude needs the optional `anthropic` SDK; the other providers do not.

## Run it

```bash
pip install -e '.[command-center]'          # adds the anthropic SDK for Claude seats
export ANTHROPIC_API_KEY=...  OPENAI_API_KEY=...  LLAMA_API_KEY=...   # only the providers you use
python -m hermes_ultra.command_center serve            # http://127.0.0.1:4710
python -m hermes_ultra.command_center serve --demo     # adds sample work, every item badged DEMO
```

State lives in SQLite at `.hermes/command_center.db` (gitignored); override with `--db` or `HERMES_CC_DB`.

Remote access (phone, tailnet): set `HERMES_CC_TOKEN`, bind `--host 0.0.0.0`, and open `http://<host>:4710/#token=<token>`. The token is stored in the browser and the fragment is removed from the URL. The server refuses to bind off loopback without a token. Voice input requires HTTPS off localhost, so put it behind `tailscale serve` (or another TLS proxy) for the phone.

## The four tabs

| Tab | What it answers | Drill path |
|---|---|---|
| **Lanes** | What each lane is producing | Owned/observed lane list → isolated feed with a filter per work type (`code`, `research`, `draft`, `test`, `plan`, `ops`, `eval`) → output drawer with model, tokens, cost, latency, linked task |
| **Orchestrators** | One room with your lead models | Council thread on the left; roster on the right with promote/demote, drag or ↑↓ for speaking order, and per-model configuration |
| **Mission Control** | What's running, not running, queued, in backlog, blocked | KPI tiles → lane health matrix (Granular view adds outputs, tokens, cost, latency, last output, work mix) → click a lane to filter the board → task drawer with timeline, evidence, linked outputs and state moves |
| **Arena / Hermes** | What Hermes is doing right now | "Hermes is doing" / live hypothesis / latest output → R&D feed → experiment drawer with hypothesis, metrics, result and run log |

### Council rules

- Seated members answer in rank order, one after another, so each sees what the earlier ones said.
- `@claude` / `@hermes` addresses specific members, including bench models invited for one question. `#lane-build` (or `@lane-build`) attaches that lane's latest outputs as context.
- A member that can't run (missing key, SDK not installed, disabled) produces an **offline notice**, never an invented reply. Errors and refusals are labelled the same way and left out of later transcripts.
- At least one member must stay seated. Promotions and demotions are logged in the activity feed.
- Keys stay in the server environment. The roster stores only the environment variable's *name*, and the store rejects anything that looks like a key.

### Voice

- **Mic** (or Ctrl+M): talk, stop, and it sends (Auto-send). Turn Auto-send off to edit before sending.
- **Hands-free**: keeps listening and sends each finished sentence.
- **Read replies**: speaks new council replies with a distinct voice per model; 🔊 replays any reply.

Voice uses the browser's Web Speech API, so it needs no keys and no server audio. Use Chrome or Edge.

### Evidence gates

- `done` requires evidence: test output, an artifact path, a URL or a commit.
- `blocked` requires a blocker; `failed` requires a note.
- Concluding an experiment requires a result summary.

Allowed task moves: backlog → queued/running/blocked/failed; queued → running/backlog/blocked/failed; running → done/failed/blocked/queued; blocked → queued/running/backlog/failed; failed → queued/backlog; done → backlog (reopen).

## Feeding it

Lanes and agents report over HTTP. The live stream (`GET /api/stream`, server-sent events) pushes every change to open browsers.

```python
from hermes_ultra.command_center.client import CommandCenterClient
cc = CommandCenterClient(actor="hermes")            # HERMES_CC_URL / HERMES_CC_TOKEN from env
t = cc.create_task("lane-hermes", "Self-repair ablation", state="queued")
cc.move_task(t["id"], "running", progress=0.2)
cc.report_output("lane-hermes", title="Ablation run 1", work_type="eval", model="hermes3:70b",
                 body="repair rate 61% -> 48%", tokens_in=4200, tokens_out=900, latency_ms=8300, task_id=t["id"])
cc.move_task(t["id"], "done", evidence="artifacts/ablation/run1.json")
```

```bash
python -m hermes_ultra.command_center post lane-ops "Rotated arena keys" --work-type ops --author cron
python -m hermes_ultra.command_center task add lane-build "Wire lane bus WAL replay"
python -m hermes_ultra.command_center task move t-abc123 done --evidence "pytest: 14 passed"
```

API surface (JSON; mutating calls need `Content-Type: application/json`; cross-origin requests are rejected):
`GET /api/state` · `GET|POST /api/lanes` · `PATCH /api/lanes/{id}` · `GET|POST /api/lanes/{id}/messages` · `GET|POST /api/tasks` · `GET /api/tasks/{id}` · `POST /api/tasks/{id}/transition` · `GET|POST /api/council/members` · `PATCH /api/council/members/{id}` · `POST /api/council/members/{id}/promote|demote` · `POST /api/council/reorder` · `GET|POST /api/council/messages` · `GET|POST /api/experiments` · `GET|PATCH /api/experiments/{id}` · `POST /api/experiments/{id}/events` · `GET /api/activity` · `GET /api/stream`

## Default roster

These are starting points; change them in the roster's **Configure** panel. The model ids for ChatGPT, Meta Muse and Gemini should be checked against each provider's current list.

| Seat | Provider | Model | Credential env |
|---|---|---|---|
| Claude (council #1) | anthropic SDK | `claude-opus-5-5`, effort `medium`, server-side refusal fallback on | `ANTHROPIC_API_KEY` or an `ant auth` profile |
| ChatGPT (council #2) | OpenAI Chat Completions | `gpt-5` | `OPENAI_API_KEY` |
| Meta Muse (council #3) | Llama API, OpenAI-compatible | `Llama-4-Maverick-17B-128E-Instruct-FP8` | `LLAMA_API_KEY` |
| Hermes (bench) | local OpenAI-compatible (Ollama) | `hermes3:70b` | none |
| Gemini (bench) | Gemini OpenAI-compatible endpoint | `gemini-2.5-pro` | `GEMINI_API_KEY` |

Cost is computed only where pricing is known (Claude list prices, or `price_in_per_m` / `price_out_per_m` set on the member); otherwise it shows `—` and is not estimated.
