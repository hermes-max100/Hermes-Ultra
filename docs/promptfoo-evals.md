# Promptfoo Evals

Hermes uses Promptfoo as a regression gate for dynamic prompting, model routing,
skill routing, and approval-boundary behavior.

## Pack Layout

```text
promptfoo/
  promptfooconfig.yaml
  evals/
    prompts.py
    hermes_provider.py
    assertions.py
```

The dynamic prompt builder receives test variables and returns chat messages.
The provider calls `src/system/hermes-dispatch.sh --report` in dry orchestration
mode. Assertions verify the route and policy text.

## Local Check

```bash
src/system/promptfoo-evals.sh check
```

This validates Python syntax and core assertion behavior without installing or
running Promptfoo.

## Full Promptfoo Run

```bash
src/system/promptfoo-evals.sh run
```

This uses:

```bash
npx promptfoo@latest eval -c promptfoo/promptfooconfig.yaml
```

Reports are written under `.hermes/reports/`.

## What It Tests

- `kimi-code` and Kimi 3 route to `moonshotai/kimi-k3`.
- Legal appeal/evidence prompts carry legal routing signals.
- JARVIS send/write actions stay approval gated.
- Mobile app control drafts but does not send or post.
- Dynamic prompts include the untrusted-data and no-secrets policies.
