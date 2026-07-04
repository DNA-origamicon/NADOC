# Bend-gap diagnosis — CanDo results (2026-07-03)

> ## ⚠ CORRECTION (2026-07-03, later) — the "0.68 bend gap" was a MEASUREMENT ARTIFACT
> The FEM/CanDo ratios first reported here (~0.68) compared the FEM measured with an
> **end-tangent** estimator against CanDo measured with **arc-span**. The end-tangent reads
> LOW on real FEM arcs (the ends straighten under the boundary conditions): design 05 reads
> **61° by end-tangent but 78° by arc-span**, where the two agree to 0.5° (a clean arc).
> Measured with the **same arc-span estimator** for both, the FEM already reproduces CanDo
> bend to **0.82–1.01 (mean ~0.91)** — see the CORRECTED table below. **There is no 32% bend
> gap.** The residual is small and concentrated at extremes (2HB 0.82, 180° hairpin ~0.85).
> Everything below the corrected table (coupling-ruled-out, rest-curvature, stiffness-model)
> was reasoning built on the artifact — kept for history but SUPERSEDED by this correction.

### CORRECTED table — FEM & CanDo BOTH by arc-span (`process_bend_battery.py`)
B5 excluded (SQ routing error bp159 H0→H1 — separate session). B4 submitted with a few
staples linearized (nicks only; bend program unchanged). FEM = native LINEAR prestress solve.

| design | CanDo° | FEM (arc-span)° | **FEM/CanDo** | notes |
|---|---|---|---|---|
| B1_density_full (112 xo) | 86.5 | 80.4 | **0.89** | |
| B1_density_half (56 xo)  | 86.4 | 84.3 | **0.94** | |
| B1_density_quarter (28 xo) | 89.5 | 84.0 | **0.93** | density sweep flat both sides |
| B1_density_minimal (1 xo) | 182.8 | — | — | CanDo collapse (disconnected); discard |
| B2_bend_030 | 29.7 | 27.9 | 0.93 | |
| B2_bend_045 | 47.0 | 45.6 | 1.01 | |
| B2_bend_060 | 56.2 | 54.4 | 0.91 | |
| B2_bend_090 | 86.5 | 80.4 | 0.89 | |
| B2_bend_135 | 129.0 | 121.3 | 0.90 | |
| B3_len_105 | 59.1 | 58.9 | 1.31 vs target* | short design, arc noisy |
| B3_len_210 | 86.5 | 80.4 | 0.89 | |
| B3_len_420 | 165.5 | 153.5 | 0.85 | high strain |
| B4_2hb_bend | 75.3 | 73.5 | 0.82 | smallest cross-section |
| B4_4hb_bend | 85.8 | 87.6 | 0.97 | |

