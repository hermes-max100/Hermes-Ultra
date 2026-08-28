# Cloud Model Picker

Hermes can switch cloud models explicitly instead of only choosing a provider.

The picker writes a local env file:

```text
.hermes/cloud-model-selection.env
```

That file is private runtime state and is excluded from transfer exports unless
you explicitly include logs/runtime state.

## List Models

```bash
src/system/cloud-model-picker.sh list
src/system/cloud-model-picker.sh list nvidia
src/system/cloud-model-picker.sh providers
src/system/cloud-model-picker.sh keys
src/system/cloud-model-picker.sh list zenmux
src/system/cloud-model-picker.sh list omniroute
```

`keys` reports only whether each provider key is loaded. It never prints secret
values.

## First-Time Setup

Create the private key file:

```bash
src/system/cloud-model-picker.sh setup
```

This creates:

```text
.env.cloud-models.local
```

The file is ignored by git/export rules. Add only the provider keys you use,
then re-run:

```bash
src/system/cloud-model-picker.sh keys
```

## Sync Provider Models

After keys are loaded, sync each provider's live `/models` endpoint into a local
catalog:

```bash
src/system/cloud-model-picker.sh sync all
src/system/cloud-model-picker.sh sync nvidia
src/system/cloud-model-picker.sh sync openrouter
```

Synced models are written to:

```text
.hermes/cloud-model-catalog.local.json
```

After sync, `list` includes both the built-in catalog and provider-discovered
models:

```bash
src/system/cloud-model-picker.sh list nvidia
src/system/cloud-model-picker.sh select nvidia <synced-model-id>
```

## Select A Catalog Model

```bash
src/system/cloud-model-picker.sh select nvidia meta/llama-3.3-70b-instruct
source "$(src/system/cloud-model-picker.sh env)"
src/system/dynamic-router.sh --json "use my selected cloud model" direct
```

For quick manual switching, use the shortcut wrapper:

```bash
src/system/model.sh onith
src/system/model.sh glm
src/system/model.sh omni-glm
src/system/model.sh kimi
src/system/model.sh kimi-code
src/system/model.sh kimi3
src/system/model.sh kimi3-openrouter
src/system/model.sh yolo-approver
src/system/model.sh yolo-env
src/system/model.sh receipt
```

Running `src/system/model.sh` with no arguments opens a numbered menu.

GLM 5.2 is registered under the NVIDIA provider:

```bash
src/system/cloud-model-picker.sh select nvidia glm-5.2
```

GLM 5.2 is also exposed as an explicit OmniRoute target:

```bash
src/system/cloud-model-picker.sh select omniroute nvidia/glm-5.2
src/system/model.sh omni-glm
```

Kimi is registered as a frontier coding/agentic family. The preferred coding
path is Kimi 3 through 9Router:

```bash
src/system/cloud-model-picker.sh select 9router kimi/kimi-latest
src/system/model.sh kimi

src/system/cloud-model-picker.sh select 9router moonshotai/kimi-k3
src/system/model.sh kimi-code
```

Kimi 3 is also available explicitly:

```bash
src/system/cloud-model-picker.sh select 9router moonshotai/kimi-k3
src/system/model.sh kimi3

src/system/cloud-model-picker.sh select openrouter moonshotai/kimi-k3
src/system/model.sh kimi3-openrouter
```

The older Kimi 2.7 code route remains available as a legacy fallback:

```bash
src/system/model.sh kimi27-code
```

## YOLO Retrieval Gate Approver

YOLO mode is intentionally narrow. It lets the highest-quality configured model
approve retrieval, source-expansion, research-depth, skill-discovery, local
report, and draft-generation gates when you are not available. It does not
approve sends, posts, deletes, purchases, credentials, OTPs, security/privacy
changes, app installs, destructive shell, exploit execution, or public-target
scanning.

Enable it for retrieval gates:

```bash
export HERMES_YOLO_MODE=retrieval
src/system/yolo-gate.sh check "look on GitHub, Reddit, X threads, skills.sh, and Skill Hub"
```

Default approver order:

```text
9router:moonshotai/kimi-k3
9router:kimi/kimi-latest
omniroute:nvidia/glm-5.2
nvidia:glm-5.2
openrouter:moonshotai/kimi-k3
onith:onith-1.0
```

If your gateway exposes Sol 5.6 or Fable 5, put them at the front of the chain:

```bash
export HERMES_YOLO_APPROVER_CHAIN="9router:openai/sol-5.6,9router:fable/fable-5,9router:moonshotai/kimi-k3,nvidia:glm-5.2"
src/system/model.sh yolo-approver
```

To source the selected approver into a shell:

```bash
source <(src/system/model.sh yolo-env)
```

Other registered providers include Onith Local, OpenAI, Gemini, Perplexity,
OpenRouter, Venice, NVIDIA NIM, ZenMux, and OmniRoute. Any OpenAI-compatible
provider can also be manually targeted with `custom` when the exact model id is
not yet in the catalog.

