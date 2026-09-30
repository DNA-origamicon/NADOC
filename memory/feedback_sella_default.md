---
name: Sella is the default molecular geometry optimizer
type: feedback
authority: canonical
status: active
---

User instruction, 2026-09-26 America/Denver: make Sella the main solver from now
on and continue cis-anti toward scientific quality.

Use Sella by default for new QM and small-fragment MM geometry optimization in
the molecular parameterization workflow. Keep the electronic evaluator (currently
Psi4) and MD engine (NAMD) distinct. For minima use explicit `order=0`, internal
coordinates and the audited Cartesian projected-gradient/constraint/chemistry
checks. Pin the runtime and record numerical settings before a native attempt.

This preference changes future method selection, not frozen historical inputs,
acceptance criteria, budgets or verdicts. Preserve old geomeTRIC evidence. Do not
silently fall back to another optimizer or extend a failed attempt. A native
completion flag establishes neither a minimum nor scientific qualification.

The cis-anti default qualification scope remains the previously selected bounded
preliminary structural use unless the user explicitly expands it. No cloud
spending. See docs/cpd_anti_additive_campaign.md for current gates and live jobs.

User clarification, 2026-09-27: be cautious that a reported shape mismatch is not
an unfounded expectation inherited from earlier work; treat Sella as the preferred
method moving forward. Identify the actual QM coordinates, electronic model,
constraints, convergence evidence and reference provenance before interpreting a
shape residual. Do not impose a preferred visual shape, planar N1, or a previous
optimizer's geometry as physical truth. Existing RMSD cutoffs are local operational
tests, not experimentally established CPD shape tolerances. Preserve their
historical verdicts while distinguishing correspondence failure from demonstrated
physical error. Sella stationarity alone does not certify curvature or identify
the globally relevant conformer. Test bounded parameter response before declaring
the current functional form inadequate.
