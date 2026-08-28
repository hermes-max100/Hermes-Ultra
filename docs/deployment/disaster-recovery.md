# Disaster Recovery

## Recovery model

Hermes cloud releases are immutable checksummed bundles stored in the private AWS
artifacts bucket. The active host uses `/opt/hermes-max/current` as an atomic
pointer to one extracted release directory.

Back up application state separately from release code.

## Backup scope

Back up:

- Hermes runtime configuration excluding raw secrets;
- Memory Fabric state snapshots;
- evidence ledger;
- Revenue OS state that is appropriate for backup;
- approved release artifacts and SHA256 files;
- recovery evidence.

Do not place plaintext secrets, browser cookies, provider API keys, SMTP
passwords, or private env files into S3/GCS logs or source control.

## Backup procedure

1. Stop mutating workloads or enter maintenance mode.
2. Export application state to an encrypted local staging path.
3. Hash the backup bundle.
4. Upload to the private `backups` bucket.
5. Record object id, digest, timestamp, classification, and restore notes.
6. Verify the uploaded object.
7. Securely delete local staging material.

## Release rollback

If a new release is bad but the host is healthy:

1. identify the prior verified directory under `/opt/hermes-max/releases/`;
2. atomically repoint `/opt/hermes-max/current` to that release;
3. run `scripts/verify-cloud-foundation.sh`;
4. restart only the affected runtime services;
5. record rollback evidence.

Do not delete the failed release until the incident is understood.

## Host-loss restore

1. Reapply `infra/aws-primary` from a trusted workstation.
2. Upload/select a previously verified release artifact.
3. Set its exact `release_object_key` and `release_sha256`.
4. Provision a replacement EC2 host.
5. Confirm bootstrap checksum/layout verification succeeds.
6. Restore the newest verified state backup.
7. Rotate runtime credentials.
8. Verify privileged operations fail closed.
9. Verify the authenticated gateway separately before routing clients.

## Credential rotation after incident

Rotate as applicable:

- model/provider keys;
- gateway signing material;
- device trust material;
- SMTP/outbound transport secrets;
- external connector credentials;
- any backup credentials not implemented as workload identity.

The EC2 host itself should use its IAM role rather than static AWS keys.

## Teardown

1. Export and verify any required final backup.
2. Disable public endpoints.
3. Destroy compute.
4. Remove storage only when evidence/backup retention permits it.
5. Keep budget alerts until all billable resources are confirmed gone.
6. Re-check provider billing dashboards after teardown.
