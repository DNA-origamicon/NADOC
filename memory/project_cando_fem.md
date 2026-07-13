---
name: project_cando_fem
description: "Native CanDo-replica FEM shape predictor (twist/curvature/RMSF). Phase 0 research DONE — GO w/ conditions. Method spec, reference-data path, phase plan."
metadata: 
  node_type: memory
  type: project
  originSessionId: e1d46763-a32b-48c8-a9b2-03be170aa027
---

# Native CanDo FEM shape predictor

**RESUME HERE →** `experiments/exp36_cando_fem_validation/HANDOFF.md` (scorecard, architecture,
bend-gap diagnosis, PRIORITY CanDo designs to run, next-session plan). This file is the running
log; the HANDOFF is the entry point for a fresh session.

## ⚙ 2026-07-13 — disconnected / ssDNA-connected blocks no longer explode (general)
Symptom: SNUPI "Fine" on VoltronCore "completed" but rendered NOTHING (just axis lines) — the
nonlinear solve had diverged to **mm-scale** coords (rmsf_max ~1384 nm). Root cause: the duplex-core
mesh split into 2 disconnected bodies. A 6-helix sub-block joined to the body ONLY by the SCAFFOLD
threading through single-stranded STUB helices (`h_XY_4_10` scaf-only 4nt, `h_XY_3_10`) — the duplex
FEM can't bridge a connection running through unpaired ssDNA, so the block floated free; the single
centroid pin left it a free rigid body that ran away under the ES repulsion, and the free-free NMA had
6 EXTRA rigid modes → µm RMSF. Two general fixes in `fem_solver.py` (`[[snupi-mimic]]`, shared cando+snupi):
1. **`_add_linker_hops` → `_add_ssdna_hops`** — generalized from LINKER-only to ALL strands: any
   strand (scaffold/staple/linker) that hops meshed-duplex → unmeshed ssDNA → meshed-duplex on a
   DIFFERENT helix now gets a compliant WLC spring (contour = ssDNA run). This TETHERS ssDNA-connected
   blocks (the physical fix). ds-bridge rigid-link case stays LINKER-only (scaffold/staple ds crossings
   are already `Design.crossovers`). Clean fully-duplex bundles gain ZERO springs → validated numerics
   byte-identical (6HB: 0 springs, 1 component — asserted).
2. **Per-component robustness backstop** (`_mesh_component_labels` + `_ensure_components_pinned` in
   `predict_shape`): pin ≥1 node in EVERY connected component (over elements+rigid_links+springs) so no
   free body drifts, and pass `n_rigid = 6·n_components` to the RMSF NMA. Single-component → identical
   to legacy (one centroid pin, n_rigid=6). A spring-tethered block counts as CONNECTED (soft mode, not
   a zero mode) → bounded RMSF. Result: VoltronCore now 1 component, span 51×152×148 nm, rmsf 0.5–4.3 nm.
Tests: `tests/test_cando_linkers.py` (+4: component labels, per-component pin, clean-bundle-unchanged,
slow VoltronCore end-to-end). See [[LESSONS]] (disconnected-block explosion).

Goal: in-app FEM that reproduces CanDo's NONLINEAR predictions (global twist +
curvature + RMSF flexibility) to within a stated tolerance on the loaded design,
ZERO export. Multi-session. Three-Layer Law: FEM output is PHYSICAL/display only.
Motivation: oxDNA/mrDNA CG-MD under-reproduce programmed loop/skip curvature
(mrDNA ~18% of designed bend, plateaus — see [[LESSONS]] A9). CanDo (Bathe lab,
continuum FE) is the experimentally-validated shape/twist/curvature/flexibility tool.

## Phase 0 verdict (2026-07-02): **GO, with two hard conditions**
Deep-research (97-agent, 24/25 claims confirmed) resolved both gate questions.

### CanDo method IS fully specified in primary lit (reimplementable)
Sources: Kim/Kilchherr/Dietz/Bathe NAR 40(7):2862 (2012, PMC3326316); Pan/Sensale/
Arya/Bathe NAR 45(11):6284 (2017, off-lattice); Castro Nat Methods 8:221 (2011).

- **Element**: two-node Hermitian beam (Euler-Bernoulli-class, NOT Timoshenko),
  **one FE node per bp**, 6 DOF/node (3 trans + 3 rot). N nodes → N−1 elements.
