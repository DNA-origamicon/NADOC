# Sim-coverage loop — metrics + cross-engine agreement

Companion to [`SIM_COVERAGE_PLAN.md`](SIM_COVERAGE_PLAN.md). Two things live here: (1) a per-task metrics row
with the anti-shovel justification, and (2) the headline deliverable — the **cross-engine agreement table** that
fills in as milestones complete.

## Per-task metrics rows (one per shipped task)

> *Format: **`<TASK-ID>` — `<title>`** · shape (service / card / solver-change) · feature covered · engines now
> comparable · oracle shipped (fast/slow) · main.js LOC Δ · tests (pass count) ·
> **"Comparable prediction gained, not just a run: ___."**_

- **`S1` — engine-agnostic shape descriptors** · shape: new `backend/core` service (`shape_metrics.py`) +
  1 additive `oxdna_health` helper (no solver/card change) · feature: comparison-metric (the shared substrate) ·
  engines now comparable: *all four* can be fed the same descriptor set (the yardstick; actual comparison lands
  at S3) · oracle: `tests/test_shape_metrics.py` 9 tests **fast** (recover twist/arc-span, can-go-red) ·
  main.js LOC Δ = 0 · tests: 9/9 oracle, `just test-fast` 4057 passed (1 pre-existing xdist flake) ·
  **Comparable prediction gained, not just a run:** every engine's frame now maps to identical twist /
  bend-angle+radius / Rg / end-to-end numbers on the shared `(helix,bp,dir,copy)` substrate, so S3 can score
  agreement instead of comparing incommensurable per-engine metrics.

- **`S2` — unified deviation + RMSF profiles** · shape: 3 functions added to the `shape_metrics.py` service
  (no solver/card change) generalizing `cando_deviation.compute_deviation`, `oxdna_health.production_rmsf`'s
  variance core, and `fem_solver.normalize_rmsf` · feature: comparison-metric (the second shared substrate) ·
  engines now comparable: *all four* can be scored on identical per-nt deviation-from-design (+RMSD) and per-nt
  RMSF (CanDo via NMA, others via `rmsf_from_ensemble`) · oracle: `tests/test_shape_deviation_rmsf.py` 10 tests
  **fast** (rmsd 0 identical, exact non-rigid displacement recovery, Kabsch pose-removal, `A/√2` fluctuation
  round-trip, normalize round-trip) · main.js LOC Δ = 0 · tests: 10/10 oracle, `just test` 4128 passed / 66
  skipped / 1 xfailed (full suite, no drop) ·
  **Comparable prediction gained, not just a run:** any engine's frame(s) now yield the SAME per-nucleotide
  deviation (Kabsch-aligned, so pose is stripped and only real shape mismatch survives) and the SAME per-nt RMSF
  on the shared substrate — the two flexibility/shape yardsticks S3's `compare_descriptors` needs to report a
  Pearson r / signed Δ between two engines instead of comparing incommensurable per-engine numbers.

- **`S3` — cross-engine descriptor agreement** · shape: 2 entry points added to the `shape_metrics.py` service
  (`compare_descriptors` + `reference_for`; no solver/card change) composing S1's descriptors + S2's profiles ·
  feature: comparison-metric (the agreement math itself) · engines now comparable: any two engines yield a
  scored comparison — signed %Δ per shape descriptor, Pearson/Spearman on per-bp RMSF, Kabsch-aligned shape
  RMSD — with the reference picked per-observable by policy (oxDNA=shape/field, CanDo=RMSF, NAMD-override) ·
  oracle: `tests/test_shape_compare.py` 13 tests **fast** (identical→perfect, ±10° twist→±10% signed,
  scaled/reversed/constant RMSF correlation, rigid-pose-invariant shape RMSD, `reference_for` policy + override +
  missing→None, **CanDo dir-less vs oxDNA per-strand RMSF collapses to per-bp & correlates** — the review-caught
  fix) · main.js LOC Δ = 0 · tests: 13/13 oracle (32/32 S1+S2+S3), `just test` 4140 passed / 66 skipped /
  1 xfailed (1 pre-existing xdist flake, passes in isolation) ·
  **Comparable prediction gained, not just a run:** the loop's first cross-*validation* number — two engines'
  frames now reduce to an agreement score (%Δ, Pearson r, aligned RMSD) with a policy-chosen reference, so the
  question "do the quick and rigorous engines agree, and where do they diverge?" becomes computable the moment
  S5 wires it into the generate/view/export card.

## Cross-engine agreement table (the deliverable)

Fills in as `compare_descriptors` (S3) + the card (S5) land and each engine emits descriptors. Per design ×
observable, record the reference engine and each candidate engine's agreement. This is what answers *"do the
quick and rigorous engines agree, and where do they diverge?"*

| Design (fixture) | Observable | Reference | CanDo | mrDNA | oxDNA | NAMD | Notes |
|---|---|---|---|---|---|---|---|
| _e.g. 6hb_curved_ | global twist | oxDNA | — | — | ref | — | pending S1–S5 |
| _e.g. 6hb_curved_ | bend angle / radius | oxDNA | — | — | ref | — | pending |
| _e.g. hinge fixture_ | RMSF profile (Pearson r) | CanDo | ref | — | — | — | pending |
| _e.g. tethered-arm_ | field deflection (cosine, mag ratio) | oxDNA | — | — | ref | — | **M-CANDO-FIELD headline** |

_Reference cells = `ref`; candidate cells = the agreement score (%-delta / Pearson r / cosine+ratio); `—` = not
yet emitted. Export each row's underlying data + PNG from the comparison card (per the generate/view/export
requirement)._

## Milestone status (derived from the JSON)

| Milestone | Meaning | Status |
|---|---|---|
| `M-METRIC-CORE` | comparison card generates/views/exports shared descriptors + agreement | pending (S1–S3 done; S4, S5 remain) |
| `M-CANDO-FIELD` | CanDo FEM field deflection cross-validates oxDNA within tol | pending (C1,C2,S4,S5,O1) |
| `M-CANDO-COMPLETE` | CanDo covers all four features + feeds the card | pending (C1–C5) |
| `M-ALL-ANCHORS-FIELD` | every engine runs an anchored field job with a comparable descriptor | pending |
| `M-FULL-COVERAGE` | all engines × all four features, all feeding the card | pending |

## Data summaries (plots + fits)

_(none yet — `### <TASK-ID> — <topic>` subsections for numeric fits, e.g. CanDo-vs-oxDNA deflection-vs-field
magnitude, as slow real-engine runs produce them.)_
