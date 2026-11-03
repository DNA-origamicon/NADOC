# Existing assets — supporting detail

[Topic head](../../project_cando_fem.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Existing assets
- Archived LINEAR beam FEM: `archive/physics_xpbd_fem/backend/physics/fem_solver.py`
  (505 LOC; build_fem_mesh, assemble_global_stiffness, apply_boundary_conditions,
  solve_equilibrium, compute_rmsf eigsh, deformed_positions). f≡0 → u=0 (no pre-stress);
  reads current xover.half_a/half_b already. Frontend `fem_client.js`, tests present.
- Analytic Dietz: `loop_skip_calculator.predict_radius_nm` / `predict_global_twist_deg`.
- caDNAno export w/ loop/skip: `backend/core/cadnano.py` (`export_cadnano`, :813).
- Fixtures: `workspace/6hb_curved.nadoc` (±9 ins/del, analytic R≈36 nm / 88°),
  `Examples/multi_domain_test3_bend90.nadoc` (90°), `workspace/loop_test.nadoc`.

## Phase plan
- P0 feasibility — **DONE (GO w/ conditions)**. First-wave CanDo battery generated + extracted.
- P1 restore linear FEM — **DONE (2026-07-03)**. `backend/physics/fem_solver.py` restored
  from archive (fixed `Optional` import; N_RMSF_MODES 30→200, KBT@298K per CanDo). Runs
  end-to-end on battery designs (mesh→K→solve→RMSF). Tests: `tests/test_fem_solver.py`
  (5 smoke tests green); `just test` 3823 passed. **Two calibration gaps exposed (→P2):**
  (1) **mesh over-counts nodes** — 1386 vs CanDo 1264: `build_fem_mesh` uses helix AXIS
  length `round(len/rise)` incl. the ~21-bp auto_scaffold end-caps; must use actual bp
  (domain ranges, loop/skip-adjusted). (2) **RMSF ~7× too floppy** (FEM mean 5.04 vs CanDo
  0.71 nm, max 12.4 nm unphysical) — uncalibrated stiffness/constraints + soft internal
  modes under a single centroid pin. Equilibrium u=0 (no pre-stress yet, expected).
- P2 (IN PROGRESS 2026-07-03):
  - **Mesh node-count FIXED** — `build_fem_mesh` meshes only the DUPLEX CORE (bp with both
    scaffold+staple) via `_duplex_bp_per_helix`, not `round(axislen/rise)` incl. the ~21-bp
    auto_scaffold caps. 05: 1386→**1260** (CanDo 1264 ✓); 18HB 3780 (CanDo 3792). Variable-
    length beam elements → per-length `_beam_stiffness_local` cache.
  - **RMSF method FIXED — free-free NMA** (`compute_rmsf_nma`): projects out 6 rigid-body
    modes (no pin) → kills the cantilever artifact. 7×→**2.9×** (mean 2.05 vs CanDo 0.71).
  - **Remaining 2.9× isolated: NOT crossover coupling** (RMSF insensitive to k_xover
    1e5→1e9, already rigid) → it's composite bending stiffness (discrete crossovers → partial
    parallel-axis EA·r²) or a B31H-formulation gap. Next calibration target.
  - Tests `tests/test_fem_solver.py` (7 green); `just test` 3825 passed.
  - **KEY HYPOTHESIS (shapes P3):** twist damping (analytic 171°→CanDo 45/23°) is
    GEOMETRIC-NONLINEAR — helices at radius r wind around the bundle axis when it twists,
    stretching (resisted by EA); a large-rotation coupling ABSENT in linear theory. Explains
    BEND reproduced ~95-102% but TWIST heavily/size-dependently damped. Predicts: linear
    pre-stress → ~free twist 171°; only P3 nonlinear → damped 45/23°. VERIFY when pre-stress lands.
  - Reference values complete incl. 10_18hb_bend (91°/R42, 1.02) in cando_reference_values.json.
  - **PRE-STRESS IMPLEMENTED + VALIDATED** — `assemble_prestress_force(mesh, design)`:
    loop/skip eigenstrain → equivalent nodal forces (torsional φ0=-Σδ·2π/bp_per_turn on θz;
    axial δ0=Σδ·rise, per-element length-weighted, rotated to global). **Linear solve
    reproduces the FREE analytic per-helix twist EXACTLY** — 02: local θz end-to-end +171.4°
    (analytic 171.4), 03: +342.9° (342.9), to 0.1°. Pins the eigenstrain magnitude/sign.
    Test `test_prestress_reproduces_free_analytic_twist`.
  - **GLOBAL SHAPE ≈ 0 in linear** — 6-fold global twist ~0 (02/03), bend ~0° (05, |u_trans|
    0.07 nm). TWO distinct causes:
    (a) TWIST global=0 → EXPECTED: local over-twist→global bundle winding is geometric-
        NONLINEAR (helices at radius r wind + stretch). Damping 171→45 is Phase 3.
    (b) BEND=0 → NOT expected (bimetallic differential-eigenstrain bend IS linear) →
        **crossover-model BUG: the spring enforces zero RELATIVE displacement of paired axis
        nodes incl. the AXIAL DOF, over-constraining the differential that creates bend.**
        Fix: rework crossover to CanDo's rigid zero-length-link geometry (allow axial
        differential, constrain lateral). Likely also relevant to the RMSF 2.9× softness.
  - Tests `tests/test_fem_solver.py` (8 green); `just test` 3826 passed.
