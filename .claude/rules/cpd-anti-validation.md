---
name: cpd-anti-validation
description: Fixed data and acceptance gates for additive cis-anti-I development
paths:
  - "experiments/cpd_anti_additive/**"
  - "docs/cpd_anti_additive_campaign.md"
  - "docs/cpd_validation_protocol.md"
---

Follow `docs/cpd_validation_protocol.md` and `validation_policy_v1.json` before
continuing this campaign. Do not launch another parameter fit merely because a
service completed. Reference acquisition/basin closure must pass and be frozen.
Existing inspected data are exposed; candidate registration precedes prospective
holdout acquisition. New fitting entry points must call `require_fit_ready()` and
use the frozen split and target identities. No bypass flags. Preserve failures,
no independent re-zeroing of MM/QM, no optimizer-completion minimum claims.
Protocol changes require an explicitly versioned rationale and retained verdicts.
Native acquisition and audits may continue while fitting is blocked. These fragment
gates do not authorize product geometry changes, full release or cloud spending.
