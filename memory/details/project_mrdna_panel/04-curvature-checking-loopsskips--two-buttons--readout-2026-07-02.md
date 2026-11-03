# Curvature checking (loops/skips) — two buttons + readout (2026-07-02) — supporting detail

[Topic head](../../project_mrdna_panel.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Curvature checking (loops/skips) — two buttons + readout (2026-07-02)
Purpose: quick-check designs with programmed curvature (Dietz loop/skip bend).
- **Two run buttons** (`mrdna-jobs-coarse-btn` / `-fine-btn`): **Coarse** (single
  5 bp/bead pass — fast global shape, no twist ⇒ no bend) and **Fine** (the real
  mrDNA multi-resolution pipeline: coarse → 1 bp/bead + local twist → frozen-twist).
  `MrdnaJob.fine_steps` (>0 ⇒ fine job). **Runner dispatch (KEYSTONE, see [[LESSONS]]
  A9):** Fine calls **`mrdna.multiresolution_simulation(...)`** (NOT
  `model.simulate(coarse_steps=,fine_steps=)`, which silently runs a single coarse
  pass — the kwargs are swallowed); Coarse calls `model.simulate(num_steps=…,
  timestep=200e-6, gpu=…)`. Multiresolution writes numbered CG stages `{stem}-N.psf`;
  `_sim_paths` auto-resolves the highest CG stage (the fine structure) via `_psf_is_cg`.
  The atomistic tail is tolerated (fine CG is written first). `FINE_DEFAULT_STEPS=2e5`.
- **`backend/core/mrdna_curvature.py`**: `analytic_curvature` (NADOC's OWN continuum
  Dietz model `loop_skip_calculator.predict_radius_nm`, scans bend direction) +
  `measured_curvature` (from display positions; **bend-based** R = arc_len/rad(bend),
  NOT a circle fit — the circle fit is noise-dominated on short CG structures and
  swings 20↔240 nm run-to-run) + `curvature_report`. Route
  `GET /mrdna/jobs/{id}/curvature` (+ `/mrdna/curvature/analytic` instant), cached to
  `curvature.json` (lazy backfill `load_curvature`). Panel readout `formatCurvature`.
- **CURVATURE reproduction (validated live, RTX box) — partial, ~18%.** Two findings:
  (1) The panel was silently NOT running the fine stage (LESSONS A9); fixing it (real
  `multiresolution_simulation`, 1 bp/bead + twist) raises the bend 2°→**~12–16°** on
  `6hb_curved.nadoc` (analytic **R≈36 nm / 88°**). (2) It PLATEAUS there (12° at both
  5e5 and 2e6 fine steps ⇒ not equilibration), and **T0 is the best parameterization**
  (T0 ~12° vs mrDNA default **1.3°** — don't drop T0). So mrDNA gives a
  DIRECTIONAL/qualitative bend (~18% of designed), not a quantitative one. The panel
  readout shows analytic (trustworthy) + simulated (indicator) + an amber caveat when
  sim/analytic<0.5. Closing the gap = open [[project_crossover_parameterization]] /
  [[project_bundle_stiffness_params]] inter-helix-stiffness work, NOT a panel fix.
- Loops otherwise run through mrDNA/ARBD cleanly: model builds (2468 nts on 6hb_curved,
  36 loop copies, **zero coincident beads** → no LJ explosion), ARBD simulates fine.
  `_build_nt_arrays` uses UNDEFORMED lattice axes + the loop/skip pattern, so there's
  no double-count with any applied bend deformation (mrDNA predicts, never refines a
  pre-bent geometry).

## MD-seed handoff (2026-07-02) — seed an MD run from a fine-stage job
A **completed FINE-stage** mrDNA job can seed a downstream atomistic MD run. Both
consumers share `mrdna_runner.build_md_seed_override` (ds per-helix Phase-3b spline,
crossovers INCLUDED, + ssDNA/overhang handling — see below):
- **GROMACS (headless/API only):** `POST /api/design/export/gromacs-mrdna-start?mrdna_job_id=…`
  → poll `gromacs-status` → download `gromacs-result`. No UI — the GROMACS export modal
  was removed 2026-05-17, so this path is scriptable only.
- **NAMD (in-app):** panel **"Use as NAMD seed"** button (`seedReady` = completed +
  `fine_steps>0`) → `api.createMdJob({mrdna_job_id})` → a managed MD job in the Molecular
  Dynamics panel tagged **"mrDNA seeded"** (`seededBadge`). Backend mirrors the oxDNA seed
  path: `build_namd_seed_from_mrdna` + `assert_mrdna_namd_seed_available` (`mrdna_runner`,
  reuse `resolve_md_seed_inputs` gating), `seed_mrdna_job_id` on `MdJob`, and the
  create/refit/prep branches in `routes_md.py`.
### Seed reconstructed as an untwisted ladder → impose ideal twist around the relaxed axis (FIXED 2026-07-04)
Every mrDNA-seeded NAMD run relaxed to **nearly straight strands with almost no helical
twist** (measured on the `6hb_2xT` seed: scaffold **0.7°/bp**, staples 7–17°/bp, vs B-DNA
34.3°). Root cause is in the **seed** reconstruction `nuc_pos_override_from_arbd_strands`
(mrdna_bridge), NOT the sim: mrDNA's fine model represents each bp with a **`DNA` axis/
centroid bead** (sits ON the helix centreline, ~2–4 Å off its own fitted axis) **plus a
separate `O` orientation bead** whose vector carries the ~34°/bp twist. Verified on the real
job: `DNA`-bead azimuth advances only **~1°/bp**; the `O`-vector advances **~26–37°/bp** ≈
design. The old override read **only `DNA` beads** and derived the backbone azimuth from
`radial = DNA_bead − ideal_axis` — which is dominated by the helix's rigid ~10 nm lateral
relaxation offset (constant per helix), so `fwd_rad` pointed the same way for every bp → a
zero-twist ladder. **The `O` orientation beads — the one thing that knows the twist — were
never read.**
- **Fix (Option A):** treat the `DNA`-bead spline as the relaxed **AXIS** and impose **ideal
  B-DNA twist** around it (`fwd_angle = phase_offset + local_i·twist`), exactly like the
  display path `nuc_pos_override_display_from_coarse` — mrDNA's orientation potential holds
  local twist near B-DNA, so "relaxed axis + ideal local twist" is the correct seed. Also
  adopts `_relaxed_axis_at_bp` (straight tangent extrapolation past beadless ends, no
  end-ring). Post-fix base-pair-vector rotation (axis-independent twist metric) = **34.3–35.0
  °/bp** on all 6 helices. Twist measured around the fixed design axis under-reports (~13°)
  because the reconstruction builds twist around the *local* relaxed tangent — use the
  fwd−rev base-pair vector, not backbone-azimuth-around-a-reference-axis.
- **Behavior change beyond twist:** the old code pinned ds positions to the **ideal** axis
  (`ideal_axis_pt + R·rad`), discarding the relaxed-axis displacement magnitude (kept only
  its direction, for azimuth). The seed now places nts on the **relaxed** axis (`axis_pt +
  R·rad`) — it genuinely follows the CG bend/drift/crossover-gaps (matches the corrected
  display; the old ds seed was ~ideal geometry). Legit consequence: positions sit a
  CG-relaxation distance (~3 nm axis drift + ~1 nm R) off the design axis, so
  `test_mrdna_pipeline.py::TestRoutedPrimitiveIntegration::test_position_range_matches_structure`
  margin was widened 2→6 nm (still ≪ a frame-mismatch's tens of nm).
- Pins: `test_mrdna_md_seed.py::test_seed_reconstruction_has_bdna_twist` (slow, real-job;
  asserts per-helix bp-vector rotation 28–40°/bp — proven can-go-red: old code fails it).

- **Gate — FINE required (decided 2026-07-02):** coarse-only jobs are 409'd / the button
  is greyed. The coarse override re-idealises + EXCLUDES crossover junctions → seeding from
  it keeps the very crossover clashes CG relax exists to fix. Only the fine stage seeds.
- **ssDNA/overhang seed handling** (distinct from the *display* phantom-duplex above, which
  the user accepts): `nuc_pos_override_ssdna_from_arbd` + `_ssdna_runs` harvest mrDNA's
  relaxed `NAS` beads so overhangs follow the relaxed body instead of seeding detached at
  the design axis (restores the ss/ds junction backbone bond a ds-only override leaves at
  ~1.4 nm). Per run: spline-NAS / root-translate / leave-ideal, chosen by a **do-no-harm
  clearance selector** (never worse than ideal). Caught+fixed a coincident-atom LJ=2e37 bug
  via the clash oracle. KNOWN LIMIT: long overhangs through a dense bundle core clash under
  any placement (baseline too) — separate problem.
- Validation: `tests/test_mrdna_md_seed.py` (gating + skip-guarded real-job junction/clash
  + NAMD-seed oracles, run live against `5edf`=`6hb_sim_v2` 200k fine); `seedReady`/`seededBadge`
  vitest. Live gesture = [[manual_validation_debt]] MV-MRDNA-NAMD / MV-MRDNA-SEED. Deep dive:
  [[project_multiresolution_roadmap]] Phase 4/5.

### Extra-base atomistic-seed bug — inline threading (FIXED 2026-07-04)
Seeding an extra-base design (`6hb_2xT`, 24 "TT" crossovers) to NAMD produced **55 Å
backbone O3′→P junk bonds** → NAMD blows up. Root cause was in the atomistic→psfgen
translation, NOT the mrDNA CG side (which threads inserts correctly via topology):
- **`atomistic.py _build_extra_base_atoms`** stored each insert's `bp_index`/`direction`
  as `ha.index`/`ha.strand` — always `half_a`, even when the source (owning, 3′) flank is
  `half_b`. So for the ~half of crossovers whose src is half_b, the insert's stored
  `(helix_id, bp_index, direction)` pointed at the WRONG nucleotide (also a latent
  `apply_deformations_to_atoms` bug — it uses that key as the insert's frame). Fixed:
  store `src_key[1]`/`src_key[2]` (the true src flank). `md_pkey` keys inserts by
  `crossover_id`+`k`, so trajectory mapping is unaffected.
- **psfgen bonds residues in `seq_num` order**, but `_build_extra_base_atoms` APPENDS
  inserts at each chain's max `seq_num` → all inserts cluster at the chain tail, so psfgen
  threaded `real → eb → eb → next-crossover's-eb` (bonding inserts from DIFFERENT
  junctions, 55 Å apart) instead of `prev_real → eb… → next_real`. Fixed: new
  **`atomistic._thread_extra_bases_inline(atoms)`** (called at end of `build_atomistic_model`)
  renumbers each chain's `seq_num` so every insert sits right after its src-flank real nt
  (`flank_seq + k + 1`), contiguous 1..M. Looped helices (non-unique `(helix,bp,dir)`) fall
  back to tail-append (unchanged). Only touches `seq_num` — a residue counter, not topology.
- Result: ideal-geometry max backbone bond **1.87 Å** (was tens of Å); on the real
  `b05f0fdc` 200k-fine seed, extra-base junction bonds all sane (0 insert bonds >6 Å; the
  residual 14–19 Å scaffold-crossover stretches are the general mrDNA-seed reconstruction,
  present with/without extra bases). **Full pipeline proven end-to-end 2026-07-04:** seed →
  `prepare_mgh_slow_release` (GROMACS solvate + declash auto-on for extra bases + full MGH
  ladder) → **NAMD stage-0 minimization: BOND 3.09M → 0.119M kcal/mol (96%↓), TOTAL
  converged to −12.7k, no explosion.** So `6hb_2xT` seeds properly enough to reach production.
- Pins: `test_namd_topology.py::{test_extra_bases_thread_inline_in_seq_num,
  test_extra_base_junction_backbone_bonds_are_sane}` (both can-go-red, verified).
- Test-oracle correction: `test_mrdna_md_seed.py::_junction_gap_and_clash` now excludes
  inserts (their now-correct src key polluted the ss/body buckets) and the do-no-harm
  assertion is gated on the ds-only baseline not already being sub-VDW (the documented
  dense-bundle carve-out). Before the key fix, that test PASSED on `6hb_2xT` by a 0.0015 nm
  artifact — the buggy insert key faked the baseline; the real `clash_all` (0.018 nm ss/body
  overhang clash) was unchanged, i.e. the ssDNA dense-bundle limit above still stands.
