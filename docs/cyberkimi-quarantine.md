# CyberKimi Quarantine Setup

CyberKimi is wired into Hermes as an explicit, opt-in cyber-specialist route. It
is not a default model and should not receive autonomous tool authority.

## Configure

Copy the key template if needed:

```bash
src/system/cloud-model-picker.sh setup
```

Edit `.env.cloud-models.local` and set:

```bash
export ADVERSERIAL_API_KEY="..."
export ADVERSERIAL_BASE_URL="https://api.adverserial.ai/v1"
```

Do not commit or export `.env.cloud-models.local`.

## Select Manually

```bash
src/system/cloud-model-picker.sh select adverserial lordx64/cyberkimi
src/system/cloud-model-picker.sh receipt
```

## One-Off Route

```bash
HERMES_MODEL_KEY_OVERRIDE=cyberkimi-quarantine \
HERMES_PROVIDER_OVERRIDE=adverserial \
HERMES_MODEL_OVERRIDE=lordx64/cyberkimi \
src/system/dynamic-router.sh --json "review this owned service threat model" cyberkimi-quarantine
```

## Policy

CyberKimi may produce report artifacts for:

- defensive security review
- detection engineering
- incident response planning
- threat modeling
- patch diff analysis
- lab-only exploitability assessment

CyberKimi must not autonomously:

- run shell commands
- use network scanners
- scan public targets
- execute exploit modules
- create malware, phishing, stealth, persistence, or credential-theft tooling
- control Android apps
- send, post, delete, purchase, enter credentials, or change account settings

Any execution must become a human approval request first.
