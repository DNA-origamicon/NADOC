---
name: project_corner_primitive
description: Headless mitred-corner primitive (build_corner) + phase-aware scaffold-length optimizer + the two-constraint principle; validated with the design-layer clash detector.
metadata: 
  node_type: memory
  type: project
  originSessionId: 2716c75a-b4c8-4c6c-9b45-def883afa1b3
---

# Headless mitred-corner primitive (shipped 2026-07-08)

`backend/api/headless_corner_build.py` — a design-automation primitive
(`/automate-feature` family) that builds a 90° corner from two planar SQUARE
sheets, folded at a mitred seam, entirely headless. Mirrors
`headless_hinge_build.py`; composes existing `headless_build` wrappers only (NO new
route, god-file LOC Δ = 0).

## Entry point
`build_corner(*, n_helices=6, base_length_bp=56, lattice=SQUARE, target_angle_deg=90,
optimize=True, window_bp=2, col_offset=None) -> Design` (returns a standalone copy).

Recipe (the clean version of what the reference `.nadoc` was hand-built as):
`create_bundle` two 1×N sheets (A cols 0..N-1, B cols offset..offset+N-1; each sheet =
its own cluster) → `resize_strand_end` trims each helix's FAR end into a ~45° staircase
miter (BOTH scaffold + staple by the same negative delta; far end = 3p if helix FORWARD
else 5p) → `transform_cluster(log=True)` folds sheet B 180° about the miter diagonal →
`force_ligate` the N cross-seam scaffold links. Result carries a full replayable feature
log (bundle-create → resize → **cluster_op** → forced-ligation).

`col_offset` MUST be ODD (each B helix gets OPPOSITE scaffold parity to its A mate — SQ
parity `(row+col)%2==0`→FORWARD — giving one free 3′ + one free 5′ per seam so every
forced ligation is legal). Default `_default_col_offset` = smallest odd ≥ n+3 (n=6 → 9,
matching the reference cols 0–5 ↔ 9–14).

## The two-constraint principle (the core)
A mitred helix length must satisfy TWO constraints; naive uniform stagger honours only #1:
1. **AXIAL (miter):** far end lands on the 45° plane. Ideal stagger = spacing/rise =
   2.25/0.334 ≈ **6.74 bp/helix** — non-integer, so integer stepping is never exact.
   `_ideal_lengths` = `base − round(i·6.74)`.
2. **ROTATIONAL (phase):** a forced ligation bonds the 3′ bead of one helix to the 5′ bead
   of its partner, each ~1 nm off-axis at azimuth `phase_offset + bp·33.75°`. ±1 bp swings
   the terminal bead 33.75° — from pointing away (bond ~1.3 nm, overstretched) to facing
   its partner (~0.3–0.5 nm). A_i and B_i must FACE each other → joint per-seam-pair search.

**Two optimizer stages (both default-on):**

**Stage 1 — LENGTHS (`optimize=True`):** per seam, search integer `(len_Ai, len_Bi)` in
`ideal ± window_bp` and pick the pair minimising the posed FL backbone stretch —
**user-chosen lexicographic objective (2026-07-08): min total stretch, tiebreak smaller
axial residual; ±2bp window is the hard axial bound.** Result (n=6): total posed FL
stretch **1.87 nm** (max 0.69) vs uniform baseline **5.51 nm** vs reference **3.43 nm**.

**Stage 2 — FOLD POSE (`optimize_fold=True`, user request 2026-07-08):** the clash lever.
Stage 1's tight tooth-mating PACKS the cross-sheet backbones, so the residual clashes are a
property of the FOLD, not the lengths (a pure translation trades clashes 1:1 for bond length
— it just slides the tradeoff). A small extra ROTATION of sheet B (a few °) about the fold
pivot + a small shift swings B's bulk off A while the seam beads stay mated → genuinely
lowers clashes. Co-optimizer = **stage A lengths → stage B fold (grid search min
`clash + 4·Σbond` s.t. every bond < `max_stretch_nm`=1.0 and angle within `angle_tol_deg`=5)
→ stage C re-optimize lengths under the tweaked fold.** Result (n=6): **genuine clashes
24→11, FL total 2.82 nm (max 0.72), angle 93°** — beats the hand-tuned reference on BOTH
axes (11 clashes / 3.43 nm / 0.94 max). `optimize_fold=False` keeps the tight-bonds-only
1.87 nm / 24-clash result.