- **Constants (verbatim, canonical across all CanDo papers)**: stretch **1100 pN**,
  bend **230 pN·nm²**, twist **460 pN·nm²**. Geometry: **2.25 nm** duplex diameter,
  **10.5 bp/turn** (34.29°/bp) honeycomb / ~10.67 (33.75°/bp) square, **0.34 nm/bp**
  rise. Bend 230 ⇒ L_p ≈ 50–56 nm; twist 460 ⇒ torsional L_p ≈ 112 nm.
  → **NADOC's archived fem_solver.py ALREADY carries EA=1100, EI=230, GJ=460.**
- **CanDo has NO twist-stretch coupling** (isotropic rod). The ~−90 pN·nm coupling
  in the original goal is single-molecule (Gore 2006), NOT CanDo. −277 pN·nm belongs
  to SNUPI (Lee-Kim, ACS Nano 2021), a DISTINCT MD-parameterized 6×6-stiffness model.
  **To match CanDo 1-to-1, do NOT add twist-stretch coupling.** (SNUPI would need
  MD per-step params — different, harder project.)
- **Crossovers** = rigid links of zero length (fix separation + orientation).
  **Nicks** = reduce bending & torsional stiffness ×100 (nick factor 0.01), keep
  full stretch. **ssDNA connections** = nonlinear modified-FJC springs.
  Off-lattice variant instead uses torsional-spring "alignment elements"
  (interhelix 1.85 nm; double-xover 1353/1353/135.3 pN·nm·rad⁻¹ about e1/e2/e3;
  single-xover drops e3 to 13.53).
- **Pre-stress mechanism** (the crux): each element has rest length 0.34 nm + rest
  twist 34.29°/bp. Lattice over/under-twist and Dietz **insertions/deletions
  (loops/skips)** enter as initial strain by deforming duplexes (stretch+twist)
  until crossovers come into spatial register, THEN energy-minimize → stored elastic
  energy drives global twist/curvature. **CAVEAT: exact per-skip → Δrest-length /
  Δrest-twist numeric recipe is NOT verbatim-published** (least-documented step).
  BUT NADOC already has the closed-form Dietz version:
  `loop_skip_calculator.predict_radius_nm` (κ = Σ ΔL_i·r_i / (L_nom·Σ r_i²), ΔL from
  bp×rise) + `predict_global_twist_deg`. Use these as the pre-stress oracle/sanity gate.
- **Solver**: geometrically **NONLINEAR** (finite rotations, large deflection),
  ADINA full-Newton historically; **the live web server now runs Abaqus (since
  2018-03-01)**. Material linear-elastic; the solve is geometrically nonlinear.
  Runtime 5–35 min. ⇒ Phase 3 (corotational/nonlinear beam FE) is genuinely
  required; the archived LINEAR solve cannot reach 90° bends / global twist.
- **RMSF/flexibility** = normal-mode analysis at the minimum, **200 lowest modes**,
  equipartition at **298 K**: RMSF_i ~ Σ_200 (kBT/λ_m)·φ²_{m,i}. Toggleable
  (jobInfo.NMA). (Archived solver already does eigsh shift-invert but only 30 modes,
  centroid-pinned, uncalibrated — bump to 200, validate.)

### Reference-data path EXISTS but is MANUAL + user-dependent (condition 1)
- **cando-dna-origami.org is LIVE (2026)**: 65,384 structures solved, 4,830 users.
  Accepts **caDNAno uploads** (+ off-lattice/Tiamat/CNDO). NADOC already exports
  caDNAno WITH loop/skip arrays (`cadnano.py:813`) → bridge is structurally intact.
- Outputs: **BILD** shape (Chimera), atomic **PDB**, thermal-fluctuation **AVI**,
  delivered as **ZIP by email**. **Interactive-only — NO API / NO batch / NO script.**
- ⇒ **I cannot run CanDo. The USER must** submit each fixture's caDNAno json to the
  web service and hand back the emailed BILD/PDB (+ any twist/curvature/RMSF numbers)
  as Phase-4 reference data. Without this, Phase-4 validation is impossible (NO-GO).

### Solver is NOT vendorable (condition on effort)
Only public Bathe-lab repo = **lcbb/Off-Lattice-CanDo** = MATLAB pre/post-proc that
shells out to proprietary **ADINA**; beam formulation + Newton solve are closed.
DAEDALUS/PERDIX/TALOS/METIS/ATHENA are routing/sequence-design tools — no mechanical
solve. ⇒ must **reimplement** the geometrically-nonlinear beam FE + NMA in-house
(Phase 3 is the real engineering).

