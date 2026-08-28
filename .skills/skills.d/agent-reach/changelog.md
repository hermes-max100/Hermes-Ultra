# Changelog

## 1.5.0-hermes.1

- Hardened Agent Reach as a public read/collect-only runtime boundary.
- Removed implicit install, raw/mutating upstream CLI access, authenticated
  social/session paths, and broad GitHub CLI credential reuse.
- Added pinned/verified upstream source provisioning and isolated runtime home.
- Added SSRF-safe public fetch with DNS/redirect validation and bounded output.
- Pinned Exa to an import-free mcporter config with only `web_search_exa`.
- Added structurally untrusted output envelopes and a Hermes-owned doctor.
- Added clean-clone security regressions and immutable GitHub Actions pins.

## 1.5.0

- Promoted Agent Reach into Hermes runtime as an approval-gated internet
  collection skill.
