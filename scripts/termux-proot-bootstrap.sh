#!/usr/bin/env bash
set -euo pipefail

cat <<'EOF'
Termux bootstrap for Hermes Max

Run these commands in Termux:

  pkg update && pkg upgrade -y
  pkg install -y proot-distro tar coreutils curl
  termux-setup-storage
  proot-distro install ubuntu
  proot-distro login ubuntu --shared-tmp

Then run these commands inside Ubuntu:

  apt update
  apt install -y python3 python3-venv python3-pip git build-essential curl ca-certificates
  mkdir -p /root/hermes-max
  tar -xzf /data/data/com.termux/files/home/storage/downloads/hermes-max-build-with-logs-*.tar.gz -C /root/hermes-max
  cd /root/hermes-max
  bash scripts/restore-hermes-build.sh
  src/system/obliteratus-runner.sh doctor
  src/system/obliteratus-runner.sh ui-start --port 7860

Open on Android:

  http://127.0.0.1:7860

Full guide:

  docs/termux-setup.md
EOF