### What "1-to-1" can mean (condition 2)
The reference is a **proprietary black-box (Abaqus)** with unpublished tolerances,
an under-documented pre-stress recipe, and an ADINA→Abaqus switch. **Bit-exact
reproduction is not provably attainable.** Near-quantitative agreement (twist &
bend within a few %, small shape RMSD, RMSF pattern correlation) IS attainable —
same beam model, same published constants. So "1-to-1" must be a **stated
tolerance**, per the user's own Phase-4 wording.

## Open questions to resolve before/within later phases
1. Exact per-skip/loop → Δrest-length/Δrest-twist mapping (use NADOC analytic as
   oracle; may need to inspect Off-Lattice-CanDo .inp generation or contact Bathe lab).
2. Do HC vs SQ change any modulus, or only ground-state twist/bp + interhelix spacing? (likely latter)
3. ADINA vs Abaqus convergence differences vs the live server output.
4. Quantitative validation table (Dietz 2009 twisted bundles/curved beams/gears,
   6-helix bundle: twist °/turn, radius nm, RMSF) — pull from Castro 2011 / Kim 2012
   supplementary; not captured in the research pass.

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

## exp37 FOLLOW-UP — twist objective WIRED INTO autorefine (2026-07-05)
Acting on exp37, changed `cando_autorefine.fem_refine` so the **SQUARE** path optimises end-to-end
TWIST relative to the design's INTENDED twist (`_twist_error` = |FEM twist − target["twist_deg"]|,
differential so the lattice offset cancels + it generalises to programmed-twist designs), NOT the
deviation RMSD (which bottoms at a lower density → floored twist at ~10-15°).
- `fem_measure` now returns `twist_deg`/`bend_deg` (off the cached solve).
- `sweep_skip_period(cost_fn=…)` — pluggable objective; default RMSD (back-compat), square passes a
  twist-error cost → sweeps to the twist-nulling density.
- `_fractional_twist_bump` — fractional per-helix density: measures ∂twist/∂skip authority per helix,
  bumps highest-authority helices by ±1 skip toward target until |twist−target|<`TWIST_TOL_DEG`(=1°).
  Mirrors the exp37 "spread" winner (bump the middle row). Placement even/off-forbidden; no geometric
  reasoning (authority MEASURED, bumps empirically kept — [[feedback_crossover_no_reasoning]]).
- `fem_refine` result gained `objective` ("twist"|"deviation"), `twist_target/before/after`,
  `twist_tol`, `authority` (per-helix map). HONEYCOMB path UNCHANGED (deviation greedy) — full
  coupled twist+bend objective for honeycomb is the generalisation plan.
- **`cando_runner` apply gate FIXED**: was `after_rmsd < before_rmsd` → would REJECT the twist-optimal
  program (rmsd RISES as twist→0). Now square gates on twist-error improvement; note shows
  twist before→after. New job fields `refine_twist_before/after/target`.
- Tests updated to the twist contract: `test_cando_autorefine.py` (square strut nulls twist +
  authority map), `automation_harness.assert_fem_autorefine_relieves_twist` (asserts twist relief for
  square, rmsd relief for honeycomb), `test_cando_autorefine_validation.py`. Smoke (200bp 6HB SQ):
  twist 58.1°→0.67°, 37 skips, off-forbidden, authority for 6 helices.
- **Generalisation plan** (coupled twist+bend Jacobian objective; hollow-tube authority-vs-geometry
  law; asymmetric-section coupling stress test; 1×N twist-degeneracy guard; symmetry-orbit scaling):
  `experiments/exp37_cando_skip_twist_map/GENERALIZATION.md`.

## Generalization progress (2026-07-05) — G1 done, G2 done
- **G1 (exp38, `experiments/exp38_coupled_shape_jacobian/`) — coupled (twist,bend) Jacobian VALIDATED.**
  On honeycomb bend designs a per-helix skip moves BOTH twist and bend; bend authority varies by
  cross-section position (bimetallic: inner vs outer bend opposite), twist authority ~uniform → the
  2×H Jacobian is well-conditioned. Ridge least-squares solve recovered an under-realized 60° bend
  25.7°→49.7° (err 28°→4°, twist err <0.5°) in ONE iter, discovering inner-loops/outer-skips from the
  Jacobian alone. Algorithm validated; NOT yet wired into `fem_refine` honeycomb path (deviation greedy
  still live). Next code step: `_solve_shape_targets` replacing the honeycomb branch.
