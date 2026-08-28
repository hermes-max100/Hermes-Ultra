#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
TYPE='m7i-flex.large'
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo 'AWS_AUTH=FAIL'
  echo "REGION=$REGION"
  exit 1
fi
echo 'AWS_AUTH=PASS'
RAW="$(aws ec2 describe-instance-types --instance-types "$TYPE" --region "$REGION" --output json)"
read -r FOUND VCPU RAM < <(python3 -c 'import json,sys; d=json.load(sys.stdin)["InstanceTypes"][0]; print(d["InstanceType"], d["VCpuInfo"]["DefaultVCpus"], d["MemoryInfo"]["SizeInMiB"])' <<<"$RAW")
echo "VCPU=$VCPU"
echo "RAM_MIB=$RAM"
echo "REGION=$REGION"
if [[ "$FOUND" != "$TYPE" || "$VCPU" != 2 || "$RAM" != 8192 ]]; then
  echo 'INSTANCE_LAUNCHABLE=FAIL'
  exit 1
fi
echo 'INSTANCE_LAUNCHABLE=PASS'
if aws pricing get-products --service-code AmazonEC2 --region us-east-1 --max-results 1 >/dev/null 2>&1; then echo 'PRICING_CHECK=PASS'; else echo 'PRICING_CHECK=UNAVAILABLE'; fi
if aws budgets describe-budgets --account-id "$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)" --region "$REGION" >/dev/null 2>&1; then echo 'BUDGET_CHECK=PASS'; else echo 'BUDGET_CHECK=UNAVAILABLE'; fi
echo 'CREDITS_CHECK=MANUAL'
