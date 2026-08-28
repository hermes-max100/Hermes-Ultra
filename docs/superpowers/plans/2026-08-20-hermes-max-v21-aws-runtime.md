# Hermes Max v2.1 AWS Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AWS production foundation exactly match the approved Hermes Max/JARVIS v2.1 runtime target and ship only immutable, verifiable releases.

**Architecture:** Terraform owns the bounded AWS foundation; cloud-init only installs host prerequisites and activates a checksummed release. The host uses Ubuntu 24.04, `m7i-flex.large`, encrypted gp3, IMDSv2, SSM, and no public Hermes/JARVIS ports. Release promotion is checksum-first and rollback-capable.

**Tech Stack:** Terraform/OpenTofu, AWS EC2/S3/Budgets/SSM, Bash, systemd, SHA-256, SPDX/CycloneDX-compatible SBOM tooling.

**Spec:** `docs/superpowers/specs/2026-08-20-hermes-max-jarvis-ultimate-production-design.md`

## Global Constraints

- AWS region is `us-east-1`.
- EC2 instance type is exactly `m7i-flex.large`; no silent family substitution.
- OS is Ubuntu Server 24.04 LTS amd64.
- Root disk is 30 GiB encrypted gp3 at 3,000 IOPS and 125 MiB/s.
- IMDSv2 is required and SSH ingress is absent.
- Monthly AWS budget target is USD 75.
- No permanent Elastic IP is required by the baseline.
- Public ports `4700`, `8642`, `9119`, `20127`, and `20128` must remain closed.
- Production releases must be immutable, checksummed, SBOM/provenance-recorded, and rollback-capable.

---
### Task 1: Lock AWS instance, OS, storage, and budget defaults

**Files:**
- Modify: `tests/test_cloud_foundation.sh`
- Modify: `infra/aws-primary/variables.tf`
- Modify: `infra/aws-primary/main.tf`
- Modify: `infra/aws-primary/terraform.tfvars.example`
- Modify: `infra/aws-primary/outputs.tf`

**Interfaces:**
- Consumes: existing `enable_storage`, `enable_ec2_compute`, release object key, and SHA256 inputs.
- Produces: Terraform defaults and resources matching the approved AWS runtime.

- [ ] **Step 1: Write failing assertions**

Add assertions to `tests/test_cloud_foundation.sh` for `m7i-flex.large`, Noble 24.04 AMI naming, `volume_size = 30`, `iops = 3000`, `throughput = 125`, budget default `75`, and absence of `aws_eip`/`aws_eip_association`.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `bash tests/test_cloud_foundation.sh`
Expected: FAIL because current Terraform still references `t3.small`, Jammy 22.04, and EIP resources.

- [ ] **Step 3: Implement the Terraform changes**

Set `ec2_instance_type` default to `m7i-flex.large`, `monthly_budget_limit_usd` to `75`, rename the AMI data source to `ubuntu_2404`, and match `ubuntu-noble-24.04-amd64-server-*`. In `root_block_device`, explicitly set `volume_size = var.ec2_root_volume_gib`, `volume_type = "gp3"`, `iops = 3000`, `throughput = 125`, and `encrypted = true`. Remove the EIP resources and replace `gateway_public_ip` with the instance public IP output when compute is enabled.

- [ ] **Step 4: Update example configuration and validate**

Set the example instance to `m7i-flex.large` and budget to `75`. Run `bash tests/test_cloud_foundation.sh` and `bash scripts/verify-cloud-foundation.sh`; both must pass.

- [ ] **Step 5: Commit**

Run: `git add tests/test_cloud_foundation.sh infra/aws-primary && git commit -m "feat: lock Hermes AWS production profile"`
### Task 2: Add immutable upstream/runtime version pins

**Files:**
- Create: `config/production-versions.json`
- Create: `tests/test_production_versions.sh`
- Modify: `scripts/verify-cloud-foundation.sh`
- Modify: `scripts/build-cloud-release.sh`