- **G2 (exp39, `experiments/exp39_hollow_tube_authority/`) — authority-vs-geometry law.** Hollow SQ
  tubes d3–d6 route CLEANLY (single scaffold, no across-hollow crossovers, full mesh); audit flagged a
  mis-routed solid 3×3 (2 scaffolds). Twist authority ∝ ~1/(N·r) (steers less as section grows); bend
  authority ∝ moment arm but noise-limited on symmetric/large tubes (scalar arc-bend ~0.6° floor).
  VERDICT: geometry predicts the trend, not accurate per-helix numbers → keep the in-loop Jacobian for
  accuracy, use geometry as a seed; symmetry-orbit grouping (G5) for scale. **Autostaple caveat: basic
  auto_scaffold can leave DISJOINT scaffolds (solid 3×3 → 2); auto_break nicks land on crossovers on
  ALL square bundles — audit every headless-generated bundle before trusting its FEM numbers.**
- Remaining: wire G1 `_solve_shape_targets` into honeycomb `fem_refine`; G3 asymmetric sections
  (bigger/cleaner bend signal + multi-skip bend probe); G4 1×N twist-degeneracy guard; G5 scale.

## Generalization G3 + G4 (2026-07-05) — both plan-refining (partly negative)
- **G3 (exp40) — coupled objective's domain narrowed.** auto_scaffold FAILED to route strong-asymmetry
  cross-sections (L→2 scaffolds, staircase triangle→10; audit flagged+skipped). Only notch_4x4 routed.
  On the notch (straight strut) register→bend coupling is weak (~0.9° bend, near noise) → 1D twist-null
  already suffices; forcing the 2D coupled solve on a sub-noise bend row makes it slightly WORSE.
  ⇒ **Use the coupled (twist,bend) solve only when the design has an intended bend above the ~0.6°
  arc-bend noise floor (i.e. programmed-shape designs, per G1); twist-only for straight struts.**
  Strong-asymmetry study is BLOCKED on the auto-scaffold routing bug → handoff prompt at
  `experiments/exp40_asymmetric_coupling/ASYMMETRIC_SCAFFOLD_HANDOFF.md` (asymmetric shapes route to
  disjoint scaffolds; seamed_router Hamiltonian path fails; read project_autoscaffold_single_strand).
- **G4 (exp41) — 1×N twist-degeneracy hypothesis REFUTED (no guard needed).** 1×N is rank-1 colinear
  (SVD sv2=0) BUT measure_bundle_twist tracks the ribbon helicoid twist fine and the autorefine drives
  68°→1.5° correctly. Pipeline is more robust than the plan assumed. Only caveat (untested): sign
  ambiguity for an INTENDED-nonzero-twist symmetric ribbon; nulling to 0 unaffected. 2×N fully fine.
- **Net generalization status:** G1 coupled solve validated (programmed bend+twist). G2 authority∝geometry
  trend (seed only). G3 → coupled solve gated on intended-bend>noise; asymmetric auto-routing is the
  blocker. G4 → no 1×N guard needed. **Still unwired: G1 `_solve_shape_targets` into honeycomb fem_refine**
  (the one live-code step); G5 (symmetry-orbit scaling) open.
- **G3 asymmetric-auto-routing blocker CHARACTERIZED + GUARDED (2026-07-05).** Why some asymmetric SQ
  sections gave the FEM disjoint scaffolds = garbage authority: the SEAMED router silently fragments TWO
  shape classes. (A) **odd helix group** — the step-2 pairing `(0,1)(2,3)…`+`(1,2)(3,4)…` orphans `path[n-1]`
  (3×3→8+1, L→6+1); a Ham path EXISTS, it's a parity bug. (B) **no Hamiltonian path** in the *crossover*-
  adjacency graph (staircase triangle → `brute_ham=False`) → whole group skipped → every helix its own
  scaffold. Predictor = Hamiltonicity of the *crossover* graph + helix-count parity — NOT cell-grid
  cut-vertices (red herring: L has 5 yet its xover graph is a clean path). **SEAMLESS handles odd fine**
  (zig-zag pairing) → guard is seamed/matched-only. **Shipped guard:** `seamed_router.seamed_routability_errors`
  (pure; skips forced-ligation + multisection = out of scope) → `routes_scaffold_routing._guard_seamed_routable`
  raises 422 BEFORE any mutation on the seamed+matched endpoints → frontend toasts it (picker already wired,
  no FE change). For the CanDo battery: **route asymmetric sections SEAMLESS, or keep even-helix Hamiltonian
  sections.** Detail in [[project_autoscaffold_single_strand]].

