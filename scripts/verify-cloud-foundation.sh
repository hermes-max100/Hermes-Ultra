#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

require_file() {
  [[ -f "$ROOT_DIR/$1" ]] || fail "missing $1"
}

for file in \
  infra/aws-primary/main.tf \
  infra/aws-primary/variables.tf \
  infra/aws-primary/outputs.tf \
  infra/aws-primary/terraform.tfvars.example \
  infra/aws-primary/templates/bootstrap-hermes.sh.tftpl \
  config/production-versions.json \
  infra/google-support/main.tf \
  infra/google-support/variables.tf \
  infra/google-support/terraform.tfvars.example \
  scripts/build-cloud-release.sh \
  scripts/deploy-aws-primary.sh \
  docs/deployment/aws.md \
  docs/deployment/google-cloud.md \
  docs/deployment/architecture.md \
  docs/deployment/disaster-recovery.md \
  docs/deployment/cost-controls.md \
  docs/deployment/evidence-template.md
do
  require_file "$file"
done

bash "$ROOT_DIR/tests/test_production_versions.sh"

grep -R 'AdministratorAccess' "$ROOT_DIR/infra" "$ROOT_DIR/docs/deployment" >/dev/null \
  && fail "broad AdministratorAccess reference found"

grep -R 'from_port *= *22\|to_port *= *22\|cidr_blocks *=.*22' "$ROOT_DIR/infra" >/dev/null \
  && fail "SSH appears to be exposed"

grep -R -E '^[[:space:]]*enable_.*compute[[:space:]]*=[[:space:]]*true|^[[:space:]]*enable_cloud_run_probe[[:space:]]*=[[:space:]]*true' "$ROOT_DIR/infra" --include='*.tfvars.example' >/dev/null \
  && fail "example config enables compute by default"

grep -R 'block_public_policy *= *true' "$ROOT_DIR/infra/aws-primary" >/dev/null \
  || fail "AWS S3 public access block missing"

grep -R 'public_access_prevention *= *"enforced"' "$ROOT_DIR/infra/google-support" >/dev/null \
  || fail "Google storage public access prevention missing"

grep -R 'max_instance_count *= *1' "$ROOT_DIR/infra/google-support" >/dev/null \
  || fail "Cloud Run max instance bound missing"

grep -q 'http_tokens *= *"required"' "$ROOT_DIR/infra/aws-primary/main.tf" \
  || fail "EC2 IMDSv2 enforcement missing"

grep -q 'AmazonSSMManagedInstanceCore' "$ROOT_DIR/infra/aws-primary/main.tf" \
  || fail "SSM management policy missing"

grep -q 'release_sha256' "$ROOT_DIR/infra/aws-primary/main.tf" \
  || fail "checksummed release bootstrap missing"

grep -q 's3:GetObject' "$ROOT_DIR/infra/aws-primary/main.tf" \
  || fail "bounded artifact retrieval policy missing"

grep -q 'enable_storage must be true' "$ROOT_DIR/infra/aws-primary/main.tf" \
  || fail "compute/storage precondition missing"

bash -n "$ROOT_DIR/scripts/build-cloud-release.sh"
bash -n "$ROOT_DIR/scripts/deploy-aws-primary.sh"
# Terraform template contains Terraform interpolations; escape only intended shell interpolation then syntax-check.
sed \
  -e 's/${aws_region}/us-east-1/g' \
  -e 's/${artifact_bucket}/example-artifacts/g' \
  -e 's/${release_object_key}/releases\/example.tar.gz/g' \
  -e 's/${release_sha256}/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef/g' \
  -e 's/$${RELEASE_SHA256:0:16}/${RELEASE_SHA256:0:16}/g' \
  "$ROOT_DIR/infra/aws-primary/templates/bootstrap-hermes.sh.tftpl" | bash -n

if command -v terraform >/dev/null 2>&1; then
  (cd "$ROOT_DIR/infra/aws-primary" && terraform fmt -check -diff -recursive && terraform init -backend=false -input=false >/dev/null && terraform validate)
  (cd "$ROOT_DIR/infra/google-support" && terraform fmt -check -diff -recursive && terraform init -backend=false -input=false >/dev/null && terraform validate)
elif command -v tofu >/dev/null 2>&1; then
  (cd "$ROOT_DIR/infra/aws-primary" && tofu fmt -check -diff -recursive && tofu init -backend=false -input=false >/dev/null && tofu validate)
  (cd "$ROOT_DIR/infra/google-support" && tofu fmt -check -diff -recursive && tofu init -backend=false -input=false >/dev/null && tofu validate)
else
  printf 'WARN: terraform/tofu not installed; skipped provider-aware HCL validation.\n'
fi

printf 'PASS: Hermes Max cloud foundation static checks passed.\n'
