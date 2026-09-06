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

The host downloads exactly one release, verifies its SHA256 and internal manifest before executing release code, joins the private tailnet, installs Orca, and delegates activation to the transactional local installer. That installer creates versioned Hermes and release roots, atomically switches the active links, activates Relay, and verifies all three services. A release that fails any integrity or health check does not become current.

Runtime secret files are deliberately excluded from release bundles. Store provider keys and a reusable, scoped `TAILSCALE_AUTH_KEY` as SecureString parameters under `/hermes-max/runtime/`. First boot loads them through the instance role; the Tailscale key is consumed and removed from the persisted runtime environment before Hermes starts.

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

For a manual or recovery install, enroll the host in Tailscale and configure Hermes Serve only after `tailscale status --json` reports the node online:

```bash
bash scripts/configure-tailscale-hermes.sh
```

The production bootstrap performs this sequence automatically. It proxies the localhost-only Hermes gateway at `http://127.0.0.1:9119` to the tailnet over HTTPS/WSS without adding public security-group ingress.

## Tailscale production deployment

Routine releases deploy through the private tailnet, not the EC2 public address.
The manual `tailscale-production-deploy` GitHub workflow builds the pinned release,
joins the tailnet as an ephemeral `tag:hermes-ci` node, verifies the production
peer, transfers the archive through Tailscale SSH, invokes the transactional
installer, and verifies Hermes, Relay, and Tailscale Serve before reporting success.

One-time tailnet setup:

1. Apply `config/tailscale-production-policy.json` in the Tailscale access-control
   editor, merging its tag owners, grants, and SSH rule with any existing policy.
2. Create an OAuth client with writable `auth_keys` scope restricted to
   `tag:hermes-ci`.
3. Store its values in the GitHub `production` environment as
   `TS_OAUTH_CLIENT_ID` and `TS_OAUTH_SECRET`; require a deployment reviewer.
4. Generate the server enrollment key for `tag:hermes-prod` and store it as the
   `/hermes-max/runtime/TAILSCALE_AUTH_KEY` SecureString before first boot.

The workflow is manual-only and serialized. It opens no AWS security-group port.
The server tag can receive only SSH from the ephemeral CI tag and private HTTPS
from tailnet members under the supplied policy.

An already authenticated operator workstation can deploy the same artifact with:

```bash
bash scripts/deploy-cloud-release-tailscale.sh \
  hermes-max dist-production/hermes-max-cloud-<build>.tar.gz ubuntu
```

The script rejects unverified archives, offline tailnets, unreachable peers,
failed health checks, and missing service receipts. Failed installation remains
subject to the existing transactional rollback behavior.
