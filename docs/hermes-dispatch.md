# Hermes Dispatch

`src/system/hermes-dispatch.sh` is the front door for Hermes tasks.

It does four things for every query:

1. Loads local cloud keys from `.env.cloud-models.local` when present.
2. Loads selected cloud model from `.hermes/cloud-model-selection.env` when present.
3. Lets the user override model and thinking level.
4. Runs the dynamic router and prints the model/skill/thinking attribution footnote.

The skill set remains automatic. The user can pick model and thinking level; the
router still chooses the correct profile skills for the query.

## Usage

```bash
src/system/hermes-dispatch.sh "fix this failing test"
src/system/hermes-dispatch.sh --profile legal "review this clause"
src/system/hermes-dispatch.sh --thinking high "debug this production issue"
src/system/hermes-dispatch.sh --json "route this only"
```

## Manual Model Selection

```bash
src/system/cloud-model-picker.sh select nvidia meta/llama-3.3-70b-instruct
src/system/hermes-dispatch.sh --thinking high "answer with my selected model"
```

Or inline:

```bash
src/system/hermes-dispatch.sh \
  --model-key nvidia-nim \
  --model-id meta/llama-3.3-70b-instruct \
  --thinking critical \
  "answer with this exact model"
```

## Daily Refresh

```bash
src/system/daily-refresh.sh
```

This validates catalogs, pulls OBLITERATUS when a Git checkout is present, and
runs the router/picker policy tests. Logs go to:

```text
.hermes/refresh/
```