The fold perturbation `(Rextra, off)` folds into ONE `transform_cluster` pose via
`_compose_fold` (rotation `Rextra·R0`, same pivot, translation `tr0+off`) — still a single
logged `cluster_op`. Fast (~5.5 s): the grid is analytic (path-B) AND pre-filters to B beads
within reach of A (only cross-sheet A–B pairs can clash under a rigid B pose; an A-bead
KD-tree is built once, transformed near-B beads queried against it, straight-close pairs
pre-excluded). `build_corner` args: `optimize`, `optimize_fold`, `window_bp`,
`max_stretch_nm`, `angle_tol_deg`.

## Optimizer is path-B FAST (do NOT rebuild per candidate)
Straight backbone beads are **trim-invariant** — a bead at bp k does NOT move when the
helix is trimmed past k (verified, max move 0). So build the straight sheets ONCE
(`create_len = base + window` to cover the window), then per coordinate-descent pass
capture the fold transform from ONE real build and search all candidate lengths
ANALYTICALLY: `R@(bead − pivot) + pivot + trans` on the recorded straight beads reproduces
the geometry kernel's posed positions EXACTLY (diff 0). Re-fix the fold each pass →
converges in ~2 passes / ~5 builds / **1.3 s** (vs 451 builds / 59 s naive per-candidate).

## Validated with the clash detector (`backend/core/clash.py`)
Oracle `tests/automation_harness.py::assert_corner_folded` (7 clauses, all 3 layers): corner
angle ~90° (posed mean axes via `deformed_helix_axes`); N forced ligations; every posed FL
stretch < 1 nm; total ≤ uniform baseline (optimizer helped); genuine steric clashes ≤
baseline; a `cluster_op` log entry for the folded cluster; round-trip stable + all FL
records persist. Tests `tests/test_headless_corner_build.py` (13).

**KEY calibration insight (banked):** a GOOD forced ligation (~0.3 nm) is itself a sub-0.65
nm "clash" to `clash_report` — FL partners are ~20 nm apart STRAIGHT, so the detector's
straight-vs-posed exclusion does NOT drop them. Raw `clash_report.count` is therefore
ANTI-correlated with ligation quality. The corner metric MUST exclude the seam FL bonds:
`steric_clash_count(design)` = `clash_report` count minus the FL-partner pairs. This is what
the task's "ideally 0 after seam design" means. (Optimized has 1 MORE raw clash than uniform
but FEWER genuine ones: 24 vs 26.)

## Reproduction / calibration notes
- The reference `tests/fixtures/corner_miter_test.nadoc` (= `workspace/corner_miter_test.nadoc`)
  is the human-tuned target the clash detector was calibrated against (15 raw / 11 genuine
  clashes, 3.43 nm bonds). Its FOLD was hand-tuned in the gizmo (pivot z 12.58 vs the
  deterministic far-end-centroid 12.02). The DETERMINISTIC base fold (lengths-only) packs
  tighter (24 genuine clashes) BUT reproduces the task's stated uniform baseline 5.31 nm
  exactly. The **stage-2 fold optimizer** recovers a better fold pose programmatically →
  11 genuine clashes at 2.82 nm bonds, beating the hand-tuned reference on BOTH axes without
  any manual gizmo work.
- The reference feature-log is messy trial-and-error; the clean recipe is create→trim→fold→
  ligate. `create_bundle(ligate_adjacent=True)` does NOT merge adjacent scaffolds (24 strands);
  the 6 seam ligations merge them (→18).
- Seam ligation: the FORWARD helix's scaffold 3′ → the REVERSE helix's scaffold 5′, both at
  their trimmed far bp (= len−1).
- `target_angle_deg` only 90 supported (the 2.25/0.334 stagger geometry); a general angle would
  need a different miter stagger + fold rotation.

Related: [[project_clash_detector]] (the metric), [[project_headless_build]] (the wrappers it
composes: create_bundle / resize_strand_end / transform_cluster / force_ligate),
[[project_hinge_autoscaffold]], [[REFERENCE_SQUARE_LATTICE]].