## G1 WIRED into fem_refine honeycomb path (2026-07-05)
`_solve_shape_targets` (cando_autorefine.py) — the exp38 coupled solve, productionized: measured 2×H
authority Jacobian (∂twist,∂bend per helix; multi-skip probe ÷count), ridge least-squares toward
(twist_target, bend_target), integer per-helix deltas (skips x>0 / loops x<0), keep-if-combined-error-
drops. `fem_refine` HONEYCOMB branch now: `objective="shape"` via the coupled solve WHEN the design
has a real shape target (`use_bend_target`: |intended bend| > `BEND_TARGET_FLOOR_DEG`=3° — the exp40
G3 gate — OR twist beyond tol); else falls back to the deviation greedy (`objective="deviation"`,
straight/weak-target, unchanged). Square path unchanged (`objective="twist"`).
- Result gained `bend_target/before/after`, `bend_tol`; `authority` for shape = `{helix:[∂tw,∂bd]}`.
- `cando_runner` apply-gate handles "shape" (combined twist+bend error; RMSD rises as shape is hit);
  note shows twist AND bend before→after. Job fields `refine_bend_before/after/target`.
- Constants: `BEND_TOL_DEG`=3, `BEND_TARGET_FLOOR_DEG`=3.
- Verified: honeycomb under-realized 60° bend → bend 25.7°→54.0° (target 53.6°), objective=shape,
  28 marks, authority for 6 helices; STRAIGHT honeycomb → objective=deviation, 0 edits (no harm).
  Tests: `test_refine_honeycomb_shape_hits_bend_and_places_marks_off_forbidden` (replaces the old
  rmsd-never-rises test); affected suite 27 green. **NOT hand-verified in the CanDo panel** (the note
  carries twist+bend; frontend shows refine_note unchanged — bend-specific UI is optional follow-up).
- Generalization: G1 wired, G2/G3/G4 done, **G5 (symmetry-orbit probe scaling) still open**.

## ANCHORS — Dirichlet BC (2026-07-06, sim-coverage task C1)
The FEM shape solve can now be run with **anchors** (a physical tether held fixed), the CanDo
analogue of a boundary condition. Backend-only; anchors are a JOB-REQUEST annotation, never a
`Design`/topology edit (Three-Layer Law).
- `apply_boundary_conditions(K, f, mesh, fixed_nodes=None)` — pins all 6 DOF of each `fixed_nodes`
  index (Dirichlet); `None` **or an empty list** falls back to the legacy centroid pin (an anchor
  selection that resolved to nothing never makes the system singular).
- `solve_prestress_shape(..., fixed_nodes=None)` clamps them at every corotational load step → the
  anchored region stays exactly at rest while the rest deflects under the loop/skip eigenstrain.
- `resolve_anchor_nodes(design, mesh, anchors)` — reuses the **shared oxDNA scope resolver**
  (`oxdna_interface.resolve_anchor_particles`: overhang/cluster/domain/strand/base) → per-nucleotide
  `(helix,bp,dir)` keys, collapsed onto the single duplex-core axis node per bp (both strands → one
  node). Out-of-core nts (ssDNA ends, extra-base inserts) drop silently.
- `predict_shape(design, *, anchors=None)` threads anchors through both the nonlinear and linear
  paths and returns `anchor_keys: [[helix_id, bp], …]`. RMSF stays the free-free NMA regardless
  (intrinsic flexibility; anchoring the RMSF is a possible later refinement, not needed by C1).
- Oracle `tests/test_cando_anchors.py` (10 fast): synthetic beam pins held & free tip moves under a
  test load; resolver maps base/cluster scopes & drops stale; prestress solve holds the anchored node
  exactly while the rest deflects; unresolved anchor is a no-op (positions identical, free-free RMSF
  preserved). Anchors are the substrate for **C2** (E-field deflection needs an anchor to hold against).

> **History.** Derivations, the superseded bend-gap diagnosis + rigid-link MPC investigation live in [project_cando_fem_archive.md](project_cando_fem_archive.md). Read on demand only.
