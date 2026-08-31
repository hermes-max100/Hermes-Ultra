#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT_DIR/scripts/verify-cloud-foundation.sh"

AWS="$ROOT_DIR/infra/aws-primary/main.tf"
VARS="$ROOT_DIR/infra/aws-primary/variables.tf"
BOOT="$ROOT_DIR/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl"
BUILD="$ROOT_DIR/scripts/build-cloud-release.sh"
INSTALLER="$ROOT_DIR/scripts/install-cloud-release-local.sh"

! grep -Eq 'from_port *= *22|to_port *= *22' "$AWS"
grep -q 'http_tokens.*=.*"required"' "$AWS"
grep -q 'encrypted.*=.*true' "$AWS"
grep -q 'AmazonSSMManagedInstanceCore' "$AWS"
grep -q 's3:GetObject' "$AWS"
grep -q 'enable_ec2_compute' "$VARS"
grep -q 'default     = \[\]' "$VARS"
grep -q 'sha256sum -c' "$BOOT"
grep -q 'restore-vps-transfer.sh' "$BOOT"
grep -q 'vendor/hermes-agent/0.20.5' "$BOOT" || { echo 'bootstrap does not use pinned Hermes Agent 0.20.5' >&2; exit 1; }
grep -Eq 'nodejs.*npm|npm.*nodejs' "$BOOT" || { echo 'bootstrap does not provision Node/npm' >&2; exit 1; }
grep -q 'nginx-core' "$BOOT" || { echo 'bootstrap does not provision loopback reverse proxy' >&2; exit 1; }
grep -q 'ensure-node-runtime.sh' "$INSTALLER" || { echo 'local installer does not own Node runtime' >&2; exit 1; }
grep -q 'sync-mcp-provider-registry.sh' "$INSTALLER" || { echo 'local installer does not apply MCP registry' >&2; exit 1; }
grep -q 'configure-tailscale-hermes.sh' "$INSTALLER" || { echo 'local installer does not activate private Hermes/Orca runtime' >&2; exit 1; }
grep -q -- "--exclude='./.codex-project'" "$BUILD"
grep -q -- "--exclude='./.hermes'" "$BUILD"
grep -q -- "--exclude='./prospects.jsonl'" "$BUILD"
grep -Fq -- "--exclude='./infra/**/terraform.tfvars'" "$BUILD"

grep -q 'default     = "m7i-flex.large"' "$VARS"
grep -q 'default     = 75' "$VARS"
grep -q 'ubuntu-noble-24.04-amd64-server-' "$AWS"
grep -q 'volume_size *= *var.ec2_root_volume_gib' "$AWS"
grep -q 'iops *= *3000' "$AWS"
grep -q 'throughput *= *125' "$AWS"
! grep -q 'resource "aws_eip"' "$AWS"
! grep -q 'resource "aws_eip_association"' "$AWS"
grep -q 'aws_instance.hermes_gateway\[0\].public_ip' "$ROOT_DIR/infra/aws-primary/outputs.tf"
grep -q 'monthly_budget_limit_usd = 75' "$ROOT_DIR/infra/aws-primary/terraform.tfvars.example"
grep -q 'ec2_instance_type   = "m7i-flex.large"' "$ROOT_DIR/infra/aws-primary/terraform.tfvars.example"

WORKFLOW="$ROOT_DIR/.github/workflows/cloud-foundation-validate.yml"
for gate in \
  test_production_versions.sh \
  test_release_supply_chain.sh \
  test_cloud_release_rollback.sh \
  test_aws_production_preflight.sh \
  test_stage_hermes_agent_source.sh \
  test_export_hermes_dependency_locks.sh \
  test_install_cloud_release_local.sh \
  test_node_runtime_prerequisite.sh \
  test_install_orca_runtime.sh \
  test_aws_runtime_secrets.sh \
  test_secret_scan_production.sh
do
  grep -q "$gate" "$WORKFLOW" || { echo "cloud CI missing gate: $gate" >&2; exit 1; }
done
for watched in \
  "scripts/**" \
  "tests/**" \
  "config/production-versions.json" \
  "src/system/load-aws-runtime-secrets.sh" \
  "src/system/orca_execution_backend.py"
do
  grep -Fq -- "- '$watched'" "$WORKFLOW" || { echo "cloud CI missing path trigger: $watched" >&2; exit 1; }
done
grep -Fq -- "- main" "$WORKFLOW" || { echo 'cloud CI does not run on canonical main' >&2; exit 1; }
! grep -Fq -- "- ai/hermes-ultra-release" "$WORKFLOW" || { echo 'cloud CI still treats legacy release branch as canonical' >&2; exit 1; }

echo 'cloud foundation tests passed'
