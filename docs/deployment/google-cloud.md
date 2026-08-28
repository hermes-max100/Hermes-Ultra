# Google Cloud Support Deployment

Google Cloud is a support cloud for Hermes Max. It must not host a duplicate
Hermes Max Core.

Allowed uses:

- Gemini or Vertex integration.
- Bounded Cloud Run auxiliary workloads.
- Dev/test services.
- Future analytics or backup support if justified.

## Step 0: Cost Protection

Apply only the Google Cloud budget first:

```bash
cd infra/google-support
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
terraform init
terraform plan
terraform apply
```

Keep `enable_support_storage = false` and `enable_cloud_run_probe = false` for
the first apply. Record visible promotional credit balance and expiration from
the Google Cloud console before enabling APIs or services.

## Resources

The foundation can create:

- Google Cloud billing budget with current-spend thresholds at 50%, 80%, and
  100%.
- Google Cloud forecast thresholds at 80% and 100%.
- Optional private support storage bucket with public access prevention.
- Optional Cloud Run support probe with min instances 0 and max instances 1.

## Cloud Run Bounds

Any Cloud Run service must set:

- min instances: 0 unless always-on behavior is required.
- max instances: 1 initially.
- explicit CPU and memory limits.
- no public access unless the endpoint is intentionally client-facing.

## Verification

Before marking Google deployment complete:

```bash
gcloud billing budgets list --billing-account "$BILLING_ACCOUNT"
gcloud services list --enabled --project "$PROJECT_ID"
gcloud run services describe hermes-max-support-probe --region "$REGION" --project "$PROJECT_ID"
```

Confirm no duplicate Hermes Core service exists in Google Cloud.
