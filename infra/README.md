# Hermes Max Cloud Infrastructure

This directory contains the conservative AWS primary foundation for Hermes Max.

The AWS foundation provides a monthly budget guard, private encrypted/versioned S3 storage, a least-privilege EC2 role, SSM management without SSH, IMDSv2 enforcement, encrypted gp3 storage, and a checksummed release bootstrap.

Compute is disabled by default. Promotional credits are not treated as permission to spend.

Validate before any apply:

```bash
bash scripts/verify-cloud-foundation.sh
bash tests/test_cloud_foundation.sh
scripts/deploy-aws-primary.sh validate
```

Roll out in stages: budget only, storage, then checksummed release plus compute.
