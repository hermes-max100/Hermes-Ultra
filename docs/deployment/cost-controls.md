# Cloud Cost Controls

Target recurring cloud infrastructure spend before model/API inference:

- preferred normal target: below `$25/month` when practical;
- working ceiling for the initial AWS + support-cloud footprint: `$40/month`;
- Terraform budget defaults: AWS `$25/month`, Google support `$15/month`.

These are budget alarms, not provider-enforced spending caps. Promotional credits
are not treated as free money. Inspect current provider pricing and credit
expiration before enabling compute.

## Cost-safe rollout

1. Apply budget resources only.
2. Verify alerts and current credit balances.
3. Enable private storage.
4. Build and upload one checksummed release.
5. Review current EC2 + EBS + public IPv4 pricing.
6. Enable one bounded EC2 host only after the plan is reviewed.
7. Keep Google support compute disabled until a concrete support workload exists.

## Prohibited initial spend

Do not buy or enable:

- Reserved Instances or Savings Plans;
- commitments;
- paid support plans;
- domains;
- NAT Gateways;
- GPUs;
- Kubernetes clusters;
- managed databases without demonstrated need;
- active-active multi-cloud replication.

## Operational controls

- Keep only one primary compute host initially.
- Keep Cloud Run support service at min 0/max 1.
- Use bounded log retention.
- Review `src/system/cost-audit.sh` output with cloud billing dashboards.
- Stop/destroy experimental resources that are not producing measurable value.
