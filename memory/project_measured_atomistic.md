---
name: measured-atomistic
description: "MD-measured all-atom nucleotide templates: every heavy atom of BOTH strands measured in one base-pair frame from free NAMD, 21 bp averaged, replacing the 1ZEW templates behind Help ▸ New Positioning. FORWARD and REVERSE measured separately — the pseudo-dyad is a result, not an input."
metadata:
  node_type: memory
  type: project
---

# The atomistic templates are measured now, not derived

**Status: NATIVE (2026-08-06).** `build_atomistic_model(measured_positioning=True)` is the DEFAULT,
so the measured templates are what NADOC draws **and** what it exports to every simulation
(verified: an exported PDB matches the native build to 5e-5 nm and differs from legacy by up to
0.38 nm). `Help ▸ New Positioning` is now default-ON and turning it OFF is a *comparison
affordance* that returns the 1ZEW geometry. Companion to [[project_extra_base_spacing]] and the CG
half in `backend/core/measured_positioning.py`.

**The CG bead layer is NOT native** — `nucleotide_geometry(measured_positioning=...)` still
defaults False, and the app states the flag explicitly on both endpoints rather than relying on
either default. Flipping the CG default was tried and reverted: the other CG position paths
(oxDNA seeding, `positions_for_design`, linker relax, extension tail beads) do not share
`apply_measured_positioning`, so the default flip put them out of register with each other.
Making CG native means threading the measured placement through those paths — a separate job.

## What changed

The 1ZEW-derived templates in `atomistic.py` are wrong internally — P, C1' and the base-ring
centroid each miss free-MD by a different amount, so no rigid move or affine map lands all three
(that audit is in `measured_positioning.py`, which now points here). The templates were therefore
**re-extracted from simulation** rather than corrected.

| | legacy (1ZEW) | measured |
|---|---|---|
| frame per nucleotide | own strand's, z-mirrored between strands | ONE base-pair frame shared by both |
| REVERSE templates | z-mirror of FORWARD (`_DT_BASE_REV` …) | independently measured |
| cross-strand fix | +58.2°/−1.8° applied to the frame ORIGIN | none needed — nothing to correct |
| C1'–C1' realised | **0.967 nm** | **1.035–1.051 nm** |
| r_P | 0.886 | 0.904–0.922 |
| r_C1' | 0.493 | 0.564–0.591 (purines > pyrimidines — a real per-base difference) |

## How it is measured — `scripts/measure_atomistic_template.py`

Frame, built from the duplex itself: origin = local helix-axis point nearest the bp;
`e_x` = radial to the FORWARD phosphorus (azimuth 0); `e_z` = axis along FORWARD 5'→3'.
Axis fitted as the cylinder the **phosphates** lie on (midpoint fits wander and drive the
cross-strand azimuth spuriously toward 180° — established in `measure_cg_registration.py`).

Three things that are load-bearing and were each learned the hard way:

1. **Rigid-GROUP averaging, not whole-nucleotide.** A Kabsch mean over a flexible molecule still
   collapses soft torsions: P–OP1 came out **0.124 nm** against a real 0.148. Averaging the
   phosphate / sugar / base groups' shape and pose separately fixes it (≤ 0.006 nm bond error).
   The two bonds JOINING groups are then restored by sliding the dependent group to the
   trajectory's own mean length.
2. **Centre the mean shape before placing it.** Averaging rotations shrinks a vector while the
   projected mean rotation preserves its length, so an off-centre shape leaks a spurious outward
   push — this inflated r_P from 0.93 to **1.06 nm** until fixed.
3. **Anchor the frame on the bp's C1'→C1' vector**, not on either strand's atom. Anchoring on the
   forward P (BI/BII swings it tens of degrees) inflated the partner strand's RMSF ~1.8×.
   Re-zeroed onto the forward P only at emit time.

Runs continue on **stacking**, not backbone: a nick does not break a duplex, and requiring an
unbroken phosphodiester on both strands gave **zero** qualifying spans in a 24hb.

## Provenance

Pooled from 5 free (`MGHH_only`) origami trajectories — `24hb_{0,1,2}xT`, `6hbx100_noT`, `18hb` —
**53,088 bp**, 11.4k–14.6k conformers per (strand, base) bucket, 21 bp spans (2 helical turns, so
the average is span-invariant: between-span RMS 0.063–0.069 nm, SEM ~3 pm). Cross-system RMS
0.021–0.061 nm. Data + full report: `backend/core/data/measured_atomistic_template.json`.

