---
name: CG pre-relax pipeline — lessons and pitfalls
description: Bugs, root causes, and validated fixes for the oxDNA→atomistic pipeline; critical for debugging new designs
type: feedback
originSessionId: c428e99e-8e62-49bc-9619-c9563281a0f3
---
## oxDNA segfault: zero-position overhang nucleotides

**Rule:** Always verify no nucleotides fall back to (0,0,0) before running oxDNA. If any backbone bonds have length ≈ 0, oxDNA will segfault with no useful error (just `Segmentation fault (core dumped)` after "N: XXXX, N molecules: YY").

**Why:** Domains in scadnano can extend beyond `helix.length_bp` (e.g., helix h_XY_0_3 has `length_bp=420` but a domain goes to bp=422). `nucleotide_positions(helix)` only generates positions for `range(length_bp)`, so bp 420–422 are absent from the geometry. Old fallback was `(0,0,0)` → backbone bond of 0 nm between adjacent nucleotides → cell list/energy computation segfault.

**How to apply:** `_compute_nuc_geometry()` in `oxdna_interface.py` now extrapolates along the helix axis for any bp outside the defined range. `write_configuration` calls it for every missing key. If debugging a new segfault on a new design, check for zero-position nucleotides first with: `any(all(x==0 for x in l.split()[:3]) for l in open('conf.dat').readlines()[3:])`.

---

## oxDNA box sizing: use backbone extents, not axis × 2

**Rule:** Box = `max(backbone_extents) + 20 nm`. The old formula `2 × helix_axis_extent + 10 nm` gave a 290 nm box for U6hb (140 nm helices), which caused a segfault because oxDNA's auto-optimized cell list can't handle boxes far larger than the structure density.

**Why:** The Cells auto-optimisation caps N_cells_side at `ceil(max_factor × box)` where `max_factor = (2N/V)^(1/3)`. For a 5036-nucleotide structure in a 290 nm box, this gave 22 cells, but the sparse box caused incorrect cell assignment for the structure's actual positions.

**How to apply:** Current code computes box from resolved backbone positions. If manually creating conf.dat, use structure extent + 20 nm (not × 2). For U6hb: extent ≈ 140 nm → box = 160 nm.

---

## oxDNA coordinates: do NOT center in box

**Rule:** Write backbone positions in their natural coordinate system (which may have negative Y values for some B-DNA helices near y=0). Do NOT translate to center in the box.

**Why:** oxDNA handles negative coordinates correctly via periodic boundary fractional arithmetic `pos/L - floor(pos/L)`. If you center the structure in the box (e.g., shift by +80 nm in x/y), the CG output positions will also be shifted by +80 nm. When `_refit_helix_axes` fits PCA axes to these shifted positions, the resulting new axis_start/axis_end will be 80 nm away from the original helix positions, making the refitted model useless.

**How to apply:** `write_configuration` does not apply any centering offset. The natural B-DNA coordinate system (x/y typically ±2 nm around helix axis, z from 0 to helix_length) is used directly.

---

## CG axis refitting: PCA over direct position override

**Rule:** Use per-helix PCA axis fitting (`_refit_helix_axes` in `cg_to_atomistic.py`), not direct backbone position override.

**Why:** oxDNA MC output has local positional noise (~0.3–0.5 nm per nucleotide). Directly using CG backbone positions for `_atom_frame()` in the atomistic builder causes adjacent templates to overlap when nucleotide z-ordering is swapped by thermal fluctuations, producing LJ energies of ~5×10^32 kJ/mol.

**How to apply:** PCA fits a smooth line through all CG backbone positions for each helix, then projects the original axis_start/axis_end onto this line. The atomistic model is rebuilt with ideal B-DNA geometry along the CG-fitted axes. Result: 0.05–0.10 nm axis shifts that capture crossover geometry correction without local noise.

---

## Per-helix PCA axis refitting does NOT reduce GROMACS EM steps

**Rule:** Don't use per-helix PCA axis fitting as the CG→atomistic bridge for GROMACS EM speedup. It produces no measurable improvement.

**Why:** PCA averages ALL backbone positions across the helix (420+ bp for U6hb). The resulting axis shift is 0.05–0.10 nm, which is a nearly-pure TRANSLATION of the whole helix. This does NOT change the RELATIVE positioning of adjacent helices at crossover junctions. The O5'/O1P atoms remain at ~0.05 nm, so initial LJ is still ~3×10¹³ kJ/mol and EM takes ~9,700 steps (same as ideal B-DNA).

**Validated on U6hb (2026-04-20):** CG path 9,656 steps, ideal 9,787 steps — 1.3% difference, within run-to-run noise.

**How to apply:** Phase 3b solution — per-helix CubicSpline through mrdna ARBD fine-stage bead
positions. The critical insight is that the mrdna fine stage has 1 DNA bead per BASE PAIR (not per
nucleotide), so per-STRAND splines fail. See `project_mrdna_bead_model.md` for the full explanation.

---

## mrdna fine-stage bead model: 1 DNA bead per bp, not per nucleotide

**Rule:** Do NOT attempt per-strand splines with mrdna ARBD fine-stage output. Do NOT assign
direction (FORWARD/REVERSE) to individual DNA beads. Use per-helix splines only.

**Why:** The mrdna fine stage has exactly 1 DNA bead per base pair (at FORWARD backbone position)
and 1 O bead (orientation indicator). For U6hb (5036 nt = 2518 bp): 2518 DNA beads, 2518 O beads.
There is NO separate bead for REVERSE strand backbone. Direction assignment by radial angle comparison
will misclassify ~50% of beads, producing duplicate positions and LJ overflow at EM step 0.

**Symptom of violation:** 75+ duplicate positions in override dict, LJ initial energy > 1e30 kJ/mol,
EM either crashes at step 0 or takes 0 steps with an extreme energy.

**How to apply:** In `nuc_pos_override_from_arbd_strands`, deduplicate to (h_id, bp_idx) — NO direction
key in the bead map. FORWARD positions come from the spline; REVERSE positions are reconstructed via
`_rotate(fwd_rad, axis_hat, BDNA_MINOR_GROOVE_ANGLE_RAD)`. Full detail in `project_mrdna_bead_model.md`.

**Validated result (U6hb, 2026-04-24):** 500 baseline steps → 14 Phase 3b steps (0.03× ratio, PASS).

---

## Skip-site sequence mapping applies to oxDNA topology too

**Rule:** The sequence offset bug (skip sites shift downstream sequence characters) applies identically to `write_topology` in `oxdna_interface.py`. Must use `_build_ls_lookup` to skip deleted bp positions when advancing the sequence index.

**Why:** The scadnano sequence string has no character for deleted bp positions (delta≤-1). Both `build_atomistic_model` and `write_topology` iterate over bp ranges including deleted positions; if the deleted positions are not skipped, all downstream characters are offset by one, giving garbage sequences. Fixed in both places via `_build_ls_lookup`.