**Interfaces:**
- Consumes: approved version pins from the design spec.
- Produces: machine-readable production pins included in every release and validated before packaging.

- [ ] **Step 1: Write the failing version-pin test**

Create `tests/test_production_versions.sh` that parses `config/production-versions.json` with Python and asserts `hermes_agent.tag == "v2026.8.18"`, `hermes_agent.version == "0.20.4"`, `hermes_relay_android.tag == "android-v1.11.0"`, and `hermes_relay_android.version == "1.11.0"`.

- [ ] **Step 2: Run the test and confirm failure**

Run: `bash tests/test_production_versions.sh`
Expected: FAIL because the pin file does not exist.

- [ ] **Step 3: Add the pin file**

Create JSON with keys `schema_version`, `hermes_agent`, `hermes_relay_android`, and `frozen_at`, using the exact approved values and canonical release URLs from the spec.

- [ ] **Step 4: Enforce pins during verification and packaging**

Make `scripts/verify-cloud-foundation.sh` require and validate the JSON file. Make `scripts/build-cloud-release.sh` run `tests/test_production_versions.sh` before manifest generation so an invalid pin cannot ship.

- [ ] **Step 5: Run tests and commit**

Run `bash tests/test_production_versions.sh`, `bash scripts/verify-cloud-foundation.sh`, and `bash tests/test_cloud_foundation.sh`. Commit with `git add config/production-versions.json tests/test_production_versions.sh scripts && git commit -m "feat: pin production Hermes and Relay releases"`.

### Task 3: Add SBOM and provenance to release artifacts

**Files:**
- Modify: `scripts/build-cloud-release.sh`
- Create: `scripts/generate-release-provenance.sh`
- Create: `tests/test_release_supply_chain.sh`

**Interfaces:**
- Consumes: staged release tree and current Git commit.
- Produces: `SBOM.spdx.json`, `RELEASE_PROVENANCE.json`, `CLOUD_RELEASE_MANIFEST.sha256`.
- [ ] **Step 1: Write failing supply-chain assertions**

Create `tests/test_release_supply_chain.sh` to build into a temporary `HERMES_DIST_DIR`, extract the archive, and assert that `SBOM.spdx.json`, `RELEASE_PROVENANCE.json`, and the internal SHA256 manifest exist while `.env*`, `.git`, `.hermes`, Terraform state, and prospect data do not.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_release_supply_chain.sh`
Expected: FAIL because SBOM and provenance files are not generated yet.

- [ ] **Step 3: Implement provenance generation**

`generate-release-provenance.sh` must emit JSON containing source commit, source branch, build UTC timestamp, production pin file SHA256, builder hostname class (`local` only, not the literal hostname), and archive format version. It must not record usernames, home paths, tokens, or environment-variable values.

- [ ] **Step 4: Implement deterministic SBOM generation**

Generate SPDX JSON from the staged file inventory using Python when no external SBOM binary is installed: include package name `hermes-max`, release commit/version metadata, and SHA256 checksums for shipped files. Add both generated files before creating `CLOUD_RELEASE_MANIFEST.sha256`.

- [ ] **Step 5: Verify and commit**

Run `bash tests/test_release_supply_chain.sh` twice and compare archive content manifests for stable file membership. Run `bash tests/test_cloud_foundation.sh`. Commit with `git add scripts tests && git commit -m "feat: add release SBOM and provenance"`.

### Task 4: Harden AWS bootstrap and rollback activation

**Files:**
- Modify: `infra/aws-primary/templates/bootstrap-hermes.sh.tftpl`
- Create: `scripts/rollback-cloud-release.sh`
- Create: `tests/test_cloud_release_rollback.sh`

**Interfaces:**
- Consumes: `/opt/hermes-max/releases/<release-id>` and `/opt/hermes-max/current`.
- Produces: atomic activation plus a deterministic rollback command that never deletes durable state.

- [ ] **Step 1: Write rollback tests**

Use a temporary install root with two fake valid releases and assert that rollback switches `current` to the previous release, refuses an unknown release, and leaves a separate `state/` directory untouched.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_cloud_release_rollback.sh`
Expected: FAIL because the rollback command does not exist.

