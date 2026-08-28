#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT_DIR/infra/aws-primary"
ACTION="${1:-help}"
shift || true

TF=""
if command -v tofu >/dev/null 2>&1; then TF=tofu; elif command -v terraform >/dev/null 2>&1; then TF=terraform; fi
need_tf() { [[ -n "$TF" ]] || { echo 'terraform or tofu is required' >&2; exit 2; }; }
need_aws() { command -v aws >/dev/null 2>&1 || { echo 'aws CLI is required' >&2; exit 2; }; }

case "$ACTION" in
  validate)
    need_tf
    cd "$TF_DIR"
    "$TF" init -backend=false
    "$TF" fmt -check -recursive
    "$TF" validate
    ;;
  budget-plan)
    need_tf
    cd "$TF_DIR"
    "$TF" init
    "$TF" plan -var='enable_storage=false' -var='enable_ec2_compute=false'
    ;;
  upload-release)
    need_aws; need_tf
    RELEASE="${1:?usage: deploy-aws-primary.sh upload-release RELEASE.tar.gz}"
    [[ -f "$RELEASE" ]] || { echo "release not found: $RELEASE" >&2; exit 2; }
    SHA="$(sha256sum "$RELEASE" | awk '{print $1}')"
    cd "$TF_DIR"
    BUCKET="$($TF output -raw artifact_bucket 2>/dev/null || true)"
    [[ -n "$BUCKET" && "$BUCKET" != "null" ]] || { echo 'artifact bucket unavailable; enable_storage and apply first' >&2; exit 2; }
    KEY="releases/$(basename "$RELEASE")"
    aws s3 cp "$RELEASE" "s3://$BUCKET/$KEY"
    printf 'release_object_key = "%s"\nrelease_sha256 = "%s"\n' "$KEY" "$SHA"
    ;;
  plan|apply|output|destroy)
    need_tf
    cd "$TF_DIR"
    "$TF" "$ACTION" "$@"
    ;;
  *)
    cat <<'HELP'
Usage:
  scripts/deploy-aws-primary.sh validate
  scripts/deploy-aws-primary.sh budget-plan
  scripts/deploy-aws-primary.sh upload-release dist/RELEASE.tar.gz
  scripts/deploy-aws-primary.sh plan
  scripts/deploy-aws-primary.sh apply
  scripts/deploy-aws-primary.sh output
  scripts/deploy-aws-primary.sh destroy

Safe rollout:
  1. Apply budget only.
  2. Enable storage and apply.
  3. Build + upload a checksummed release.
  4. Set release_object_key/release_sha256 and enable_ec2_compute=true.
  5. Plan, inspect cost, then apply.
HELP
    ;;
esac