### DEFINITIVE FEM/CanDo (linear, arc-span, clean per-station centerline) — 2026-07-03
Explicit **FEM/CanDo** (the earlier "0.82 for 2HB" etc. were FEM/*target*, a second misread).

| design | FEM/CanDo | agree° | design | FEM/CanDo | agree° |
|---|---|---|---|---|---|
| B1_full (112xo) | 0.90 | 0.5 | B2_090 | 0.90 | 0.5 |
| B1_half (56xo)  | 0.94 | 0.5 | B2_135 | 0.90 | 4.0 |
| B1_quarter (28xo) | 0.91 | 0.6 | B3_210 | 0.90 | 0.5 |
| B2_030 | 0.92 | 0.0 | B3_420 | 0.93 | 21.6 noisy |
| B2_045 | 0.95 | 0.0 | B4_2hb | **0.94** | 0.3 |
| B2_060 | 0.93 | 0.1 | B4_4hb | **0.99** | 0.7 |
| 05 | 0.90 | 0.5 | 06_hairpin | 0.86 | 16.5 noisy |

**Mean 0.92, range 0.90–0.99** for every cleanly-measured design (agree < 5°). It is a
**uniform ~8–10% offset**, not strain- or cross-section-dependent. FEM/analytic ≈ 0.86–0.90,
CanDo/analytic ≈ 0.95–0.97 → the FEM is ~10% more compliant in bending than CanDo's continuum.

**Nonlinear solve** (`solve_prestress_shape`) closes the moderate cases toward CanDo: 05 →
82.1° (**0.95**), 2HB → 73.3° (**0.97**), 4HB → 92.5° (1.08). The 180° hairpin is the sole soft
spot (nonlinear 0.78) — but its *measurement* is unreliable (span vs sagitta disagree 16–22°;
a tight U can't be circle-fit), and our corotational solve relaxes it open more than CanDo's
ADINA. Edge case, measurement-confounded.

**BOTTOM LINE: bend is MATCHED to ~0.92 (linear) / ~0.95 (nonlinear, moderate). No systemic
gap, no extreme-strain residual (2HB/4HB are 0.94/0.99). The paper-review U→D→R per-segment
rework was NOT built — unwarranted once the premise (0.68) proved to be an estimator artifact.**

## Diagnosis (the plan's central question, ANSWERED)

**"Does CanDo also lose bend to shear-lag (our model right, needs tuning), or is CanDo bend
density-independent (our shear coupling too weak)?" → CanDo bend is DENSITY-INDEPENDENT.**

1. **Crossover density is NOT the lever (three independent confirmations).**
   - B1: CanDo bend is FLAT 86.5→86.4→89.5° as staple crossovers drop 112→56→28 (4× cut,
     <3° change).
   - CanDo `05.inp` census: 117 HJ ≈ our 122 (CanDo not denser).
   - In-code: +1140 rigid links (10× coupling) changes our FEM bend <1°.
   ⇒ The sparse-coupling / shear-lag hypothesis is refuted from reference, model, AND sweep.

2. **CanDo is a near-ideal LINEAR bend converter, ratio ≈ 0.95, flat across everything:**
   angle 30→135° (0.94–1.04), length 210/420 (0.92–0.96), cross-section ≥4HB (0.95–0.96).
   Only 2HB dips (0.84) — a mild small-cross-section effect. Programmed bend ≈ realized to ~5%.

3. **Our FEM under-converts (~0.68) AND the deficit GROWS with strain** — angle 0.74→0.63,
   length 0.79→0.55. That is the fingerprint of the AXIAL-RELIEF loss (67% of eigenstrain
   energy → uniform axial stretch): more eigenstrain ⇒ more absolute loss to stretch.

## The fix — rest-curvature reformulation TRIED and REJECTED (2026-07-03)
Hypothesis: apply the loop/skip differential as a rest-CURVATURE (bending moments) instead
of opposing axial end-forces (±N0 = EA·δ0/L, which leak ~67% to stretch → 0.68 bend).
Implemented in `assemble_prestress_force` (curvature mode) + `_bundle_rest_curvature`:
- **The curvature geometry is EXACT** — the composite plane-section fit gives κ direction +
  magnitude matching the analytic: 05 → R=45.2 nm vs `predict_radius_nm` 45.5. So the
  eigenstrain→curvature projection is correct.
- **But applying κ as per-element bending moments FAILS.** A constant rest-curvature applied
  as element end-moments has its internal moments cancel at shared nodes → only a net
  end-couple per helix survives. A long, crossover-coupled bundle does NOT transmit end-
  couples into a uniform curvature (Saint-Venant + distributed crossover constraints). The
  realized bend is topology/length-dependent and, even sized to the composite EI
  (`comp_scale = 1+(EA/EI)d²`, ~25× ΣEI_h for 6HB), UNDER-converts and worse than the axial
  method: **6HB 0.62, 4HB 0.42, 420 bp 0.32 of analytic** (self-cal factor 1.6–3.2, not a
  constant). Clean planar arcs (planarity 0.00) but wrong magnitude.

**Conclusion: the bend gap is NOT in the eigenstrain LOAD formulation — it is in the discrete
STIFFNESS RESPONSE.** The axial-force eigenstrain applies the correct section moment
M* = Σ EA·ε_h·r_h; the discrete crossover-coupled beam simply responds to it more compliantly
(more axial relief) than CanDo's continuum plane-section B31H beam. Reverted the solver to the
validated axial+torsion eigenstrain (honest 0.68). RMSF ✅ + twist ✅ unchanged.

**Real next step (dedicated session): a STIFFNESS-model change** — make the discrete bundle
enforce plane-sections like CanDo's continuum. Candidates: (a) rigid cross-section MPCs that
tie ALL helices at a station into one plane-section frame (not just crossover node pairs —
the dense-link test showed pairwise rigid links don't rigidify the section); (b) add the
inter-helix SHEAR stiffness CanDo's B31H section carries; (c) a Timoshenko/warping term.
Gate any change on: bend → ~0.95 flat across B1/B2/B3/B4 AND twist (0.26 6HB) + RMSF unmoved.

## RMSF (secondary, all present)
Stiff crossover-dense core → floppy ends, ~0.5–1.8 nm on the well-connected designs
(matches first-wave). Elevated on 2HB / minimal (sparse coupling → softer), as expected.
