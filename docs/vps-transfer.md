# Hermes Max VPS Transfer

This bundle is for moving the Hermes Agent plus self-evolving JARVIS workspace
to a VPS without copying local secrets or phone-only runtime debris.

## Included

- `.agents/skills/` project-agent skills
- `.skills/` Hermes runtime skill registry
- `.skill-sources/` downloaded skill source receipts and reference repos
- `src/system/` driver scripts, routers, model tools, sweep tools, and bridges
- `bridge/`, `gateways/`, `config/`, `profiles/`, `packs/`, `promptfoo/`,
  `tests/`, `scripts/`, `docs/`, and `agents/`
- safe `.hermes` subtrees needed for policy, bundles, and transfer receipts
- Agent Reach runtime skill and `src/system/agent-reach.sh` Linux driver
- `OBLITERATUS/` source, docs, tests, and examples without local venv, caches,
  checkpoints, or model weights

## Excluded

- `.env*` files and provider key files
- log files, pid files, screenshots, base64 screen captures, and install logs
- virtual environments, Python caches, pytest caches, node modules, and dist
  outputs
- git internals from nested downloaded repositories
- model weights and checkpoints
- APK, wheel, zip, pdf, and other bulky binary artifacts unless explicitly
  re-downloaded by a setup script

## Create The Bundle

```bash
scripts/export-vps-transfer.sh
```

The script writes:

- `dist/hermes-max-vps-transfer-<timestamp>.tar.gz`
- `dist/hermes-max-vps-transfer-<timestamp>.tar.gz.sha256`
- `.hermes/transfer/vps-transfer-manifest-<timestamp>.txt`

## Restore On A VPS

On the VPS:

```bash
sudo apt update
sudo apt install -y bash coreutils tar gzip findutils python3 python3-venv python3-pip git curl jq ripgrep tmux
mkdir -p ~/hermes-max
tar -xzf hermes-max-vps-transfer-*.tar.gz -C ~/hermes-max
cd ~/hermes-max
bash scripts/restore-vps-transfer.sh --verify-only
```

Then create your local env file from the template:

```bash
cp config/cloud-models.env.example .env.cloud-models.local
chmod 600 .env.cloud-models.local
$EDITOR .env.cloud-models.local
source .env.cloud-models.local
```

Run the full restore:

```bash
bash scripts/restore-vps-transfer.sh
```

Check Agent Reach after restore:

```bash
src/system/agent-reach.sh status
src/system/agent-reach.sh doctor
```

## VPS Notes

- Android Accessibility, Shizuku, Usage Access, Notification Access, and app UI
  control remain phone-side capabilities. On the VPS, Hermes can keep the
  routing, skills, JARVIS, sweeps, evals, and model gateways. Phone control
  still needs a phone bridge endpoint.
- Do not copy secrets into the archive. Re-supply keys on the VPS through
  `.env.cloud-models.local`, a systemd environment file, or the VPS secret
  manager.
- Keep JARVIS approval gates enabled for send/post/delete/install/security
  actions after the move.
