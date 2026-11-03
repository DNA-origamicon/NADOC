---
name: project_snupi_gaps
description: "Gap analysis — our SNUPI mimic vs the full published SNUPI (Lee/Kim ACS Nano 2021, SI Notes S1–S15). Every modeling difference + a phased implementation plan + a fresh-session kickoff prompt."
metadata:
  node_type: memory
  type: project
---

# SNUPI mimic — gap analysis vs the full publication + build plan

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## ⚙ 2026-07-13 — SHAPE fix: diagonal material for the equilibrium solve (VoltronCore)
Symptom: SNUPI "Fine" on a large SQUARE-lattice design (VoltronCore, 59 helices) over-deformed massively
vs mrDNA/oxDNA (which sit ~1.7 nm from the design). Root cause, isolated by experiment (results below):
the **twist–stretch (off-diagonal) couplings** of the SNUPI 6×6 material. The loop/skip + square register
over-twist eigenstrain is imposed as a nodal FORCE computed from the ISOTROPIC stiffness (`el.gj`), then
applied to the cross-coupled SNUPI constitutive law → the couplings over-rotate large twisted bundles.
Measured (VoltronCore, real deformation vs the undeformed reconstruction, self-consistent):
- **COUPLED (old default): 33.5 nm** real deformation; crossovers blown to 65 nm.
- **DIAGONAL (couplings zeroed): 3.3 nm**; crossovers == the undeformed baseline (NO solve over-stretch).
- Isolation: zeroing couplings alone took axis-RMSD 11.9→1.4 nm; cando (isotropic) = 1.4 nm; torsion/axial
  eigenstrain individually don't drive it — it's the coupling. 6HB diagonal-vs-coupled shape delta = **0.000 nm**
  (no regression on well-formed bundles — their eigenstrain is small so the couplings barely act).
**Fix** (`fem_solver.py`): `assemble_global_stiffness(..., diagonal_material=)` + `solve_prestress_shape(..., diagonal_material=)`;
`predict_shape` runs the SNUPI **shape** solve with `diagonal_material=(material=="snupi")` (drops the off-diagonal
couplings — anisotropic rigidities kept). The **RMSF/DCCM NMA keeps the FULL coupled 6×6** (SNUPI's validated
flexibility channel — untouched). cando is diagonal already (no-op). This composes with the disconnected-body
fix ([[project_cando_fem]]) already in place.
<a id="-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem-overlay"></a>
- [⚙ 2026-07-13 — DISPLAY fix: overhang beads no longer snap in the FEM overlay](details/project_snupi_gaps/01-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem.md#-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem-overlay)

<a id="-2026-07-13--display-fix-2-winding-rise-scale-bug-the-still-open-residual--was-not-minor"></a>
- [⚙ 2026-07-13 — DISPLAY fix #2: winding rise-scale bug (the "still-open" residual — was NOT minor)](details/project_snupi_gaps/01-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem.md#-2026-07-13--display-fix-2-winding-rise-scale-bug-the-still-open-residual--was-not-minor)

<a id="-2026-07-13--display-fix-3-47-of-every-frame-was-beads-the-renderer-cannot-draw"></a>
- [⚙ 2026-07-13 — DISPLAY fix #3: 47% of every frame was beads the renderer cannot draw](details/project_snupi_gaps/01-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem.md#-2026-07-13--display-fix-3-47-of-every-frame-was-beads-the-renderer-cannot-draw)

<a id="visual-vs-namd-automation--the-shape-gap-2026-07-12"></a>
- [Visual-vs-NAMD automation + the shape gap (2026-07-12)](details/project_snupi_gaps/01-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem.md#visual-vs-namd-automation--the-shape-gap-2026-07-12)

<a id="-phase-d-done-2026-07-12--g4--g5--g11-full-corotational-newton-opt-in-shape-only"></a>
- [✅ Phase D DONE (2026-07-12) — G4 + G5 + G11 (full corotational Newton; opt-in, shape-only)](details/project_snupi_gaps/01-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem.md#-phase-d-done-2026-07-12--g4--g5--g11-full-corotational-newton-opt-in-shape-only)

<a id="-phase-c-done-2026-07-12--g7--g8-new-observables-no-impact-on-the-rmsf-verdict"></a>
- [✅ Phase C DONE (2026-07-12) — G7 + G8 (new observables, no impact on the RMSF verdict)](details/project_snupi_gaps/01-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem.md#-phase-c-done-2026-07-12--g7--g8-new-observables-no-impact-on-the-rmsf-verdict)

<a id="-phase-b-done-2026-07-12--g3--g2-gated-behind-materialsnupi"></a>
- [✅ Phase B DONE (2026-07-12) — G3 + G2, gated behind `material="snupi"`](details/project_snupi_gaps/01-2026-07-13--display-fix-overhang-beads-no-longer-snap-in-the-fem.md#-phase-b-done-2026-07-12--g3--g2-gated-behind-materialsnupi)

<a id="-phase-a-done-2026-07-11--g1--g6--g12-gated-behind-materialsnupi"></a>
- [✅ Phase A DONE (2026-07-11) — G1 + G6 + G12, gated behind `material="snupi"`](details/project_snupi_gaps/02-phase-a-done-2026-07-11--g1--g6--g12-gated-behind-materialsnupi.md#-phase-a-done-2026-07-11--g1--g6--g12-gated-behind-materialsnupi)

## What we already match
- Intrinsic 6×6 motif properties (S3/S4): transcribed EXACTLY (GJ 313.83, EIy 158.33, EIz 245.79,
  g(Δx,Θx) −277.39; 74 motifs). `snupi_params.json` + `motif_D`/`family_mean_D`.
- Inter-helix Debye–Hückel electrostatics (S6/S7): q=0.7 e @ 20 mM MgCl₂, λ_D=1.24 nm, r_cut=2.5 nm.
- Free-free NMA RMSF via equipartition, 200 modes, 300 K (S11). **[G6 done: snupi now uses the
  generalized mass-weighted eigenproblem; cando stays K-only mass-independent.]**
- Compliant CO-step crossover beams; loop/skip eigenstrain; anchors (Dirichlet) + uniform E-field.

<a id="the-gaps-snupi-si--ours"></a>
- [The gaps (SNUPI SI ⟶ ours)](details/project_snupi_gaps/03-the-gaps-snupi-si--ours.md#the-gaps-snupi-si--ours)

<a id="prioritization-by-expected-effect-on-the-validated-rmsf-vs-md-metric-low-risk-first"></a>
- [Prioritization (by expected effect on the VALIDATED RMSF-vs-MD metric, low risk first)](details/project_snupi_gaps/03-the-gaps-snupi-si--ours.md#prioritization-by-expected-effect-on-the-validated-rmsf-vs-md-metric-low-risk-first)

<a id="kickoff-prompt-for-a-fresh-session"></a>
- [Kickoff prompt for a fresh session](details/project_snupi_gaps/03-the-gaps-snupi-si--ours.md#kickoff-prompt-for-a-fresh-session)

<a id="references"></a>
- [References](details/project_snupi_gaps/03-the-gaps-snupi-si--ours.md#references)