Onith 1.0 is registered as a local runtime:

```bash
src/system/cloud-model-picker.sh select onith onith-1.0
```

The router output includes:

```json
{
  "model": "nvidia-nim",
  "provider": "nvidia",
  "provider_model_id": "meta/llama-3.3-70b-instruct"
}
```

## Receipt

Use `receipt` whenever you want to verify exactly what Hermes will use:

```bash
src/system/cloud-model-picker.sh receipt
```

The receipt includes:

```text
provider=nvidia
model=glm-5.2
router_model=nvidia-nim
selection_mode=manual
api_key_env=NVIDIA_API_KEY
api_key_status=loaded
base_url=https://integrate.api.nvidia.com/v1
```

It does not print API keys.

## Auto-Pick A Model

Use `auto` when you want Hermes to choose the best available model for the
query. It scores catalog models against the task and prefers providers with a
loaded API key.

```bash
source .env.cloud-models.local
src/system/cloud-model-picker.sh auto "deep coding and architecture task"
src/system/cloud-model-picker.sh show
```

The selection file records:

```bash
export HERMES_MODEL_SELECTION_MODE=auto
```

## Run Against The Selected Cloud Model

`hermes-dispatch.sh` only prints routing metadata. To actually send the prompt
to the selected OpenAI-compatible provider, use:

```bash
src/system/hermes-run.sh --dry-run "test the route without calling the provider"
src/system/hermes-run.sh "send this prompt to the selected cloud model"
src/system/hermes-run.sh --auto "pick the best cloud model and run this task"
```

`hermes-run.sh` supports the OpenAI-compatible providers in the local catalog:
Onith Local, OpenAI, Gemini, Perplexity, OpenRouter, Venice, NVIDIA NIM, ZenMux,
OmniRoute, and 9Router.

## OmniRoute Gateway

OmniRoute is treated as an optional provider gateway under Hermes. Hermes still
chooses skills, thinking level, project context, and manual-vs-auto mode.
OmniRoute handles its own backend pool when selected.

```bash
export OMNIROUTE_API_KEY="local-placeholder"
export OMNIROUTE_BASE_URL="http://127.0.0.1:20128/v1"

src/system/cloud-model-picker.sh list omniroute
src/system/cloud-model-picker.sh select omniroute auto/coding
src/system/cloud-model-picker.sh select omniroute nvidia/glm-5.2
src/system/hermes-run.sh --dry-run "fix this failing test"
src/system/hermes-run.sh "fix this failing test"
```

The first-class Hermes wrapper is:

```bash
src/system/omniroute.sh doctor
src/system/omniroute.sh start-bg
src/system/omniroute.sh sync
src/system/omniroute.sh select auto
```

See `docs/omniroute-integration.md`.

## 9Router Gateway

9Router is treated as an optional provider gateway under Hermes. Hermes still
chooses skills, thinking level, project context, and manual-vs-auto mode.
9Router handles its own backend pool, RTK/token saving, quota tracking, and
fallback when selected.

Hermes defaults 9Router to `http://127.0.0.1:20127/v1` so it can run beside
OmniRoute on `20128`.

```bash
export NINEROUTER_API_KEY="local-9router-placeholder"
export NINEROUTER_BASE_URL="http://127.0.0.1:20127/v1"

src/system/cloud-model-picker.sh list 9router
src/system/cloud-model-picker.sh select 9router auto/coding
src/system/cloud-model-picker.sh select 9router nvidia/glm-5.2
src/system/hermes-run.sh --dry-run "fix this failing test"
src/system/hermes-run.sh "fix this failing test"
```

The first-class Hermes wrapper is:

```bash
src/system/ninerouter.sh doctor
src/system/ninerouter.sh start-bg
src/system/ninerouter.sh sync
src/system/ninerouter.sh select auto
```

See `docs/9router-integration.md`.

## Select A Custom Model ID

Use `custom` when the provider supports a model that is not in the local catalog:

```bash
src/system/cloud-model-picker.sh custom nvidia nvidia/my-model-id
source "$(src/system/cloud-model-picker.sh env)"
```

Examples:

```bash
src/system/cloud-model-picker.sh custom openrouter anthropic/claude-sonnet-4
src/system/cloud-model-picker.sh custom venice llama-3.3-70b
src/system/cloud-model-picker.sh custom gemini gemini-3.5-pro
```

## Clear Selection

```bash
src/system/cloud-model-picker.sh clear
```

## Termux Pattern

Inside Ubuntu proot:

```bash
cd /root/hermes-max
source .env.cloud-models.local
src/system/cloud-model-picker.sh list nvidia
src/system/cloud-model-picker.sh select nvidia meta/llama-3.3-70b-instruct
source "$(src/system/cloud-model-picker.sh env)"
src/system/dynamic-router.sh --json "answer with the selected model" direct
```
