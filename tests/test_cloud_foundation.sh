#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT_DIR/scripts/verify-cloud-foundation.sh"

AWS="$ROOT_DIR/infra/aws-primary/main.tf"
VARS="$ROOT_DIR/infra/aws-primary/variables.tf"
BOOT="$ROOT_DIR/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl"
BUILD="$ROOT_DIR/scripts/build-cloud-release.sh"

! grep -Eq 'from_port *= *22|to_port *= *22' "$AWS"
grep -q 'http_tokens.*=.*"required"' "$AWS"
grep -q 'encrypted.*=.*true' "$AWS"
grep -q 'AmazonSSMManagedInstanceCore' "$AWS"
grep -q 's3:GetObject' "$AWS"
grep -q 'enable_ec2_compute' "$VARS"
grep -q 'default     = \[\]' "$VARS"
grep -q 'sha256sum -c' "$BOOT"
grep -q 'restore-vps-transfer.sh' "$BOOT"
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
  test_aws_runtime_secrets.sh \
  test_secret_scan_production.sh
do
  grep -q "$gate" "$WORKFLOW" || { echo "cloud CI missing gate: $gate" >&2; exit 1; }
done
for watched in \
  "scripts/**" \
  "tests/**" \
  "config/production-versions.json" \
  "src/system/load-aws-runtime-secrets.sh"
do
  grep -Fq -- "- '$watched'" "$WORKFLOW" || { echo "cloud CI missing path trigger: $watched" >&2; exit 1; }
done

echo 'cloud foundation tests passed'