- [ ] **Step 3: Implement rollback and bootstrap hardening**

Add `rollback-cloud-release.sh --install-root PATH [--to RELEASE_ID]`; default to the newest release other than the current target, verify its internal manifest, then atomically replace the symlink. In bootstrap, retain at least the previous release and never `rm -rf` durable state.

- [ ] **Step 4: Validate and commit**

Run `bash tests/test_cloud_release_rollback.sh`, `bash tests/test_cloud_foundation.sh`, and `bash -n infra/aws-primary/templates/bootstrap-hermes.sh.tftpl` after applying the existing Terraform-variable substitution used by `verify-cloud-foundation.sh`. Commit with `git add infra scripts tests && git commit -m "feat: add atomic cloud rollback"`.
### Task 5: Add live AWS preflight and private Tailscale ingress preparation

**Files:**
- Create: `scripts/aws-production-preflight.sh`
- Create: `scripts/configure-tailscale-hermes.sh`
- Create: `tests/test_aws_production_preflight.sh`
- Modify: `docs/deployment/aws.md`

**Interfaces:**
- Consumes: authenticated AWS CLI for live preflight; an already enrolled Tailscale node for Serve configuration.
- Produces: machine-readable preflight output and a private `:9119` Tailscale Serve route without embedding enrollment secrets.

- [ ] **Step 1: Write offline tests with fixture command shims**

Create shell tests that place fake `aws` and `tailscale` commands first in `PATH`. Assert preflight rejects a non-`m7i-flex.large` response, accepts `2` vCPU/`8192` MiB, reports missing AWS credentials distinctly, and that Tailscale configuration refuses to run unless `tailscale status --json` shows the node is logged in.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_aws_production_preflight.sh`
Expected: FAIL because the scripts do not exist.

- [ ] **Step 3: Implement the preflight**

`aws-production-preflight.sh` must call `aws sts get-caller-identity`, `aws ec2 describe-instance-types --instance-types m7i-flex.large --region us-east-1`, and the AWS pricing/credit checks available to the authenticated account. It prints `AWS_AUTH`, `INSTANCE_LAUNCHABLE`, `VCPU`, `RAM_MIB`, and `REGION`; it exits nonzero on mismatch and never provisions resources.

- [ ] **Step 4: Implement Tailscale Serve configuration**

`configure-tailscale-hermes.sh` must require an already authenticated Tailscale daemon, then configure HTTPS/WSS Serve to proxy the local Hermes Dashboard/Gateway at `http://127.0.0.1:9119`. It must not call Funnel and must not accept an auth key argument.

- [ ] **Step 5: Verify and commit**

Run `bash tests/test_aws_production_preflight.sh`, `bash scripts/verify-cloud-foundation.sh`, and `git diff --check`. Commit with `git add scripts tests docs/deployment/aws.md && git commit -m "feat: add AWS and Tailscale production preflight"`.
### Task 6: Vendor and install the pinned Hermes Agent runtime

**Files:**
- Create: `scripts/stage-hermes-agent-source.sh`
- Create: `tests/test_stage_hermes_agent_source.sh`
- Modify: `scripts/build-cloud-release.sh`
- Modify: `infra/aws-primary/templates/bootstrap-hermes.sh.tftpl`

**Interfaces:**
- Consumes: a clean Hermes Agent source checkout resolving to approved release `v2026.8.18` / version `0.20.4`.
- Produces: `vendor/hermes-agent/0.20.4/` in a production release and an installed `/var/lib/hermes/.hermes/hermes-agent` runtime on AWS.

- [ ] **Step 1: Write failing staging tests**