- **CROSSOVER REWORK — big win (2026-07-03).** Replaced the zero-relative-displacement
  spring with a STIFF BEAM spanning the inter-helix offset (`XOVER_STIFF_SCALE=100`, robust:
  RMSF insensitive 20→1000). Rigid-link kinematics (u_B=u_A+θ_A×r_AB) with the offset geometry
  → composite bundle. Fixed BOTH:
  - **RMSF now CALIBRATED**: 05 ratio 0.97, 02 0.95, 18HB 0.92, 2HB 0.81 (was 2.9-7×). Robust.
  - **TWIST now reproduced IN LINEAR** — the offset-coupled crossovers provide the torsional
    damping (my "twist needs nonlinearity" hypothesis was WRONG; it was the missing offset
    coupling). FEM vs CanDo: 07(2HB) 111 vs 84, 02(6HB) 40 vs 45, 03 80 vs 87, 09(18HB) 28
    vs 23 — cross-section scaling captured, ~10-30% off. 6HB best (~10%).
  - **BEND enabled but under-converted**: 05 34.6° vs CanDo 87° (0.38), 06 64° vs 166° (0.36).
- **P3 corotational nonlinear solve added** (`solve_prestress_shape`, incremental load-step +
  `_reframe_elements` recompute frames from deformed geometry). Converges but **barely moves
  the bend** (05: 34.6→35.7°, 06: 63.9→71.4°). **KEY: the bend gap is NOT large-deflection
  and NOT crossover stiffness** (bend insensitive to XOVER scale 10→1e5; 35° is a small bend).
  It's the **eigenstrain→bend CONVERSION** — the outer/inner length differential relieves as
  elastic AXIAL strain instead of bending (~2.5× under). OPEN calibration problem: needs the
  eigenstrain formulation reworked (impose rest-CURVATURE / prevent along-helix relative
  slide at crossovers), not nonlinearity. Twist + RMSF unaffected (already good).
  Test `test_nonlinear_prestress_shape_runs_and_deforms`. `just test` 3827 passed.

**SCORECARD vs CanDo (2026-07-03):** RMSF ✅ 0.8-0.97 (calibrated, robust). TWIST ✅ ~10-30%
(cross-section scaling captured: 2HB 111/84, 6HB 40/45, 18HB 28/23). BEND ❌ ~38% (open —
eigenstrain→bend conversion under-couples; NOT nonlinearity). Next: crack the bend conversion.

## ⚠ BEND "GAP" WAS A MEASUREMENT ARTIFACT — CORRECTED (2026-07-03, exp36)
The reported ~0.68 FEM/CanDo bend ratio (and the whole coupling/rest-curvature/stiffness saga
below) came from measuring the FEM with an END-TANGENT estimator vs CanDo with ARC-SPAN. The
end-tangent reads low on real FEM arcs (ends straighten under BCs): 05 = 61° end-tangent but
78° arc-span (the two agree to 0.5° on the clean arc). **Measured consistently (arc-span both),
the FEM already reproduces CanDo bend to 0.82–1.01 (mean ~0.91) LINEAR; nonlinear refines the
clean cases (05→0.94, 4HB→1.08). Density sweep flat both sides. NO 32% bend gap.** Residual is
small, only at extremes (2HB 0.82, 180° hairpin 0.78 — high-strain continuum relaxation).
Fix: `process_bend_battery._fem_linear_bend` now uses arc-span (same as CanDo). The
paper-review-motivated per-segment U→D→R rework was NOT implemented — premise (0.68) was wrong;
bend is already good. **NEW SCORECARD: RMSF ✅, TWIST ✅, BEND ✅ (~0.9, was falsely ❌).**
Everything in the sections below predates this correction — read it as history.

