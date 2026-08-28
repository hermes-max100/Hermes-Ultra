# Workflow: Compliance Audit

> **SOP**: Regulatory compliance audit using HERMES.

## Overview

Audit documents, practices, or systems against applicable regulations.

## Supported Regulations

- **GDPR** — EU General Data Protection Regulation
- **CCPA** — California Consumer Privacy Act
- **HIPAA** — Health Insurance Portability and Accountability Act
- **SOX** — Sarbanes-Oxley Act
- **AML/KYC** — Anti-Money Laundering / Know Your Customer
- **PCI-DSS** — Payment Card Industry Data Security Standard

## Steps

### Step 1 — Scope Definition
- Identify applicable regulations
- Define audit boundaries (which systems, data, processes)
- Gather relevant documentation

### Step 2 — Run HERMES Compliance Check
```bash
simplellms --hermes compliance ./policy-document.md --jurisdiction EU
```

### Step 3 — Gap Analysis
- Review compliance gaps by priority
- Identify required remediations
- Estimate effort for each gap

### Step 4 — Remediation Plan
- Prioritize items (critical → high → medium → low)
- Assign owners and timelines
- Track in project management system

### Step 5 — Documentation
- Save compliance report to `./compliance/` with date stamp
- Maintain audit trail of remediations

## Output
- Compliance assessment report
- Remediation roadmap with priorities
- Risk classification summary