Use a fake Git repository fixture. Assert staging refuses a dirty checkout, refuses a version not equal to `0.20.4`, excludes `.git`, venvs, auth files, logs, and caches, and records the source commit plus tree checksum in provenance.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_stage_hermes_agent_source.sh`
Expected: FAIL because the staging script does not exist.

- [ ] **Step 3: Implement source staging and host installation**

`stage-hermes-agent-source.sh SOURCE_DIR DEST_DIR` validates `hermes --version` metadata from the source tree, requires a clean worktree, archives only runtime source, and writes `SOURCE_COMMIT` plus manifest. In production build mode, require `HERMES_AGENT_SOURCE_DIR`; bootstrap installs from the staged source using its bundled setup path rather than `hermes update` or a moving branch.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_stage_hermes_agent_source.sh`, `bash tests/test_release_supply_chain.sh`, and `bash tests/test_cloud_foundation.sh`. Commit with `git add scripts tests infra/aws-primary/templates/bootstrap-hermes.sh.tftpl && git commit -m "feat: vendor pinned Hermes runtime"`.
### Task 7: Add secret-safe AWS runtime delivery

**Files:**
- Create: `src/system/load-aws-runtime-secrets.sh`
- Create: `tests/test_aws_runtime_secrets.sh`
- Modify: `infra/aws-primary/main.tf`
- Modify: `infra/aws-primary/variables.tf`

**Interfaces:**
- Consumes: SSM Parameter Store SecureString values under `/hermes-max/runtime/` using the EC2 instance role.
- Produces: `/var/lib/hermes/.config/hermes/runtime.env` with mode `0600`; no secret values enter Terraform state.

- [ ] **Step 1: Write failing tests with an AWS CLI shim**

Assert only allowlisted parameter suffixes become environment keys, output never includes values, destination mode is `600`, unknown keys fail closed, and a world-readable destination is corrected before use.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_aws_runtime_secrets.sh`
Expected: FAIL because the loader does not exist.

- [ ] **Step 3: Implement loader and least-privilege IAM**

Allowlist only approved API fallback keys such as `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `VENICE_API_KEY`, and explicitly enabled Google/API provider keys. Add `ssm:GetParameter`, `ssm:GetParameters`, and `ssm:GetParametersByPath` only for the configured `/hermes-max/runtime/*` ARN. Do not create secret parameter values in Terraform.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_aws_runtime_secrets.sh`, `bash tests/test_cloud_foundation.sh`, and `bash scripts/verify-cloud-foundation.sh`. Commit with `git add src/system/load-aws-runtime-secrets.sh tests/test_aws_runtime_secrets.sh infra/aws-primary && git commit -m "feat: add secret-safe AWS runtime delivery"`.
### Task 8: Add release/log secret scanning

**Files:**
- Create: `scripts/secret-scan-production.sh`
- Create: `tests/test_secret_scan_production.sh`
- Modify: `scripts/build-cloud-release.sh`

**Interfaces:**
- Consumes: repository/release/log paths supplied explicitly.
- Produces: redacted `SECRET_SCAN=PASS|FAIL` without echoing matched secret values.

- [ ] **Step 1: Write failing scanner tests**

Create fixtures containing fake API keys, bearer headers, cookie names, OAuth refresh-token fields, safe placeholders, and documentation examples. Assert real-looking test secrets fail, placeholders are allowlisted narrowly, and output reports file plus detector class without printing the secret.

- [ ] **Step 2: Run and confirm failure**

Run: `bash tests/test_secret_scan_production.sh`
Expected: FAIL because the scanner does not exist.

- [ ] **Step 3: Implement scanner and build gate**

Scan tracked source, staged release content, and selected runtime logs for token/cookie/API-key patterns plus forbidden browser-session credential names. Make production release packaging stop on scan failure before generating the final archive.

- [ ] **Step 4: Verify and commit**

Run `bash tests/test_secret_scan_production.sh`, `bash tests/test_release_supply_chain.sh`, and `git diff --check`. Commit with `git add scripts tests && git commit -m "feat: add production secret scan gate"`.
