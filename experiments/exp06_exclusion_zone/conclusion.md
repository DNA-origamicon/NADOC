# Exp06 — Scaffold-Staple Exclusion Zone: PASS (vacuously)

## Result: PASS — 0 violations, but for a specific structural reason

## Finding
Zero scaffold crossovers exist in a fresh `make_bundle_design()` output because each helix
receives its own separate scaffold strand (no inter-helix scaffold routing). The 5 bp
exclusion zone from the caDNAno paper is only relevant when scaffold crossovers exist between
helix pairs — which happens only after the user manually routes scaffold crossovers.

The current code correctly excludes positions WHERE scaffold strands ARE (via `scaffold_positions`
set), which is the appropriate guard for the current workflow.

## Note on `find_staple_crossovers` counting
The function counts domain transitions, not physical crossovers. ONE physical crossover creates
TWO domain transitions (outer strand A→B and inner strand B→A), so each crossover appears
twice in the output. Pairs showing [10, 11] are ONE crossover at bp=10 — the `11` is the
transition in the companion strand (b_left ends at bp_b+1=11 for REVERSE).

## Actionable conclusion
No change required for the current workflow. If scaffold routing is added in future (allowing
users to place scaffold crossovers between helices), the exclusion zone filter should be
added to `compute_autostaple_plan` at that time. The framework for it already exists:
the `scaffold_positions` set can be extended to a `scaffold_crossover_pairs` dict.