**Emergent checks** (nothing was told to reproduce these): WC N–N 0.272–0.278 nm, C1'–C1'
1.035–1.051 nm, ring planarity ≤ 1.4 pm, glycosidic 0.146–0.148 nm, stereocentre signed volumes
identical in sign across all 8 buckets.

**The pseudo-dyad is a RESULT.** FORWARD and REVERSE come from disjoint samples (the measurement
alternates which strand it calls FORWARD span by span), yet the optimal proper rotation between
them is **179.84–179.98°** about an axis **0.0–0.32°** off perpendicular, with shapes agreeing to
**0.3–1.6 pm**. The symmetry is real — it is now evidence rather than an assumption.

## ⚠ The one provisional number

The **cross-strand azimuth** (~183° instantaneous, ~179.5° through the rigid-body average) is
seed-susceptible: every trajectory in this repo started at 183.84°, and this agrees with the
independent 20 bp duplex measurement (183.9°) but NOT the 1ZEW crystal (208.5°). Radii, internal
shape and axial placement all relaxed demonstrably away from the seed; this DOF is slow and soft.
Settling it needs `experiments/exp52_groove_seed_sweep` (4 arms seeded at 150/184/208/232°) —
**its jobs are not on this machine**; `runs.json` has job ids but no job dirs exist locally.

## How it reaches every path — the legacy-frame conversion

The measured templates are stored in the base-pair frame, but they are *served* to the build in the
**legacy `_atom_frame` local convention** (`measured_atomistic.legacy_local_templates()`, used via
`atomistic._native_local_defs`). That works because the legacy frame is a fixed rigid transform of
the base-pair frame — and, verified exactly, **independent of lattice cell type** (the ±150° groove
placement and the +58.2°/−1.8° correction land on the same frame to 2e-16). Round-trip against a
direct base-pair-frame stamp: **5.7e-16 nm**.

Consequence: every path that already builds a frame and stamps a fixed template becomes native by
swapping numbers, with **no frame changes** — the duplex loop, the surface point cloud
(`_surface_stamp_templates`), the fast client-side stamp descriptor (`_template_local_map`), and
the oxDNA rigid-frame calibration (`_rigid_frame_calibration._local`, which MUST match what the
build stamps or the placer stops reproducing the design build).

Note this also means the legacy layout's single shared `_SUGAR` cannot be reused: converted into
the same frame, the forward and reverse sugars sit **333–371 pm apart** (max 635 pm). That gap is
the legacy z-mirror construction, not a real strand difference — the strands agree with the dyad to
0.3–1.6 pm — but it is why the templates are per (direction, residue).

## Scope / what is NOT covered

**Extra crossover bases and strand-extension tails deliberately keep the 1ZEW templates.** Their
placers are calibrated against that template's local origin: insert atoms must sit on the CG chord
(an extra base's position is a READ of the CG representation), and the tail linker geometry is
fitted the same way. Swapping the template under them moved the insert origin **0.41 nm** off the
chord and stretched a tail backbone bond to **3.5 Å** (limit 3.2). Making them native = re-deriving
both placers. Their positions still follow the CG layer and their junction linkers are minimised,
so they join measured duplex.

Crossover junction nucleotides are relocated by the bridging pass after stamping (≈4 of 252 bp on
`6hb_test`), which is why `tests/test_measured_atomistic.py` asserts ≥95 % exact rather than 100 %.

## Wiring

`build_atomistic_model()` (default) → `GET /api/design/atomistic` (defaults true) →
`atom_surface_display._atomisticUrl()` appends `geometryQuerySuffix`, which now always states the
mode explicitly because the two endpoints it feeds do **not** default alike. The Help handler
invalidates the atom cache + refetches. `atomistic_cache` keys on the mode, or a legacy build
would be served for a native request.

## Tests that pin this

`tests/test_measured_atomistic.py` (45): bond lengths, chirality signs, planarity, emergent WC,
the dyad as a fitted result, the native default, cell-type independence of the legacy frame, and
the legacy-local conversion. `tests/test_atomistic_geometry_lock.py` goldens were regenerated —
approved change, `_PHASE_*` untouched.
