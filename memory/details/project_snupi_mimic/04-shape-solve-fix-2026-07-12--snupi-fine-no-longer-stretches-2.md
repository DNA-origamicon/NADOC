# ⚠ Shape-solve fix (2026-07-12) — snupi Fine no longer stretches ~2× — supporting detail

[Topic head](../../project_snupi_mimic.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ⚠ Shape-solve fix (2026-07-12) — snupi Fine no longer stretches ~2×
The default (fixed-point S9) snupi nonlinear SHAPE solve included the inter-helix electrostatics,
which **ran away** (no consistent tangent → the lateral-soft repulsion mode blows up → every helix
stretched ~2×: 6hbx100_noT 35→85 nm vs cando 42 nm). **Fix:** the default snupi shape solve now drops
through the same corotational-PREDICTOR loop as cando with the SNUPI material, WITHOUT electrostatics
(`solve_prestress_shape`). Electrostatics stays where it's (a) validated — the free-free NMA/RMSF (PD
axial-only tangent, exp42 numbers unchanged) — and (b) stable — the opt-in corotational Newton
(`corotational=True`, its consistent G11 tangent handles the repulsion; 6hbx100_noT span 40.9 nm).
Verified end-to-end through the real job→display path: span 41.7 nm. Regression pin
`test_snupi_nonlinear_shape_is_finite_and_not_stretched` (snupi span < 1.3× cando). `_solve_snupi_nonlinear`
is now unused by the default path (kept for reference / the corotational path supersedes it).
**Frontend note:** the deform-display toggle works for SAVED designs (design-scoped unified job list);
a job run on a NEW *unsaved* design is filtered out of that list (path mismatch) — a known edge case,
not a feature bug (the display itself works — user-confirmed + backend serves all payloads).

## Handoff
**Gap-closure Phase A + B + C DONE (2026-07-11/12) — see [[project_snupi_gaps]] head for full detail.**
Phase A: G1 (sequence-specific `motif_D`), G6 (SPD mass matrix + generalized eigsh), G12 (`mgcl2_M` salt).
Phase B: G3 (single/double crossover classification; **biggest win**), G2 (bp-frame registration eq 3.18,
kept ON). Phase C: G7 (`compute_correlation_matrix` BP–BP DCCM + `scripts/snupi_dccm_compare.py` MD comparator),
G8 (`persistence_length_from_nma` bending L_p ≈ 2.6–4.5 µm). cando byte-identical throughout.
**Verdict, now on TWO channels: SNUPI ≥ CanDo.** RMSF: HC pearson 0.598→0.623, SQ 0.742→0.763. DCCM motion
topology (HC): snupi→MD 0.491 > cando 0.454. Pins `test_snupi_element.py::test_g{1,2,3,6,7,8,12}_*` (27 total).
**Phase D DONE too (2026-07-12): G4/G5/G11 — the full corotational Newton shape solver** (opt-in
`predict_shape(material="snupi", corotational=True)`; `backend/physics/snupi_corotational.py` EICR +
consistent internal force fixed the old divergence; benchmark-validated rigid/linear-EB/large-defl; 6HB
converges ~47 s; electrostatics with the FULL tangent in-Newton). Shape-only — verdict metrics unchanged.
Pins `tests/test_snupi_corotational.py` (5). **ALL gap phases A–D now DONE.** Remaining refinements only:
the 15 couplings inside the corotational local element, G9/G10 (situational), G7's MI-based correlation.
Phase A+B committed as `7d3c216`; **Phase C (G7/G8) + Phase D (G4/G5/G11) uncommitted.**

**P1 + P2 + P2b + P4 DONE (2026-07-11). FINAL VERDICT: "SNUPI for free" = YES** — snupi ≥ cando on
both lattices at $0 (robustly better on the well-sampled 20ns honeycomb; a tie/slight snupi rank-edge
on the under-sampled 5ns square). The mimic is built and validated. Next best (only if pursued):
longer square-lattice MD to firm up SQ; single-vs-double-CO classification; bp-frame registration;
then **P3** (Debye–Hückel electrostatics) — the extra-base extension is the only GPU spend.
Everything to run the mimic exists:
- Params: `backend/data/parameters/snupi_params.json` (74 motifs). Pin `tests/test_snupi_params.py`.
- Material: `backend/physics/snupi_material.py` → `family_mean_D(fam)` 6×6. Pin `tests/test_snupi_material.py`.
- FEM: `predict_shape(design, material="snupi")` / `assemble_global_stiffness(mesh, material="snupi")`
  / `compute_rmsf_nma`. Pin `tests/test_snupi_element.py`. cando path unchanged.
- Informal first data point: on `6hbx100_noT`, cando RMSF mean 0.411 nm vs snupi 0.398 nm (630 nodes,
  624 beams, 66 crossover rigid links). Comparable magnitude (shared crossover model); P4 tests
  RMSF-*pattern* correlation + shape vs the MD DCD, which is where couplings/anisotropy show.

**P4 to-do:** from `/media/jojo/Archive/nadoc_jobs/892ad3d12d4f/package/6hbx100_noT_namd_solvated/` (psf+pdb+20ns
k=0 DCD), compute per-bp RMSF (bp-center = mean both-strand C1'; reuse `local_crossover_extract.py`
/ `build_p_gro_order`) + equilibrium shape/twist/bend/L_p. Correlate snupi vs cando vs MD.
Success = snupi ≥ cando at matching MD, at $0.

**Open P2b/P3 (only if P4 says so):** (P2b) crossovers as compliant double-CO/single-CO beams
(replace rigid links; single-CO needs PD-projection — 7/16 non-PD); bp-frame registration for EIy≠EIz;
snupi prestress force. (P3) Debye–Hückel electrostatics.

Key references: `backend/physics/fem_solver.py`, `Literature/SNUPI_SI.pdf` Tables S1–S5,
[[project_cando_fem]] (FEM scorecard), [[feedback_bundle_param_extraction]] (why NOT Euler-ZYZ).
