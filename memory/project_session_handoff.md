---
name: Session handoff — bundle param extraction fixed + 10hb run assessment (2026-04-26)
description: extract_bundle_params.py fixed (topology-based assignment); first-pass K_lateral extracted; run at 10.3%, continue
type: project
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
## What changed this session (2026-04-26)

### Git commit pushed
`a52a751` — "feat: MD overlay panel — trajectory scrubber, PBC correction, Kabsch alignment"
Includes: atomistic_to_nadoc.py, md_metrics.py, ws.py PBC pipeline, md_panel.js, md_overlay.js, all tests.

### extract_bundle_params.py — two bugs fixed

**Bug 1 — Wrong trajectory**: hardcoded `prod.xtc` (24 frames). Now auto-selects:
1. `view_whole.xtc` (recommended, PBC-preprocessed)
2. all `prod_best.part*.xtc` sorted
3. `prod.xtc` fallback

Topology: `em.tpr` > `prod_best.tpr` > `prod.tpr` > `npt.gro`

**Bug 2 — Geometry-based helix assignment fails**: design axes at XY=(0,0), trajectory at XY=(60, 44) Å. Even with centroid shift + 2D Kabsch rotation, pairs sharing the same X column in the honeycomb lattice were mis-assigned (outer helices displace > 10 Å after 15° rotation). Fixed by replacing with **topology-based assignment** via `build_p_gro_order` from `atomistic_to_nadoc.py` — maps GROMACS P-atom order directly to (helix_id, bp_index) with no geometry search.

**Bug 3 — PCA axis sign flip**: `_helix_axis_from_c1prime` returns arbitrary ±Z. Fixed by snapping all reference axes to +Z after frame-0 computation.

### 10hb nominal run — convergence assessment

- **Current time**: 103.4 ns (10.3% of 1000 ns target)
- **Thermodynamics**: fully converged. T=310.2 ± 0.7 K, potential flat 80+ ns.
- **Run status**: active (PID 997601), continuing
- **view_whole.xtc**: covers 0–54.6 ns (547 frames), PBC-preprocessed

**First-pass stiffness (5 of 11 pairs reliable, lat > 12 Å):**
- K_lateral: ~0.18 ± 0.10 kJ/mol/Å² (both 2-2 and 2-3 contexts)
- K_tilt (q4): 100–480 kJ/mol/rad² (high pair-to-pair variance, insufficient sampling)
- Per-pair ESS: 49–65 (need ~200 for converged stiffness)

**Known extraction limitations (not fixed, future work):**
1. **Crossover centroid bias**: 6 of 11 pairs show lat=6–11 Å (expected ~22 Å). Crossover residues at the midpoint between helices pull the PCA centroid inward. Fix: exclude crossover-bp positions from centroid in `_interhelix_q`.
2. **Euler ZYZ gimbal lock**: K_q3, K_q5 unreliable for tilt < 15° (all pairs). Fix: axis-angle or quaternion parameterization for rotational DOFs.
3. **3-3 context** (h_XY_1_1 ↔ h_XY_0_1): affected by both — not extractable until fixes applied.

**When to re-run extraction**: after extending view_whole.xtc to ~220+ ns (need `gmx trjcat` + `gmx trjconv -pbc whole`). At 220 ns, per-pair ESS ≈ 200 → converged lateral stiffness.

### Documentation added
`docs/bundle_param_extraction.md` — full pipeline description, limitations, convergence table, commands.

## Reference paths

- Extract script: `runs/10hb_bundle_params/extract_bundle_params.py`
- Convergence monitor: `runs/10hb_bundle_params/check_progress.py`
- Run dir: `runs/10hb_bundle_params/nominal/`
- Results: `runs/10hb_bundle_params/nominal/all_pairs.json`, `context_params.json`
- Doc: `docs/bundle_param_extraction.md`

## Earlier pending (still valid)

- **Visual validation in browser**: load `workspace/10hb.nadoc` + `view_whole.xtc`, play through frames
- **Live mode validation**: `get_latest` rebuild-Universe fix never tested with active XTC
- **RMSF coloring**: compute per-bead RMSF from aligned trajectory → `applyFemRmsf`
- **Test nuc_pos_override_from_mrdna_coarse → GROMACS EM** (from 2026-04-21)
