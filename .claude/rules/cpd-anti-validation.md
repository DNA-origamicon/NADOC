---
name: cpd-anti-validation
description: Fixed data and acceptance gates for additive cis-anti-I development
paths:
  - "experiments/cpd_anti_additive/**"
  - "docs/cpd_anti_additive_campaign.md"
  - "docs/cpd_validation_protocol.md"
---

For the explicitly resumed preliminary campaign, follow
`docs/cpd_preliminary_protocol_v2.md` and `preliminary_policy_v2.json`.
V2 has independent, hash-locked stages and bounded fits; it does not pass v1,
release parameters, or permit normal product-geometry promotion. New v2 fits call
`require_fit_ready(stage=...)` and reserve a round through `begin_round`.
Do not mutate a stage lock or relabel exposed data as blind.

The registered shape-v2.2 successor follows `docs/cpd_anti_shape_fit_v2_r2.md` and
`shape_fit_protocol_v2.py`: original candidate remains locked, one exclusive
successor inherits the consumed round, all23 inspected cases are exposed, and
only round two may be reserved through the unchanged `begin_round` function.
Do not modify pinned worker/protocol sources during that active fit. No third
round or automatic continuation follows from termination.

The user selected Sella as the default for new molecular geometry optimization
on 2026-09-26 (America/Denver); see `memory/feedback_sella_default.md`. Use explicit
minimum mode and independent stationarity/chemistry checks. Keep frozen historical
plans and active acquisition inputs unchanged. This preference does not unlock
fitting after candidate registration or expand numerical acceptance limits.

Legacy v1 entry points still follow `docs/cpd_validation_protocol.md` and `validation_policy_v1.json` before
continuing this campaign. Do not launch another parameter fit merely because a
service completed. Reference acquisition/basin closure must pass and be frozen.
Existing inspected data are exposed; candidate registration precedes prospective
holdout acquisition. New fitting entry points must call `require_fit_ready()` and
use the frozen split and target identities. No bypass flags. Preserve failures,
no independent re-zeroing of MM/QM, no optimizer-completion minimum claims.
Protocol changes require an explicitly versioned rationale and retained verdicts.
Native acquisition and audits may continue while fitting is blocked. These fragment
gates do not authorize product geometry changes, full release or cloud spending.
