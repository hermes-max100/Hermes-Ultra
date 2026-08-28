# AWS Primary Deployment

Hermes Max uses AWS as its primary production cloud. The initial production host is an `m7i-flex.large` EC2 instance managed through AWS Systems Manager Session Manager; there is intentionally no SSH ingress.

## Foundation

The deployment can create:

- monthly AWS Budget alerts;
- three private, encrypted, versioned S3 buckets for evidence, artifacts, and backups;
- a least-privilege EC2 instance role;
- SSM Session Manager access;
- an encrypted gp3 EC2 host with IMDSv2 required;
- no permanent Elastic IP; the baseline uses the instance public IP only when compute is enabled;
- a checksummed cloud-init bootstrap from the private artifacts bucket.

## Safe rollout

Validate first:

```bash
bash scripts/verify-cloud-foundation.sh
bash tests/test_cloud_foundation.sh
scripts/deploy-aws-primary.sh validate
```

### Stage 1 — budget only

Copy `infra/aws-primary/terraform.tfvars.example` to `terraform.tfvars`. Keep `enable_storage=false` and `enable_ec2_compute=false`, inspect the plan, then apply only the budget guard. Record current promotional credit balance and expiration before enabling resources.

### Stage 2 — private storage

Set `enable_storage=true`, keep compute disabled, plan and apply. Retrieve the artifact bucket with `terraform output artifact_bucket`.

### Stage 3 — release and compute

Build a deterministic release:

```bash
scripts/build-cloud-release.sh
```

Upload it:

```bash
scripts/deploy-aws-primary.sh upload-release dist/hermes-max-cloud-*.tar.gz
```

Copy the printed `release_object_key` and `release_sha256` into `terraform.tfvars`, set `enable_ec2_compute=true`, and run `plan`. Inspect the plan and current AWS pricing before applying.

## Bootstrap guarantee

The host downloads exactly one release, verifies its SHA256 and internal manifest, installs it under `/opt/hermes-max/releases/<digest>`, atomically switches `/opt/hermes-max/current`, runs the existing restore checks, and enables a foundation-verification systemd service. A release that fails verification does not become current.

Runtime secret files are deliberately excluded from release bundles. Load them separately through the guarded Hermes runtime env path or an approved secret-delivery mechanism.

## Security

- No TCP/22 rule is provisioned.
- No application ingress is required by the private Tailscale baseline.
- TCP/443 and TCP/80 remain optional and disabled unless explicitly allowlisted.
- EC2 uses an instance role rather than static AWS credentials.
- S3 public access is blocked and versioning is enabled.
- Application/runtime secrets and prospect data are excluded from cloud releases.

Before any live provisioning, run the read-only production preflight:

```bash
bash scripts/aws-production-preflight.sh
```

For the private mobile path, enroll the host in Tailscale separately, then configure Hermes Serve only after `tailscale status --json` reports the node online:

```bash
bash scripts/configure-tailscale-hermes.sh
```

This proxies the localhost-only Hermes gateway at `http://127.0.0.1:9119` to the tailnet over HTTPS/WSS without adding public security-group ingress.