## CONSTANTS ALIGNED TO CANDO + NICK MODEL (2026-07-03)
Set FEM to CanDo submission defaults: `FEM_RISE_PER_BP=0.34` (was NADOC 0.334),
`HELIX_DIAMETER=2.25`, `BP_PER_TURN=10.5`, EA/EI/GJ 1100/230/460, `NICK_FACTOR=0.01`.
Added nick model: `_nick_bps_per_helix` (strand 5'/3' termini) → beams spanning a nick get
bending+torsion ×0.01. **Fixed a real bug:** `assemble_prestress_force` used GLOBAL GJ_DS/EA_DS
for the eigenstrain force → soft (nicked) beams over-twisted; now uses PER-ELEMENT el.gj/el.ea
(a nick relaxes local over-twist = CanDo swivel). Also excluded crossover beams from eigenstrain.
**Effect (with nicks):**
- **BEND IMPROVED 0.38→0.68** (05 59°, 06 97°) — nicks soften helix bending → bundle bends more.
- **TWIST REGRESSED to over-predict** (02 1.32, 07 1.58, 09 1.68; was ~0.9 no-nick) — soft
  torsion + crossover UNDER-DAMPS. RMSF 1.06 (was 0.97).
- **ROOT CAUSE now sharp: the crossover model (stiff finite BEAM) vs CanDo's RIGID zero-length
  link is the remaining gap for BOTH bend (0.68 not 0.95) AND twist damping (over with soft
  helices).** Next: replace the crossover beam with a true rigid link / MPC (u_B=u_A+θ_A×r_AB
  as an exact constraint, not a stiff beam) → should give full bend conversion + restore twist
  damping simultaneously. Tests 9 green; `just test` 3827.

## exp37 — skip→twist LANDSCAPE MAP + sub-1° config (2026-07-05) — `experiments/exp37_cando_skip_twist_map/`
User goal: get 3x6x400 SQ end-to-end twist below 1° (autorefine floored at ~10-15°). Mapped the
FINE-FEM twist/bend/deviation landscape vs skip count on `workspace/3x6x400_Sq_test.nadoc` (18
helices, best-guess 180 skips=10/helix, FINE twist 14.3°). 252 nonlinear solves (~233 s each),
parallelised 8-way (12 cores), checkpointed+watchdog'd. Scripts: `sweep.py` (uniform diagonal +
per-helix axes), `analyze.py`, `stage2_spread.py`, `plot.py`→`results/exp37_summary.png`.
KEY FINDINGS:
- **FEM twist is placement-INDEPENDENT, count is the axis** (probe: <0.2° across
  baseline/even/front/back at fixed count). The ±30° register sensitivity that killed regional
  optimization ([[project_regional_autorefine]]) was an oxDNA-measurement artifact; the
  deterministic FEM makes per-helix skip COUNT a clean, well-defined lever. Overturns the
  "regional not viable" blocker FOR THE FEM ORACLE.
- **ROOT CAUSE of the ~10-15° floor: autorefine minimises deviation RMSD, and RMSD-min ≠
  twist-min.** RMSD valley is at ~10 skips/helix (twist +14°); the twist→0 crossing is ~12.6
  skips/helix. A deviation-driven refiner structurally cannot null twist. Nulling twist costs
  ~0.10 nm RMSD (0.44→0.54) — an intrinsic twist↔deviation tradeoff, not a solver bug.
- **Per-helix authority varies ~4×**: middle row (h_XY_1_0…1_5) ≈ −0.44..−0.52°/skip vs
  corners (0_0,0_5,2_0) ≈ −0.13°/skip (moment-arm + coupling; interior steers hardest).
- **RECOMMENDED sub-1° config `12base+6@13`**: 12 skips on all 18 helices + 13 on the middle row →
  **twist 0.37°, bend 0.33°, rmsd 0.54, 222 skips** (from 14.3°/0.30°/0.44/180). Physical + clean.
  `results/optimized_spread.json`. The auto-greedy `analyze.py` optimum was DEGENERATE (38 skips on
  ONE helix → twist −0.37 but bend 1.66°); the authority-per-rmsd metric over-concentrates — prefer
  the spread search. All proposals are marks only; NOTHING applied to the design (Three-Layer).
- **ACTIONABLE (not yet done):** to make `cando_autorefine` actually null twist, its objective needs
  a twist term (or a fractional-density knob per helix), not just deviation RMSD. Current
  `sweep_skip_period` tunes a single global period against RMSD → lands at the RMSD optimum (~10),
  ~14° short. Offer before implementing.
