# Hermes Maintenance Loop

Hermes now has three maintenance loops:

- Runtime routing: `src/system/model.sh`, `src/system/hermes-run.sh`, and skill routers.
- Gateway health: `src/system/gateway-watchdog.sh`.
- External source freshness: `src/system/external-source-sweep.sh`.

## Gateway Watchdog

```bash
src/system/gateway-watchdog.sh --dry-run --required 9router,omniroute
src/system/gateway-watchdog.sh --required 9router,omniroute
```

The watchdog checks each gateway's `/models` endpoint through the existing
gateway wrapper scripts. If a gateway is installed but unhealthy, it attempts a
background restart unless `--dry-run` or `--no-restart` is set.

Health events are written to:

```bash
.hermes/logs/gateway-health.jsonl
```

## External Source Sweep

```bash
src/system/external-source-sweep.sh run
src/system/external-source-sweep.sh run --offline
src/system/external-source-sweep.sh status
```

The sweep reads:

```bash
config/external-skill-sources.json
```

It clones or updates each source into:

```bash
.hermes/external-cache/
```

Then it inspects metadata without executing external code and writes:

```bash
.hermes/reports/external-source-sweep-<timestamp>.md
.hermes/reports/external-source-sweep-<timestamp>.jsonl
.hermes/external-proposals/<source>-<timestamp>/
```

Review proposals are created when a source is high-risk, has package/install
files, fails to update, or contains risky text signals. Promotion remains manual.

## Skill Evolution Validation

`src/system/skill-evolver.sh promote <proposal-id>` now validates the proposed
trigger terms in a temporary copy of `.skills/` before changing the real skill.

Manual validation:

```bash
src/system/skill-evolver.sh validate-proposal <proposal-id>
```

## Daily Summary

```bash
src/system/daily-summary.sh
```

The summary combines:

- active model receipt
- provider key status
- gateway health
- skill drift dashboard
- external source sweep status
- latest report/proposal artifacts

It writes:

```bash
.hermes/reports/hermes-daily-summary-<timestamp>.md
```

## Daily Refresh

```bash
src/system/daily-refresh.sh
```

Daily refresh now runs:

1. OBLITERATUS update check
2. catalog validation
3. provider model sync
4. gateway watchdog
5. Continue config generation
6. external source sweep
7. daily summary
8. verification tests

The separation stays clean:

- installer sets up files and first-run state
- router chooses skills/models at runtime
- daily refresh validates and reports batch changes
