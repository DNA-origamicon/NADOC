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

## CanDo reference-data battery — first wave GENERATED (2026-07-02)
`workspace/cando validation/` — 6 designs, all **6HB honeycomb, 210 bp/helix**, single
M13 scaffold, 122 xovers, uniform routing (only loop/skip program varies). Each has a
`.nadoc` (inspect) + `.cadnano.json` (**the CanDo upload artifact**), plus
`EXPECTED_VALUES.md` (submission steps + calibration targets) and `_manifest.json`.
Generator: `scratchpad/gen_cando_battery.py` (create_bundle → auto_scaffold(seamed) →
auto_crossover → auto_break → add_twist/add_bend → apply_loop_skip_deformations →
export). All 6 built cleanly → **nothing added to the automation ledger.**

| file | program | marks L/S | NADOC twist | NADOC R |
|---|---|---|---|---|
| 01_control_straight | none | 0/0 | 0° | ∞ |
| 02_twist_half_turn | uniform skips | 0/30 | +171.4° | ∞ |
| 03_twist_full_turn | uniform skips | 0/60 | +342.9° | ∞ |
| 04_twist_opposite | uniform loops | 30/0 | −171.4° | ∞ |
| 05_bend_90 | gradient | 18/18 | 0° | 45.5 nm |
| 06_bend_180 | gradient | 36/36 | 0° | 22.7 nm |

Physics confirmed at gen: uniform marks → pure twist (bend cancels); gradient → pure
bend (twist cancels), R matches predict_radius_nm. **USER runs these through
cando-dna-origami.org (fine model + NMA on); hands back BILD/PDB + B-factors** →
Phase-4 reference. Three-way check: NADOC-analytic ↔ NADOC-FEM ↔ CanDo.
Follow-on waves (2: 18HB+square cross-section; 3: 2× length; 4: RMSF hinge) NOT yet built.

**Gotcha found:** `full_autostaple` does NOT route the scaffold into one strand (assumes
already routed) → leaves 6 disjoint scaffolds. Must call `auto_scaffold` first for a
single snaking scaffold (CanDo needs it). Realize loop/skips AFTER auto_break so
autostaple never sees non-uniform cells (dodges the Phase-7 non-uniform-cell concern).

## Analysis pipeline + FIRST CanDo RESULT (2026-07-03) — `experiments/exp36_cando_fem_validation/`
`analyze_cando_pdb.py` (analyser) + `gen_cando_battery.py` (regen). CanDo atomic ZIP =
`structure_multimodel.pdb` + 3 PNGs. **31 MODELS: MODEL 1 = full equilibrium structure
(chain A, ~1 C1'/bp), MODELS 2–31 = per-strand split → parse MODEL 1.** Coords in Å.
**B-factors ZERO → no RMSF in the atomic PDB;** RMSF needs NMA on + likely a separate
output file. Robust bend = arc-span + chord+sagitta on the polar-ordered
cross-section-centroid centerline (must agree; got 0.25°). **Discarded as non-robust
(A9): turning-angle integral (→788°), straight-axis slab binning (→42°, biased low).**

**05_bend_90 FINAL (honeycomb, lattice-matched): CanDo bend = 85.8° (R=46.4 nm) vs NADOC
analytic 90° (R=45.5 nm) → 95% of ideal, radius within 2%.** Atomic PDB (85.7°) ≈ coarse
BILD (86.0°) to 0.3°. **The earlier 72.5°/54.6nm was a LATTICE ARTIFACT** — first run was
submitted as SQUARE (CanDo form default) but design is HONEYCOMB; hex→rect remap of
moment-arms caused ~15° of the apparent gap. **LESSON: CanDo submission lattice MUST match
the design — check readme.txt "File type".** caDNAno legacy JSON stores no lattice, so the
CanDo web form decides. Our export is correct (self-detects HC). Residual ~4° (86 vs 90) =
genuine continuum relaxation, small for a gentle bend; expect larger on 06 hairpin.
RMSF present in coarse zip (`structure_NMA_RMSF.txt`, 0.50–1.37 nm, ends floppy). NADOC-FEM
target for 05 = ~86°.

**Batch 2 (2026-07-03) — CanDo labels SCRAMBLED; identify by content (node count=bp,
definitive: +30→04, −30→02, −60→03, net-0 split by planarity/bend).** Zips labeled
01/02/03/05 are ACTUALLY **01, 04, 06, 05**. PRESENT: 01,04,05,06. **MISSING: real 02 & 03**
(the deletion/positive-twist designs). **06_bend_180: CanDo 166°/R24.1 vs analytic 180°/22.7
→ 92%.** Bend calibration: 05→95%, 06→92% (relaxation grows with strain). Control (01) reads
twist≈0 ✓. **Twist-magnitude estimator STILL UNSOLVED** — global proxies alias with the
backbone spiral (70–168° spread); need per-helix-centroid azimuth tracker before any twist
number is trustworthy. Bend pipeline solid. Fingerprint/analysis in exp36 README.

**Two ZIPs per CanDo job:** `*_atomic.zip` (multimodel PDB, B-factors ZERO) + `*.zip`
coarse (RMSF txt HERE, deformedShape.bild=cleanest geometry, **structure_NLSA.inp=the
Abaqus deck**). Deck CONFIRMS EA=1100/EI=230/GJ=460 (Å units) + reveals:
**pre-stress = TEMPERATURE eigenstrain + prescribed disp→register, then staged nlgeom
relaxation (InitialDisp→HJgen→Unloding1-6 w/ *Temperature op=mod→NMA).** Elements: B31H
(hybrid Timoshenko), NICKDNA (I,J÷100), HJ (crossover beams), CONN3D2 (ssDNA nonlinear).
This is the exact Phase-2/3 blueprint. Pending CanDo (re-run honeycomb): 01,02,03,04,06.

## FULL BATTERY EXTRACTED (2026-07-03) — calibration targets in
`experiments/exp36_cando_fem_validation/cando_reference_values.json`. All 6 zips present,
correctly labeled, honeycomb.
**KEY FINDING: CanDo reproduces BEND ~95% of naive analytic but TWIST only ~25-36%.**
- Bends: 05→86.9°/R45.9 (0.97), 06→170.1°/R23.4 (0.94). Tight, well-measured.
- Twists: 02(30skips)→~45° (analytic 171, 0.26), 03(60skips)→~87° (0.25), 04(30loops)→~62°
  (0.36). Measured via 6-fold order param on coarse axis nodes (|Z|~0.9, linear ψ profile,
  control=0 ✓; scales w/ count 02:03≈1:2 ✓; abs sign frame-arbitrary; ±15% method unc).
- **Why:** analytic 34.3°/deletion is SINGLE-HELIX; the 6-helix crossover-coupled bundle's
  torsional coupling strongly resists global twist. The FEM MUST reproduce this bend/twist
  ASYMMETRY (near-full bend, heavily-damped twist) — naive analytic can't. This is THE
  Phase-2/3 calibration signal.
- RMSF (all designs, `structure_NMA_RMSF.txt`): ~0.4–1.7 nm, stiff core→floppy ends.
Twist estimator lives inline (6-fold on BILD axis nodes); tube-follower fragile at high
winding — use 6-fold.

**CROSS-SECTION SCALING (2026-07-03, structures 07/08/09):** at SAME 5-skips/helix
(analytic 171° for all), CanDo twist DROPS with size: **2HB=84° (0.49), 6HB=45° (0.26),
18HB=23° (0.14)** — halves as helix count triples. 18HB straight (08) reads 0° ✓ (validates
measure). Tube-following (kmeans nh clusters + per-helix azimuth slope) is robust at LOW
twist (these) — agrees with m=6 order param on 18HB (23.2 vs 23.7). 2HB needs 2-tube (m-fold
degenerate). Naive analytic is cross-section-BLIND → only FE captures this. 2HB anchors GJ;
6/18HB pin coupling scaling. **10_18hb_bend NOT returned (missing zip) — user to resubmit.**
**CYCLIC-STAPLE NOTE:** user saw cyclic staples in caDNAno for 2HB/18HB, added nicks +
re-sequenced before submit. BUT our `.cadnano.json` traces provably LINEAR (every staple
5'→3', 0 cycles) — discrepancy is caDNAno-side import/render, not our file. Submitted
topology has user's extra nicks → global twist trend robust, but exact per-design FEM
matching wants the user's submitted files (ASK). Values in cando_reference_values.json.

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

## BEND-GAP DIAGNOSIS — coupling RULED OUT both ways (2026-07-03, exp36)
Two independent tests converge: **the bend gap is NOT inter-helix coupling.**
- **CanDo `05.inp` element census:** 1225 BDNA + 33 NICKDNA + **117 HJ crossover beams** +
  5 ssDNA connectors (1264 nodes). **117 HJ ≈ our 122 crossovers → CanDo is NOT more
  coupled than us.** HJ = finite-length **compliant B31H beams** (span 2.25–3.8 nm, DNA
  section EI=230/GJ=460), not rigid links.
- **In-code dense-coupling test** (`fem_bend_diagnostics.py`): adding a rigid link at EVERY
  duplex bp between adjacent helices (+1140 links, 10× coupling) changes the bend by <1°
  (05: 61.2→60.4°; 06: 99.5→98.6°). **More coupling does nothing.**
- **Energy partition:** **67% of the eigenstrain strain-energy relieves as internal AXIAL
  stretch**, only 33% into bend+torsion (05 & 06 both). This is the dominant loss channel.
- ⇒ **The fix is the eigenstrain→CURVATURE formulation, not coupling / not nonlinearity.**
  Current `assemble_prestress_force` applies loop/skip as opposing AXIAL nodal forces
  (±N0=EA·δ0/L); across the cross-section these SHOULD make a bimetallic moment but 2/3 of
  the energy bleeds into uniform axial strain of the bundle. NEXT: impose the differential
  as a rest-CURVATURE (bending eigenstrain / rest-angle per element) directly, rather than
  as axial end-forces that partly cancel into stretch. Linear bend 05=61°(0.70)/06=100°(0.58).

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

## BEND-GAP DIAGNOSIS (SUPERSEDED by the correction above) — CanDo results in (2026-07-03, exp36)
User ran B1–B4 (B5 excluded: SQ routing error bp159 H0→H1, separate session). Measured via
`process_bend_battery.py`; full table in `bend_diagnostics_results.md`.
**ANSWER to the plan's central question: CanDo bend is crossover-density-INDEPENDENT.**
- **B1 sweep decisive:** CanDo bend FLAT 86.5→86.4→89.5° as staple crossovers drop
  112→56→28 (4× coupling cut, <3° change). `minimal` (1 xo) = degenerate collapse (disconnected
  6HB, planarity 0.64, RMSF 1144nm) → discard.
- **CanDo is a near-ideal LINEAR converter, ratio ≈0.95 FLAT** across angle (B2: 30–135° →
  0.94–1.04), length (B3: 210/420 → 0.92–0.96), cross-section (B4: 4HB 0.95, 6HB 0.96; only
  2HB dips to 0.84). Programmed bend ≈ realized to ~5%.
- **Our FEM ~0.68 AND deficit GROWS with strain** (angle 0.74→0.63, length 0.79→0.55) =
  the axial-relief fingerprint (67% eigenstrain energy → stretch).
- ⇒ Coupling refuted 3 ways (census 117≈122, dense-coupling <1°, CanDo sweep flat).
- **REST-CURVATURE FIX TRIED + REJECTED (2026-07-03).** Reworked `assemble_prestress_force`
  to route the differential into a composite rest-curvature (bending moments). The κ geometry
  is EXACT (05 → R=45.2 vs analytic 45.5) BUT applying κ as per-element moments only leaves
  net END-COUPLES after assembly, which a long crossover-coupled bundle can't transmit into a
  uniform curvature → topology/length-dependent UNDER-conversion (6HB 0.62, 4HB 0.42, 420bp
  0.32; self-cal factor 1.6–3.2, not constant). WORSE than axial. **Reverted** solver to the
  validated axial+torsion eigenstrain (0.68). `just test` green (see below).
- **REFINED CONCLUSION: the bend gap is in the discrete STIFFNESS RESPONSE, not the eigenstrain
  LOAD.** The axial eigenstrain already applies the correct section moment M*=ΣEA·ε·r; the
  discrete crossover-coupled beam just responds more compliantly (more axial relief) than
  CanDo's continuum plane-section B31H. **Real fix (dedicated session) = a STIFFNESS change:
  enforce plane-sections** — rigid cross-section MPC tying ALL helices at a station (pairwise
  rigid links don't rigidify, per dense-link test), OR add B31H inter-helix shear/warping
  stiffness. Gate: bend→~0.95 flat across B1/B2/B3/B4 AND twist(0.26)+RMSF unmoved.
  Details: `experiments/exp36/bend_diagnostics_results.md`.

## CanDo bend-gap BATTERY generated (2026-07-03) — SUBMITTED, results above
`gen_bend_diagnostics.py` → 15 designs `B1_*`…`B5_*` in `workspace/cando validation/`,
submission guide `BEND_DIAGNOSTICS_SUBMISSION.md` (honeycomb+fine+NMA; B5=square). All
verified caDNAno-level: single scaffold, **0 marks on crossovers/ends**
([[feedback_loopskip_no_crossover_ends]]), `?`-free CSV. Families: **B1** staple-crossover
density sweep at fixed 90° bend (112/56/28/1 — THE decisive run; .inp predicts CanDo bend
stays ~87° since coupling isn't the lever), **B2** angle series 30/45/60/90/135°, **B3**
length series at fixed R≈45nm (105/210/420bp = 45/90/180°), **B4** 2HB+4HB, **B5** SQ
(confounded by ~149° intrinsic SQ-correction twist). Generator reuses the proven route +
adds staple-crossover thinning (by process_id) + an off-crossover/off-end mark-relocation
pass (core realizers still don't self-enforce the rule).

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

## RIGID-LINK MPC + eigenstrain diagnostics (2026-07-03) — hypotheses RULED OUT
Replaced the stiff crossover beam with a TRUE rigid link (`FEMRigidLink`, penalty on the exact
constraint Cd=0: u_j−u_i+skew(r)θ_i=0, θ_j−θ_i=0). **NUMERICALLY IDENTICAL to the stiff beam**
(bend 0.68, twist 1.3-1.7, RMSF 1.06) → beam was already effectively rigid; **crossover model is
NOT the bottleneck.** Ruled out: bend is **purely AXIAL-driven** (axial-only 59.5° = both 59.3°;
torsion-only 0.8°); eigenstrain net force is **exactly 0** per-helix + total (no net-force bug);
bend insensitive to crossover stiffness AND rigid-vs-beam. **So the bend gap (0.68 vs 0.95) is the
AXIAL→BEND CONVERSION EFFICIENCY** — ~32% of the differential relieves as internal axial strain
(even net-0 middle helices "stretch" +6nm via coupling). Likely SHEAR-LAG between discrete
crossovers (helices slide axially between crossover points); CanDo may couple duplex shear more.
OPEN. Added `axial=/torsion=` toggles to `assemble_prestress_force`. Tests 9 green; `just test` 3827.
**Net vs CanDo: RMSF ✅~1.0, TWIST ✅(no-nick)/over(nick), BEND 0.68 (open: shear-lag).**
- P2b pre-stress (axial ΔL from ins/del + torsional from over/under-twist & ins/del)
  + calibrate to CanDo constants; GATE: linear small/moderate bends match
  predict_radius_nm in direction AND magnitude. (NO twist-stretch coupling.)
- P3 geometric nonlinearity — corotational 3D beam + Newton-Raphson w/ load-stepping
  (REQUIRED for 90° bends + global twist).
- P4 validate vs REAL CanDo (user-supplied reference); iterate to stated tolerance.
- P5 in-app "Predict shape (FEM)" — **entry point SHIPPED 2026-07-03**:
  `fem_solver.predict_shape(design, nonlinear=True, n_steps=20, with_rmsf=True)` → deformed
  positions + per-bp RMSF; **nonlinear solve is the default** (validated ~0.95 vs CanDo; linear
  ~0.92 for fast preview). Display-only (Three-Layer). Test green; `just test` passing.
  **Full Phase-5 feature handoff (4 items — dynamics panel / viz-cylinder toggle / flex+
  deviation maps / CanDo-oracle autorefine) in `experiments/exp36/HANDOFF.md §7`**, each mapped
  to the oxDNA/mrDNA module to mirror (`cando_job.py`←oxdna_job, `cando_jobs_panel.js`←
  oxdna_jobs_panel, `oxdna_display`/`oxdna_metrics_card`, `routes_autorefine`). Zero export.

### P5 Item 1 — Dynamics-tab CanDo FEM job panel **SHIPPED 2026-07-03**
Full jobs-list + Coarse/Fine + Advanced + detail/stop/delete panel, mirroring the mrDNA
section but radically simpler (FEM is in-process scipy — **no subprocess, no GPU, no
availability probe**; the two "engines" are the solver modes). New modules:
- `backend/core/cando_job.py` — `CandoJob` (persist to `workspace/cando_jobs/{id}/job.json`),
  `new_cando_job`. Params: `nonlinear` (Fine/Coarse), `n_steps`, `with_rmsf`. Archival parity.
- `backend/core/cando_runner.py` — daemon-thread lifecycle: snapshot `design.json` → run
  `predict_shape` → cache `display.json` (positions) + `rmsf.json` → completed. `stop` is
  best-effort (scipy solve can't be interrupted mid-way → flag, finish, discard). Progress =
  time estimate. `reconcile_cando_status` recovers orphaned running jobs after a `--reload`.
- `backend/api/routes_cando.py` (registered in `main.py`) — `/api/cando/{available,jobs,...,
  jobs/{id}/{progress,start,stop,display,rmsf,error-log}}`. `/available` always true.
- `frontend/src/ui/cando_jobs_panel.js` (`initCandoJobsPanel({candoDisplay,getWorkspacePath})`)
  + HTML block `#cando-jobs-panel` in `index.html` + client fns (`candoAvailable`…`getCandoRmsf`)
  + thin `main.js` init (`candoDisplay:null` until Item 2). Pure helpers unit-tested
  (`cando_jobs_panel.test.js`, 15). Backend `tests/test_cando_job.py` (5).
- **BUG FIXED (shared latent w/ mrdna):** `_run_job` now sets `job.status=running` (not just
  the stage) at solve start, so the panel's progress bar + ETA (gated on status==running) light
  up during the run. mrdna/oxdna autostart leaves status=queued — cando is strictly more correct.
- **PERF NOTE:** on a real ~1200-node design (6hb_curved) the **200-mode RMSF NMA dominates**
  — linear+RMSF ~41s standalone, linear-only ~4s. So `with_rmsf` off = a genuine fast preview;
  Fine (nonlinear)+RMSF is a background job. Advanced exposes `n_steps` + `with_rmsf`.
- **DEFERRED in Item 1:** EA/EI/GJ/NICK_FACTOR advanced params (handoff asked for them) — they
  are module-level constants in `fem_solver`; threading per-job overrides is a solver change that
  risks the exp36 calibration, so left out (only `n_steps`+`with_rmsf` exposed). Deform display
  toggle present but disabled (wired by Item 2's `candoDisplay`). No `physics-fem.md` rule created
  (planned in MEMORY.md but doesn't exist; routes already scoped by `api-and-state.md`).
- **NOT hand-driven in a browser** — full lifecycle verified over HTTP vs the live server
  (create→run→complete→display→rmsf→list→delete, status/progress/ETA correct); the button/DOM
  gesture path is unexercised in a real browser (MV pending).
- **DOUBLE-CLICK GUARD 2026-07-04 (user-reported crash):** clicking Coarse/Fine twice fast
  spawned TWO jobs → crash. `confirmNoConcurrentJob` can't gate the FEM (it only knows MD/oxDNA
  jobs; the FEM is in-process), and the old `_launch` awaited the confirm BEFORE disabling the
  buttons, so both clicks slipped through. Fix in `cando_jobs_panel.js`: synchronous `_launching`
  re-entrancy flag set before any await + pure `launchBlocked(launching, jobs, selectedJob)` that
  keeps both buttons disabled until NO CanDo job is active; `_fetchJobs`' poll re-enables when the
  job finishes. Tests: `launchBlocked` unit (4) + `cando_jobs_panel.launch_guard.test.js` (jsdom
  integration — double-click `.click()` → exactly 1 `createCandoJob`; re-enable after completed).
  Verified at gesture level in jsdom (real-browser click still MV-pending).

### P5 Item 2 — "Predicted shape (deform model)" toggle **SHIPPED 2026-07-04**
Deform-only viz toggle: turning it on deforms the NADOC model to the FEM-predicted positions;
off restores native. New `frontend/src/ui/cando_display.js` (`initCandoDisplay({designRenderer,
api})`) — a stripped sibling of `mrdna_display.js` (no CG-beads mode; the FEM has no bead cloud).
Exposes exactly the `candoDisplay` interface the Item-1 panel already called: `showDeform(id)`
(→`api.getCandoDisplay`→`toFemUpdates`→`designRenderer.applyFemPositions`), `stopDeform()`
(→`applyFemPositions(null)`), `stopAndRestore()`, `deformActive()`, `deformJobId()`. Coarse+Fine
share the deform path (mode is baked into the cached positions). Wired in `main.js` (`const
candoDisplay = initCandoDisplay({designRenderer, api})` replacing the `null` placeholder — +1
import +1 init line, pure wiring, main.js cohesive LOC flat). **Three-Layer: display-only.**
- Tests: `cando_display.test.js` (6 vitest — verbatim lift of exercised mrdna deform logic).
  `just test-frontend` green (2038); `just smoke` green (23).
- **VERIFIED IN APP:** 6hb_curved → panel Coarse → completed (1182 nodes) → toggle ON → status
  "Showing: model deformed" → OFF → cleared; no JS console errors. Backend display also HTTP-proven
  (2364 positions, correct shape). One-off gesture e2e used then removed (E2E = troubleshooting-only).
- **Item-2 original "cylinders" spec SUPERSEDED:** the shipped Item-1 panel committed to a
  deform-in-place toggle, so Item 2 = applyFemPositions swap (same mechanism as mrDNA), not new
  cylinder geometry. Simpler + reuses the shared FEM-position display path.
- **BUGFIX 2026-07-04 — stranded ssDNA ends + loop bases (user-reported, w/ screenshot).** The
  first Item-2 ship stranded every non-duplex-core nucleotide: `deformed_positions` emitted ONLY
  FEM mesh nodes (duplex core), so ssDNA scaffold ends + loop/skip inserted bases got no
  displacement and stayed at native while the duplex swung to the bent shape → bonds stretched
  across the gap (long fanning lines off the ends; centroid-pinned solve, so no global shift —
  just the bend stranding the ends). **My earlier "verified in app" was a FALSE PASS** — the e2e
  asserted only the panel's "model deformed" status text, never the actual render (and the smoke-
  config runs showed "No active design" — multi-doc: design never loaded into the page's doc).
  Lesson: status text ≠ visual correctness; drive a doc-pinned load (`?doc=` + `X-NADOC-Doc`) and
  screenshot. **Fix:** `deformed_positions` now mirrors mrDNA's `_display_positions` gap-fill —
  iterate EVERY nucleotide; covered bp → its FEM displacement; uncovered (ss end / loop) → ride
  along the nearest FEM-covered bp in the same helix (nearest by bp index). Full coverage: on
  6hb_curved the display went 2364→2536 positions (== all rendered nucleotides). Display-only,
  purely geometric, mirrors a shipped/validated pattern (no new topology reasoning). **Validation
  (the user's ask):** new `test_predict_shape_covers_every_nucleotide_no_stranded_ssdna_or_loops`
  asserts `predict_shape().positions` key-set == every nucleotide key (would've failed on the old
  mesh-nodes-only output); `test_cando_job` count assertion relaxed `==2*n_nodes` → `>=2*n_nodes`
  (old exact-equality encoded the bug). `just test` 3834 passed. **VISUALLY re-verified** on
  6hb_curved (doc-pinned dev-server screenshots OFF vs ON): deformed bundle moves coherently, no
  stranded fanning lines; the residual grey/blue straight lines are native scaffold arcs (present
  in OFF too).
- **EDGE CASE FIXED 2026-07-04:** `predict_shape` on a duplex-free design (0 FEM mesh nodes — e.g.
  the e2e's lone unpaired scaffold, or any all-ssDNA design) crashed with a cryptic
  `AxisError: axis 1 is out of bounds` — `apply_boundary_conditions` did `norm(positions-centroid,
  axis=1)` on an empty (1-D) positions array. Now `predict_shape` guards `len(mesh.nodes) <
  _MIN_FEM_NODES` (=2, a beam FEM needs ≥1 element) and raises a clear `ValueError` ("needs a
  double-helical (duplex) core of at least 2 base pairs … pair the scaffold with staples first").
  The job runner's `except` stores `str(exc)` → the panel shows it as a readable "Failed: …" instead
  of the numpy error. Guard sits before the linear/nonlinear branch → both modes covered. Test
  `test_predict_shape_raises_clear_error_on_duplex_free_design`; runner path hand-verified (status
  failed + friendly message). `just test` green.
- **FRAME-JUMP FIXED 2026-07-04 (user-reported "shifts the entire model", w/ screenshot; after
  the ssDNA gap-fill the whole model still jumped).** Root cause: `deformed_positions` built the
  FEM shape on the STRAIGHT `nucleotide_positions` base (FEM mesh nodes sit on the straight helix
  axes), but the renderer draws the DISPLAYED geometry = `/design/geometry` =
  `deformed_nucleotide_positions` with the design's **DeformationOps + cluster transforms** applied.
  6hb_curved's bend is a DeformationOp (`κ=0.45°/bp`), NOT baked into raw nucleotide_positions —
  so raw base bbox is straight `5.9×6.5×73.5` while the displayed (rendered) geometry is bent
  `49×6.5×48`. Toggling swapped the bent render for the straight-based FEM shape → whole-model jump
  (centroid shift 12.9 nm). **Fix (user chose "align to displayed model"):** `deformed_positions`
  now rigid-body superimposes (Kabsch, `_rigid_superpose`) the FEM shape onto the displayed geometry
  over the shared beads — zips `nucleotide_positions(helix)` (FEM base) with `deformed_nucleotide_
  positions(helix, design)` (target), same order. Rigid alignment preserves ALL intrinsic quantities
  (bond lengths, twist, curvature → exp36 calibration + the twist/bend measurement tests untouched);
  only the global pose changes, exactly like the mrDNA/oxDNA overlays. Verified: centroid gap
  12.9→**0.0 nm**, FEM bbox now `56×6.7×53` ≈ displayed `49×6.5×48`; browser OFF/ON co-located (no
  jump). Test `test_predict_shape_covers_every_nucleotide...` still green (alignment doesn't drop
  beads). `just test` green. NOTE: the FEM's predicted curvature still differs somewhat from the
  DeformationOp analytic (FEM predicts from the loop/skip eigenstrain, gentler) — that's a legitimate
  prediction difference, now shown overlaid in-frame rather than as a jump. Whether the loop/skips
  fully encode the DeformationOp's intended bend is a SEPARATE question (not pursued).
### P5 Item 3 — flex map + deviation map (on-structure) **SHIPPED 2026-07-04**
Two new display modes join the deform toggle; the panel's single deform checkbox became a
mutually-exclusive **radio group** (Off / Predicted shape / Flexibility map (RMSF) / Deviation
from design). All Physical-layer/display-only, share the one FEM overlay + scalar-colour channel.
- **Flex map** (RMSF): backend `/cando/jobs/{id}/rmsf` already existed. Deform to predicted shape +
  `applyScalarColors` viridis over per-bp RMSF (rigid=dark→flexible=bright). No new backend.
- **Deviation map** (NEW backend): `backend/core/cando_deviation.py::compute_deviation(design,
  display_positions)` → per-nucleotide |FEM-predicted − intended-geometry| + global **RMSD**. Native
  target = **deformed_nucleotide_positions** (the DISPLAYED geometry the FEM was Kabsch-aligned to),
  NOT straight `nucleotide_positions` (diffing vs straight would just re-report the DeformationOp
  bend). Route `/cando/jobs/{id}/deviation`; green→red ramp; readout shows RMSD.
- **Semantics validated** (`tests/test_cando_deviation.py`, 4): straight control RMSD 0.00; realized
  90° bend RMSD 1.94 (FEM ~85° ≈ drawn 90°); UNREALIZED bend (add_bend, no apply_loop_skip_deformations)
  RMSD 5.11 — realizing loop/skips halves+ the deviation. **This IS the Item-4 autorefine oracle.**
- Frontend: `cando_display.js` → 3-mode controller (showDeform/showFlex/showDeviation/refresh/mode/
  lastStats; local viridis+green→red ramps, pure `flexColorMap`/`deviationColorMap`). Panel radios +
  `getCandoDeviation` client fn. Tests: `cando_display.test.js` 15, panel test green, full frontend 2047.
- **VISUALLY VERIFIED** (doc-pinned e2e screenshot on 6hb_curved's completed jobs, then removed):
  flex = viridis bead cloud (dark rigid core), deviation = green→amber (RMSD 5.54 nm, grows where the
  FEM under-realizes 6hb_curved's drawn bend), radios exclusive, readouts correct, 0 console errors.
  `/deviation` HTTP-verified (2536 positions, rmsd 5.54). Backend `just test` green.
- **DEFERRED to Item 3b:** PNG/CSV export + the `metric_graph.js`-style heatmap card (the handoff's
  "PNG/CSV export like the oxDNA metrics card"). On-structure maps shipped; the 2D graph/export did not.

### LOOP-COPY FIX for all CanDo display toggles **2026-07-04** (user-reported)
Loop *insertions* place several nucleotides at ONE (helix,bp,dir); the renderer distinguishes them
by a **`copy` index** (`helix_renderer._copySeenBB`) and addresses beads/colours by the 4-part key
`helix:bp:dir:copy` (NO 3-part fallback for beads/slabs/cones). CanDo's `deformed_positions` emitted
**no copy field** → every loop copy>0 aliased to copy 0 → loop-insert bases were never moved OR
coloured by deform/flex/deviation (stranded at native). The prior coverage test checked a COLLAPSED
set of (helix,bp,dir) → blind to it (false pass).
- **Fix:** `fem_solver.deformed_positions` now stamps `copy` = per-(helix,bp,dir) running counter over
  `nucleotide_positions` order — **verified identical to the geometry-endpoint order** (0/36 loop keys
  mis-ordered) so it matches the renderer's `_copySeenBB`. `compute_deviation` matches native per
  (helix,bp,dir,COPY). Frontend `toFemUpdates`/`flexColorMap`/`deviationColorMap` thread `copy` and
  emit 4-part colour keys (+3-part alias only for copy 0).
- **Validation tests (the user's ask):** `test_fem_solver.test_predict_shape_covers_every_nucleotide_
  including_each_loop_copy` now asserts coverage over (helix,bp,dir,COPY) tuples + `len(pos)==total_nuc`
  (would fail on the old collapse); `test_cando_deviation.test_loop_copies_each_get_their_own_deviation_
  entry`; frontend loop-copy colour-key + `toFemUpdates` copy tests. Data check: 6HB w/ loops → 1296
  nuc = 1296 display entries = 1296 distinct (h,bp,dir,copy), 36 copies>0.
- **VISUALLY VERIFIED** (loop-heavy 6HB, fresh coarse+RMSF job, doc-pinned screenshots): flex viridis +
  deviation green→amber colour the ENTIRE structure incl. the loop-dense mid-region — no stranded/grey
  loop beads; 0 console errors. `/display` + `/deviation` HTTP-verified carrying `copy` (84 loop copies).
- **mrDNA shares the same latent gap** (`mrdna_runner._display_positions` emits no copy) — flagged, not
  fixed (out of scope; separate feature area + tests).

### P5 Item 3b — Graphs & Metrics card (per-bp flex + deviation graphs, PNG/CSV) **SHIPPED 2026-07-04**
The oxDNA-style "Graphs and Metrics" card, for CanDo. **Key difference from oxDNA: the FEM is a STATIC
solve → NO temporal domain, NO background compute.** Both metrics are purely SPATIAL (per bp), and the
data already lives on the completed job (rmsf.json + on-demand `/deviation`), so a click just fetches +
draws. Two metric rows: **Flexibility (RMSF)** and **Deviation from design**; each with Display (popup
graph) + Export (PNG/CSV modal).
- **New modules (frontend-only; no backend — Item-3's `/rmsf` + `/deviation` are the whole data path):**
  - `frontend/src/ui/cando_metrics.js` — pure cores: `rmsfRows`/`deviationRows` (response → per-bp
    `{helix,bp,val}`; deviation AVERAGES the strands/loop-copies at one (helix,bp) station), `helixSeries`
    (one overlaid polyline per helix), `candoMetricCSV`, `buildCandoSpec`. Reuses metric_graph.js
    `buildChartSpec`/`SERIES_COLORS`/`drawChart`/`renderToDataURL` (shared, live-validated) so popup +
    PNG render identically.
  - `frontend/src/ui/cando_metrics_card.js` — `initCandoMetricsCard({getSelectedJob})`, a CHILD module of
    the cando jobs panel (mirrors how `initOxdnaMetricsCard` is wired from the oxDNA panel). Per-job rows
    cache, lazily-built single-canvas Display popup (oxDNA's is two-canvas; CanDo needs only spatial).
    RMSF row gated on `job.rmsf_max_nm`; deviation always available once solved.
  - HTML `#cando-metrics-card` block in `index.html` (last element in the cando panel body). Reuses
    metric_export_modal.js (PNG/CSV modal + downloads).
- **Wiring (module-first):** `cando_jobs_panel.js` gains `import initCandoMetricsCard` + `const _metricsCard
  = initCandoMetricsCard({getSelectedJob: _selectedJob})` + `_metricsCard?.sync()` in `_renderDetail` +
  `_metricsCard?.refresh()` in `_stopDisplays`. main.js untouched (panel owns the child, like oxDNA).
- **REAL-DATA GOTCHA (would've silently mis-sorted):** `helix_id` is a STRING (`"h_XY_0_1"`), NOT numeric,
  and `bp_index` can be NEGATIVE (ss/loop ends). Initial `a.helix - b.helix` sort → NaN. Fixed with a
  numeric-aware `localeCompare` comparator (`_cmpHelix`); pinned by a string-id + negative-bp test.
- **Tests:** `cando_metrics.test.js` (pure: rows/series/CSV/spec, incl. the string-id/negative-bp pin),
  `cando_metrics_card.test.js` (jsdom: button gating on completed+RMSF job, Display→popup, Export→modal→
  files, fetch cache + refresh-clears). `just test-frontend` green **2063** (was 2047).
- **VERIFIED IN APP (doc-pinned e2e, real 6hb_curved completed FEM job, then removed):** both graphs draw
  non-blank real canvases — RMSF shows the floppy-ends/stiff-core profile (0.44–1.62 nm), deviation shows
  the ends-high/middle-low profile (6hb_curved under-realizes the drawn bend most at the free ends), 6
  helix polylines each, correct axes/legend, status "1200 base pairs"/"1250 base pairs", **0 console
  errors**. Pure pipeline also cross-checked on the live payload via node (1200 rmsf → 6 helices, 1250
  deviation per-bp rows, CSV w/ negative bp). (One unrelated pre-existing `just smoke` fail:
  `assembly_exit_cleanup`, an assembly-mode teardown test my Dynamics-tab change doesn't touch.)

### P5 — "CanDo style output" cylinder representation **SHIPPED 2026-07-04** (user-requested, pre-Item-4)
A new display toggle that draws the FEM-predicted shape the way CanDo does: one grey **jointed-cylinder
tube per helix** (a chain of short cylinders, radius = duplex radius 1.125 nm, threaded through the per-bp
axis positions) + thin **crossover joint connectors** (radius 0.2 nm), with the native NADOC model hidden
— a standalone rep exactly like the mrDNA CG-beads mode. Works for both Coarse (linear) and Fine
(nonlinear) jobs (the shape is baked into the job's cached display positions).
- **What CanDo actually renders (confirmed from the zips):** the coarse zip's
  `structure_NLSA_deformedShape.bild` is 2516 thick cylinders (radius 11.25 Å = duplex radius) forming the
  per-helix axis tubes + 244 thin (2.0 Å) crossover connectors, all grey; the RMSF `.bild` is the same
  cylinders coloured per-segment. `deformed_shape_view*.png` = smooth grey tubes following the bent axis.
  **The axis of a duplex bp = midpoint of its two strand backbones** (they sit at ±radius), so the aligned
  axis polyline falls straight out of the cached (Kabsch-aligned) display positions — no re-solve.
- **New backend:** `backend/core/cando_cylinders.py::compute_cylinders(design, display_positions)` →
  `{tube_radius_nm, joint_radius_nm, helices:[{helix_id, points}], joints}`. Axis map keeps only
  duplex-core bp (both FORWARD+REVERSE, copy 0) → clean axis; ssDNA ends/loop copies excluded (match
  CanDo's duplex tubes). Per-helix points bp-ordered; joints from `design.crossovers` (half.index == bp).
  Route `/cando/jobs/{id}/cylinders` (mirrors `/deviation`: cached display + snapshot design, no re-solve).
- **New scene overlay:** `frontend/src/scene/cando_cylinders.js::initCandoCylinders(scene)` — mirrors
  `mrdna_connections.js` (InstancedMesh of unit cylinders scaled per segment) with thick tube segments +
  thin joint connectors. **PURE CYLINDERS — no sphere fillers** (user: CanDo's real output is the
  "coin-stacked" per-bp disc look, not a smooth marshmallow tube; the deformedShape.bild is cylinders
  only). Pure `cylinderSegments(data)` (tubes/joints split, each carrying mean-endpoint RMSF) + `jetRGB`
  unit-tested.
- **RMSF heat-map colouring (user: "colour-coded like the RMSF view CanDo provides").** CanDo's
  `structure_NMA_RMSF.bild` colours every cylinder with the **jet ramp**, normalised bluest=min(0th pct)→
  reddest=95th pct (per `structure_NMA_HeatMapRange4RMSF.txt`, clamp above p95). So `/cylinders` now also
  loads `rmsf.json` and returns per-node RMSF + `rmsf_min`/`rmsf_p95`/`rmsf_max`/`has_rmsf`; the overlay
  tints each segment by `jetRGB((rmsf-min)/(p95-min))`. Segments/jobs w/o RMSF → grey fallback (the ~5%
  ss-end tips outside the meshed duplex core also stay grey). Three THREE.js gotchas fixed to get the
  vivid CanDo look: (1) per-instance colour is `instanceColor`/`setColorAt` with `MeshBasicMaterial({color:
  0xffffff})` — **do NOT set `vertexColors:true`** (that looks for GEOMETRY vertex colours the cylinder
  lacks → renders solid BLACK); (2) **unlit** MeshBasic (not MeshStandard) so the ramp reads vivid
  regardless of scene lighting (a lit material sank the blue end to near-black); (3) `setRGB(...,
  THREE.SRGBColorSpace)` treats ramp values as display colours. Uses the **vivid jet** (bright
  blue→cyan→green→yellow→red, no dark tails) because the stiff core sits at the ramp min → analytic jet's
  dark-blue `(0,0,0.5)` looked near-black; CanDo's own dark tails are lifted by Chimera's lighting.
- **Display wiring:** `cando_display.js` gains a 4th mode `showCandoStyle(jobId)` (fetch cylinders →
  overlay.update + hide native model via injected `setDesignVisible`) + a `_teardown()` that every mode
  entry calls so switching between cylinder-rep and the bead-based deform/flex/deviation modes cleanly
  swaps (clear tubes+show model ⇄ clear bead overlay/colours). Panel: 5th radio "CanDo style output
  (cylinders)" + `_MODE_FNS.cando` + status readout. main.js: `initCandoCylinders(scene)` overlay +
  `setDesignVisible: _setDesignGeometryVisible` passed to `initCandoDisplay` (thin wiring; hides beads +
  arcs, exactly like mrDNA CG-beads). Client `getCandoCylinders`.
- **Three-Layer:** purely Physical/display-only — axis geometry derived from the aligned display positions,
  topology untouched.
- **Tests:** backend `tests/test_cando_cylinders.py` (5: axis-midpoint duplex-only, bp-ordering, real-6HB
  tube-per-helix + joints⊆crossovers, **RMSF heat-map per-node + p95 ramp**, empty); frontend
  `cando_cylinders.test.js` (5: `cylinderSegments` mean-RMSF/no-spheres + `jetRGB` vivid landmarks) +
  `cando_display.test.js` cando-mode block (6). `just test-frontend` **2073**; `just test` **3850** (2
  unrelated real-sim fails: oxDNA real-binary + NAMD benchmark).
- **VERIFIED IN APP (doc-pinned e2e on real 6hb_curved job, then removed):** the 6 helix tubes render as
  the **coin-stacked per-bp disc** look (no spheres) heat-mapped by the **jet RMSF ramp** — bright blue
  stiff core → red floppy ends, exactly matching CanDo's `rmsf_view*.png`; native bead model hidden, 0
  console errors.

#### Refinement round 2 (user feedback) — helix-CENTRE axis, no ssDNA, dimmer jet **2026-07-04**
Three user asks after seeing the first cylinder render:
1. **"Remove ssDNA (no grey fall-back)."** & 3. **"Centre the cylinders on the helix centre, not the
   backbone contour."** — BOTH solved by threading the tubes through the **FEM AXIS nodes** (true helix
   centre, one per duplex-core bp) instead of the backbone MIDPOINT. The old midpoint precesses around the
   axis along the helical groove → the tube visibly wobbled ("follows the backbone contour"); and it
   included ss-end bp that had both display strands but no FEM/RMSF node → grey tips. Axis nodes exist only
   for the meshed duplex core, so ssDNA is gone and every node has RMSF (no grey).
   - **Solver:** `fem_solver` now shares the Kabsch alignment via `_kabsch_transform`/`_apply_transform`;
     `deformed_positions_with_axis(design,mesh,u)→(positions,axis)` applies the SAME rigid transform to the
     axis nodes (`mesh.nodes[i].position + u[axis]`) so they overlay in-frame. `predict_shape` returns
     `"axis": [{helix_id,bp_index,position}]`; `deformed_positions` kept as a thin list-returning wrapper.
   - **Runner:** `_run_job` caches `axis` into `display.json`.
   - **`compute_cylinders(design, axis_nodes, rmsf)`** now consumes the axis-node list directly (was
     reconstructing midpoints). `axis_from_backbones(display, rmsf)` is the FALLBACK for jobs cached BEFORE
     this change (wobblier midpoint, but still ssDNA-filtered via the rmsf-bp set). Route prefers
     `cached["axis"]`, falls back otherwise. **Old cached jobs need a re-run to get the centred axis.**
2. **"Jet is good but WAY too bright."** — dimmed the ramp by `_BRIGHTNESS=0.62` at colour-set time
   (`jetRGB` stays the canonical vivid ramp; grey fallback also darkened to `0x8a8a8a`). Full-saturation
   jet under the unlit material read as glaring neon; ~⅔ brightness matches CanDo's tone.
- **RE-VERIFIED IN APP (fresh Coarse job, e2e, removed):** 6 smooth parallel tubes (no helical wobble),
  fully colour-covered end-to-end (no grey/ssDNA), smooth blue→cyan→green→yellow→red gradient at a calm
  brightness — a close match to CanDo's `rmsf_view`. Status "6 helix tubes, 114 crossover joints", 0
  console errors.
- **Tests:** backend `test_cando_cylinders.py` (7: `axis_from_backbones` midpoint+rmsf-filter, bp-ordering
  from axis nodes, real-6HB tube-per-helix, **axis-nodes==rmsf-nodes & differ from backbone-midpoint**,
  RMSF p95 ramp, empty); `test_fem_solver`/`test_cando_deviation` still green (alignment refactor
  behaviour-preserving). `just test-frontend` **2073**; backend cando+fem subset 28 passed (full suite
  re-running).

### P5 Item 4 — CanDo-FEM autorefine (backend engine + routes + tests) **SHIPPED 2026-07-04**
The greedy loop/skip refiner driven by the FAST in-process FEM oracle (`predict_shape` →
`compute_deviation.rmsd_nm`), replacing oxDNA CUDA's hours with seconds. Mirror of
`skip_twist_tuning.greedy_finetune_skips` with the FEM oracle swapped in. **Backend only this
session (user's scope choice); the panel Autorefine button/apply is Item-4b, not built.**
- **New `backend/core/cando_autorefine.py`** — `fem_refine(design, *, nonlinear=False, sigma,
  max_hotspots, min_spacing, rmsd_improve_nm, allow_loops=None, on_progress, should_stop)`:
  baseline `fem_measure` → rank deviation hotspots (mean+σ·std, spread) → at each hotspot TRY every
  candidate edit and KEEP the best if it lowers RMSD by ≥`rmsd_improve_nm`. Returns
  `{status, mode, n_hotspots, n_evaluated, edits_kept, before/after:{rmsd,dev_max,dev_mean},
  converged_marks:{helix_id:{bp:delta}}}`. Pure helpers: `aggregate_deviation_by_bp`,
  `rank_hotspots`, `free_interior_candidates`, `current_marks_by_helix`, `apply_marks`,
  `candidate_edits`, `fem_measure`.
- **User's split (Q-answered):** SQUARE lattice → **skips only** (add/remove deletions); twist/bend
  (honeycomb) → **skips + loops** (`allow_loops = lattice != SQUARE`, overridable). Edit DIRECTION
  is chosen EMPIRICALLY — every candidate (add_skip/add_loop/remove) is tried and the FEM oracle
  keeps whichever lowers RMSD. **No geometric reasoning about direction** (CLAUDE DNA-topology rule +
  [[feedback_crossover_no_reasoning]]).
- **Off-crossover/off-end placement ENFORCED** ([[feedback_loopskip_no_crossover_ends]]):
  `free_interior_candidates` = `core_candidates` minus crossover bp + domain endpoints + END_MARGIN(6).
  The refiner NEVER adds a mark on a forbidden bp (inherited marks the core realizer put on
  crossovers are left alone — that realizer still doesn't self-enforce the rule).
- **Trial builds are fast + pure:** `apply_marks` = clear+apply loop/skips, NO re-sequence (the FEM
  oracle reads duplex-coverage geometry, not base letters). The apply route DOES re-sequence.
- **New `backend/api/routes_cando_autorefine.py`** (registered in main.py) — mirror of
  `routes_autorefine.py`: in-memory `_RUNS`/`_STOP` + daemon thread + durable JSON. Routes:
  `POST /design/cando/autorefine/start` (rejects a design w/ no marks AND no deformation),
  `GET /design/cando/autorefine/{id}`, `.../stop`, `.../apply` (lands `converged_marks` as ONE
  reversible feature-log entry `op_kind='cando-autorefine-marks'` — NEW op_kind added to models.py;
  re-sequences via `_build_refined_design`, delta-aware + lattice-general, built OUTSIDE
  mutate_with_feature_log to dodge the non-reentrant state-lock deadlock, same pattern as oxDNA apply).
  Works on ANY lattice (objective is positional RMSD, not the SQ twist gate).
- **Three-Layer Law:** loop reads topology + predicts Physical-layer shape; only `apply` mutates
  topology, reversibly. **VERIFIED** (in-process real route handlers, under-realized 90° 6HB bend):
  guard rejects bare design; start→done, 4 hotspots/12 trials/4 kept, **RMSD 2.19→1.99 nm**; apply
  landed +4 marks + `cando-autorefine-marks` feature-log entry + proper design response. Backend-only,
  NOT driven from a browser (no panel yet).
- Tests `tests/test_cando_autorefine.py` (10 green): pure helpers + the off-crossover/off-end filter
  (load-bearing) + oracle (`fem_measure`) + greedy loop (straight control→0 edits, under-realized
  bend→RMSD never rises + added marks off-forbidden, SQ→skips-only). `just test` **4046 passed** (3
  pre-existing real-sim fails: oxDNA real-binary ×2 + NAMD benchmark, unrelated — no oxDNA/NAMD code
  touched).
### P5 Item 4b — Autorefine PANEL button + live status **SHIPPED 2026-07-04**
The Dynamics-tab CanDo panel now drives the Item-4 engine (user-requested). Frontend + a small
backend progress enrichment; no main.js change (all in `cando_jobs_panel.js`, module-first).
- **Button** `#cando-jobs-autorefine-btn` (+ Stop + status + result) sits **BELOW the Coarse/Fine
  row** in `index.html`; `cando_jobs_panel.js` wires start→poll→stop→apply mirroring the oxDNA
  autorefine block. Client fns `startCandoAutorefine`/`getCandoAutorefine`/`stopCandoAutorefine`/
  `applyCandoAutorefine` on `/design/cando/autorefine/*`. Apply is an EXPLICIT "✓ Apply to design"
  button in the result (safer than oxDNA's auto-apply — it mutates topology; reversible feature log).
- **LIVE status** (braille spinner, 1s poll): shows **iteration index + current→target twist /
  curvature / deviation** each round, e.g. `Iteration 3/8 · dev 2.04 nm→0.00 nm · curve 44.0°→72.3°
  · twist -0.7°→-1.7°`. Pure formatters `autorefineStatusText`/`autorefineResultHtml` (6 vitest).
- **Backend metric enrichment** (`cando_autorefine.py`): `fem_refine` emits a `phase:"iteration"`
  event per hotspot carrying `current`+`target` `{deviation, twist_deg, bend_deg}` — measured off the
  ALREADY-solved shape (NO extra solves): twist via `oxdna_health.measure_bundle_twist`, curve via a
  NEW `oxdna_health.measure_bundle_arc_bend` (chord-sagitta on the slab-centroid centreline — reads
  the TRUE arc angle ~85-90° for a 90° bend, unlike the existing `measure_bundle_bend` end-tangent
  estimator that reads low; the A9-safe exp36 estimator). Target = same estimators on the design's
  intended `deformed_nucleotide_positions` (deviation target 0). The route retains `last_iteration`
  so the metrics line persists through the interspersed per-trial events.
- Tests: backend `test_cando_autorefine.py` **14** (added iteration-metrics + arc-bend estimator);
  frontend `cando_jobs_panel.test.js` **21** (+6); full frontend suite **2153**. **VERIFIED IN APP**
  (doc-pinned e2e on `6hb_curved`, then removed): button below Coarse/Fine, click → live
  `Iteration 0 · dev 6.49 nm→0.00 nm · curve 73.1°→146.3° · twist 16.5°→-2.8°`, Stop works, 0 console
  errors. **Item 4 (backend + panel) COMPLETE → all of Phase 5 shipped.**

### TWO BUGS FIXED (user-reported on 6hb_curved) **2026-07-04**
1. **Deform-display backbone beads mis-wound on curvature.** `deformed_positions_with_axis` only
   TRANSLATED each bead by its axis-node displacement — the radial offset stayed in the STRAIGHT
   frame, so on a bent bundle the beads pointed the wrong way ("helical positions messed up mapping
   onto the curvature"); the CanDo-cylinder axis looked right (it uses axis nodes directly), which is
   how the user spotted it. **Fix (user chose "full frame incl. predicted twist"):** transport a
   rotation-minimising frame (RMF, double-reflection Wang 2008 — new `_rmf_frames`) along each helix's
   DEFORMED axis, seeded from the straight frame; re-seat every bead (`_wound_backbones_for_helix`) at
   its EXACT straight winding angle + radius in the transported cross-section frame. Captures bend +
   the bundle's global twist (helices spiral) from the correct axis geometry — no solver change, no
   calibration risk (display-only). **GOTCHA:** the FEM mesh spaces nodes at `FEM_RISE_PER_BP=0.34`
   (a CanDo constant, do NOT touch) while display geometry uses the helix's own rise → parametrise the
   RMF interpolation by **bp coordinate** (drift-free), NOT absolute axial, else beads drift off-node
   (measured non-perpendicular). After fix: beads ⊥ local deformed tangent (|off·tan|/|off|≈0.04) at
   radius≈1.0 nm. Loop copies keep their ±½-bp bulge (bp-coord ±0.5). Test
   `test_fem_solver.test_deform_backbones_wind_around_the_curved_axis`; VISUALLY verified on 6hb_curved
   (clean curved bundle, coherent winding). Twist/bend MEASUREMENTS unaffected (they use bp midpoints
   = axis, invariant to winding).
2. **"Add Loops/Skips [4]" tool placed marks on crossovers/ends** (42/74 on 6hb_curved). See
   [[feedback_loopskip_no_crossover_ends]] — now ENFORCED via `relocate_marks_off_forbidden` in
   `apply_loop_skips_from_deformations` (crud.py), preserving per-helix net count. Shared helpers in
   `loop_skip_calculator.py`; `cando_autorefine` now derives crossovers via
   `extract_crossovers_from_strands` too (robust vs the often-empty `design.crossovers`). Tests: tool
   → 0 marks on forbidden bps; curvature/deviation calibration unchanged (net count preserved).

### AUTOMATED CURVATURE VALIDATION + negative test **2026-07-04**
Prior curvature validation lived only in `experiments/exp36/process_bend_battery.py`, which
needs user-supplied CanDo ZIPs in `workspace/cando validation/` → NOT reproducible in `just test`.
Closed that gap: the bend validation now runs headlessly against the committed CanDo reference
angles (`cando_reference_values.json`: 05→86.9°, 06→170.1°), no CanDo run needed.
- **Oracle in `tests/automation_harness.py`:** `measure_fem_bundle_bend(design, nonlinear=)` →
  builds mesh, solves prestress, reduces deformed axis nodes to a per-station cross-section-centroid
  centerline, measures bend via `_chord_sagitta_bend` (A9-safe: reads ~0 on a STRAIGHT rod, true
  angle on an arc — circle-fit arc-span is degenerate on straight lines, turning-integral jitters).
  `assert_fem_matches_cando_bend(design, cando_deg, ...)` adds ratio band + can-go-red guard.
- **Tests `tests/test_fem_curvature_validation.py` (5):** regenerate the 6HB/210bp bends via the
  gen_cando_battery pipeline; FEM/CanDo — 90° LIN 81.3° (0.94), NL 85.4° (0.98); 180° LIN 145.7°
  (0.86). Marks depend only on per-helix NET count (not bp positions) → FEM bend identical to the
  battery even if placement differs.
- **NEGATIVE test (user ask, Three-Layer Law):** `add_bend` WITHOUT `apply_loop_skip_deformations`
  → display DeformationOp bends the frame ~82° (`assert_deformation_angle`) but 0 loop/skips → FEM
  predicts a STRAIGHT rod (bend <3°). Pins that the physical/geometric layers read only topological
  loop/skips, never the display deformation. `just test` green.

### Colour-map LEGENDS + Display collapsible card **SHIPPED 2026-07-04** (user-requested)
Two small UI asks on the CanDo panel:
1. **Legends for the colour-mapped displays** — the Flexibility (RMSF, viridis) and Deviation
   (green→red) maps now each get a floating colour-ramp legend pinned **middle-right of the workspace,
   the SAME slot as the oxDNA flex scale** (`#flex-scale`) → every colour-mapped output reads its legend
   from one place. Static ramp bar + data max/min readout; hidden for the non-colour modes (off /
   predicted shape / CanDo cylinders).
   - **New module `frontend/src/ui/cando_legend.js`** (`initCandoLegend()→{show(mode,min,max),hide,
     isVisible}`). The ramps are SAMPLED from cando_display's own `viridisHex`/`deviationHex` (pure
     `gradientCss`) so the legend can't drift from the on-structure colours. Pure `legendLabels`/
     `gradientCss`/`legendConfig` unit-tested (`cando_legend.test.js`, 10).
   - **HTML `#cando-legend`** (title/max/bar/min) beside `#flex-scale` in index.html.
   - **Wiring:** `initCandoDisplay` gains a `legend` dep — `showFlex`/`showDeviation` call
     `legend.show(...)` after applying; `_teardown` calls `legend.hide()` (so deform/off/cando hide it).
     main.js: `legend: initCandoLegend()` (pure wiring, main.js cohesive LOC flat). Legend-drive pinned
     in `cando_display.test.js` (shown for flex/deviation w/ correct bounds, hidden for deform/stop).
2. **Display options in their own collapsible card** — the mutually-exclusive viz-mode radios moved
   from an inline block in the job-detail into an `ox-card` ("Display", collapsible, starts open),
   matching the Advanced / Graphs-and-Metrics cards. `cando_jobs_panel.js` wires the header toggle
   (`#cando-display-toggle`/`-arrow`/`#cando-display-card`).
- **VERIFIED IN APP** (doc-pinned e2e on the real 6hb_curved completed FEM job, screenshots, then
  removed): Flexibility → viridis legend "RMSF (nm)" 1.62→0.44 middle-right; Deviation → green→red
  legend "Deviation (nm)" 15.94→0.23 (matches the RMSD-5.54 readout); Off hides it; Display card
  collapses on header click. `just test-frontend` **2084** green; `just smoke` **23** green; 0 console
  errors. Frontend-only change (no Python touched).

#### Follow-ups — CanDo-cylinder legend + always-visible Display card **2026-07-04** (user)
1. **CanDo-style cylinder output now has a legend too.** The tubes are an RMSF **jet** heat map
   (bluest = rmsf_min → reddest = rmsf_p95, clamped), so `showCandoStyle` shows the same legend keyed
   to the cylinders response's `rmsf_min`/`rmsf_p95` (only when `has_rmsf`; a no-RMSF job = grey tubes,
   legend stays hidden). New `cando` legend mode in `cando_legend.js` uses the scene overlay's own
   `jetRGB` dimmed by an exported `JET_BRIGHTNESS` (0.62) — single-source, so the legend can't drift
   from the tubes. Title "RMSF (nm)" (jet ramp ≠ the flex-map viridis ramp for the same quantity).
2. **Display card is now ALWAYS visible; its radios lock until a completed job is selected.** Moved the
   Display `ox-card` OUT of `#cando-jobs-detail` (which hides when nothing's selected) to a panel
   sibling. New `_syncDisplayModes()` (called from `_renderDetail` on every render, job or not) gates
   each radio: enabled only for a completed job + candoDisplay dep (Flexibility also needs the job's
   RMSF); no/unfinished selection → all locked. HTML radios keep their default `disabled` so the card
   boots locked.
- **VERIFIED IN APP** (doc-pinned e2e, real 6hb_curved job, screenshots, removed): before any
  selection the Display card shows with all radios dimmed/disabled; after selecting the completed job
  they enable; CanDo-style output → jet legend "RMSF (nm)" 1.21(p95)→0.44(min) matching the blue
  stiff-core tubes; Off hides it. `just test-frontend` **2086** green; `just smoke` 22 passed (the lone
  fail = the pre-existing flaky `assembly_exit_cleanup`, passes standalone, unrelated). 0 console
  errors. Frontend-only.

### PER-JOB SNAPSHOT RENDER for all display toggles **2026-07-04** (user-reported) — USER-CONFIRMED RESOLVED
Every CanDo display mode now renders the SELECTED JOB'S OWN design snapshot (the topology the design
had when that job ran) instead of overlaying the FEM positions onto the LIVE rendered beads. Fixes two
things the user reported:
1. **Old job + new live topology → stranded beads.** The bead modes (predicted shape / flex / deviation)
   called `applyFemPositions` onto the live model's beads (keyed `helix:bp:dir:copy`). When the live
   design had topology the snapshot lacked (loops/skips added since), those live beads got no update and
   sat at native ("new topology remains with unchanged positions"). Only the CanDo-cylinder mode was
   immune (it hides the model + draws its own geometry). **Fix:** the bead modes now fetch the job's own
   snapshot geometry and render THAT (hiding the live model), then overlay the FEM shape on it → 1:1 bead
   coverage, snapshot topology shown.
2. **Switching jobs with a mode on didn't update the view.** `_selectJob` never retargeted the active
   display to the newly-selected job. Added `_retargetDisplayToSelection` — on job switch, if a mode is
   active it re-applies that mode for the new job (or turns off if the new job can't support it, e.g.
   flex w/o RMSF or not completed).
- **New backend route** `GET /cando/jobs/{id}/snapshot-geometry` (`routes_cando.py`) → the snapshot
  design's full geometry (`_geometry_for_helices` + `deformed_helix_axes` + `_apply_ovhg_rotations_to_axes`
  on the job's `design.json`) + the design object. Same shape as `/design/geometry` plus `design`.
  Client fn `getCandoSnapshotGeometry`.
- **New renderer methods** (`design_renderer.js`): `renderExternalGeometry(design, geometry, helixAxes)`
  rebuilds the scene from arbitrary (snapshot) data + sets `_externalActive` (store subscription then
  ignores live-design changes — pure display swap, active design NEVER mutated, Three-Layer safe);
  `clearExternalGeometry()` restores the live model. Reuses the existing `_rebuild` path (colours/slabs/
  cones/xover-extras all free).
- **`cando_display.js`:** `_teardown` replaced by `_clearAll` (full restore: tubes + colours +
  `clearExternalGeometry`) and `_prepareForExternal` (light, before a snapshot render). Each `showDeform/
  showFlex/showDeviation` now `Promise.all([display/rmsf/deviation, getCandoSnapshotGeometry])` →
  `_renderExternal(snap)` → overlay. `showCandoStyle` calls `_clearAll` first (restore live, then hide +
  tubes). (NOTE: the Item-3b/legend doc above says `_teardown` calls `legend.hide()` — that logic now
  lives in `_clearAll`/`_prepareForExternal`.)
- **Tests:** backend `test_cando_job.py` +2 (`test_snapshot_geometry_reflects_the_jobs_own_topology`,
  `..._missing_snapshot_is_not_ready`), `just test` green. Frontend `cando_display.test.js` updated (new
  mocks + snapshot-render assertions + a snapshot-unavailable not-ready case); full frontend suite **2160**
  green. main.js untouched (LOC flat — `initCandoDisplay` wiring unchanged).
- **KNOWN LIMITATION:** crossover ARC LINES (unfold_view) still track the LIVE design, not the snapshot;
  when snapshot vs live crossovers differ some arcs can mismatch. In practice loops/skips never land on
  crossovers ([[feedback_loopskip_no_crossover_ends]]) so the crossover set is typically identical.
  Selection raycasts snapshot beads while a mode is active (inspection-only; pre-existing in spirit).
- **USER-CONFIRMED RESOLVED 2026-07-04** — the user exercised it in the app (select old job after adding
  loops → toggle modes; switch jobs with a mode on) and confirmed the per-job snapshot render works.

### SLAB SPLAY FIX (wound base-normal/tangent in the FEM display) **2026-07-04** (user-reported) — USER-CONFIRMED RESOLVED
On a heavily bent + mark-dense design (6hb_curved w/ 56 loops/55 skips) several base-pair SLABS in the
predicted-shape/flex/deviation display splayed radially OUTWARD. Root cause: the FEM display WINDS the
backbone beads onto the deformed axis (`_wound_backbones_for_helix`, RMF frame) but emitted NO base
normals (option B), so `applyFemPositions` kept each slab at its DESIGN (display-frame) orientation while
the bead moved to the wound frame → the two diverge; measured slab tilt vs inward-radial had a tail to
**102°** (>90° = pointing outward), ~1% of beads (worst on loop copies).
- **NOT a regression from the per-job snapshot render** — verified the snapshot endpoint returns geometry
  byte-identical (0.000 nm / 0.00°) to what the FEM Kabsch-aligns onto; the slab/normal code was untouched.
  Latent option-B display gap, exposed by this design's strong bend + dense marks.
- **Also confirmed Symptom-1 ("barely changes curvature") is NOT a bug:** the FEM converts the marks
  strongly (displayed bend 164°, 0° with marks stripped, 164° with the DeformationOp stripped → marks
  drive it, DeformationOp doesn't feed the solve per Three-Layer). It "barely changes" vs native only
  because the native model is already drawn ~163° by its bend DeformationOp and the FEM prediction (164°)
  lands on top of it — the drawn bend and the loop/skip program agree. No fix needed.
- **Fix (Symptom-2):** `_wound_backbones_for_helix` now also transports each bead's DESIGN base-normal +
  axis-tangent through the SAME straight→wound rotation (`_transport`: express in `(e1s,e2s,axis_hat)`,
  rebuild in `(e1,e2,tan)`) and returns `(positions, normals, tangents)`. `deformed_positions_with_axis`
  rotates them by the Kabsch R and emits `nx/ny/nz` (slab bnDir) + `tx/ty/tz` (slab tanDir) per position.
  `cando_deviation.compute_deviation` forwards the 6 fields. Frontend: `cando_display._femUpdate` threads
  them (both `toFemUpdates` + `deviationColorMap`); `helix_renderer` slab normal-map path uses the emitted
  `tx/ty/tz` when present (falls back to design `axis_tangent` → mrDNA/oxDNA overlays unaffected).
- **Result (measured):** wound slab normal ⊥ tangent (orthonormal frame, 0.00° err); vs the NATIVE
  displayed base-normal p50 **9.5°** / max **35°** (residual = genuine FEM-vs-drawn shape diff); NO slab
  exceeds 90° (outward splay eliminated).
- **Backward-compatible:** OLD job caches (display.json without the frame fields) → slabs keep design
  orientation (prior behaviour). **Re-run a job to get wound slabs.**
- **Tests:** backend `test_fem_solver.test_deform_slabs_carry_the_wound_frame_not_the_straight_orientation`
  (frame fields present + orthonormal + no outward slabs); frontend `cando_display.test.js` +2 (frame
  passthrough in `toFemUpdates` + `deviationColorMap`). `just test` / frontend suite green.
- **USER-CONFIRMED RESOLVED 2026-07-04** — the user re-ran a job and confirmed the slabs no longer splay
  radially outward (the visual is correct in the app).

### WELCOME-SCREEN LEGEND LEAK FIX **2026-07-04** (user-reported) — VERIFIED
CanDo RMSF/deviation legend `#cando-legend` (and the view-cube 90° roll buttons `#vc-roll`) stayed
visible after **File ▸ Close Session** returned to the welcome screen. Cause: `_resetForNewDesign`
tore down most overlays but never called `candoDisplay.stopAndRestore()` (the only path that hides
`#cando-legend` via `_clearAll → legend.hide()`); and `_showWelcome` hid only `#vc-wrap`, not the
sibling `#vc-roll`.
- **Fix (main.js):** `_resetForNewDesign` now calls `candoDisplay.stopAndRestore()`; `_showWelcome`/
  `_hideWelcome` use `viewCube.hide()`/`viewCube.show()` (which toggle wrap + roll together) instead of
  poking `#vc-wrap` directly. main.js LOC ≈ flat (swap, not growth).
- **Verify:** `frontend/e2e/welcome_overlay_cleanup.spec.js` (load → close-session → assert `#vc-roll`
  visible-then-hidden, `#cando-legend` hidden). Frontend suite 2162 green. `just smoke` close-session
  teardown gate green (the `assembly_exit_cleanup` fail under `just smoke` is the pre-existing flake —
  reproduces on stashed master, unrelated).

### 500 ON `/api/cando/jobs` DURING A SOLVE — thread-unsafe global warnings filter FIXED **2026-07-04** (user-reported)
User: "CanDo FEM fails for square-lattice designs" — terminal showed `GET /api/cando/jobs 500` with a
`FastAPIDeprecationWarning: ORJSONResponse is deprecated` raised as an exception (FastAPI 0.135). **NOT
square-lattice-specific — a concurrency race.** `fem_solver.solve_equilibrium` wrapped `spsolve` in
`with warnings.catch_warnings(): warnings.filterwarnings("error", category=Warning)` to detect a singular
matrix. But the warnings filter list is **process-global and not thread-safe**, and the CanDo FEM runs in
a background daemon thread (`cando_runner`). While a solve sat inside that block, the global filter was
"all Warnings → error"; any HTTP request the main loop served concurrently — e.g. the panel's
`/api/cando/jobs` poll, which builds an `ORJSONResponse` (now deprecated) — had its DeprecationWarning
promoted to a real exception → 500. Square lattice just happened to be what was solving (longer solve =
wider race window).
- **Fix:** dropped the `catch_warnings`/`filterwarnings("error")` entirely. A singular system makes
  `spsolve` emit a `MatrixRankWarning` and **return NaNs**, which the existing NaN/Inf guard already
  catches → same friendly "disconnected helices" `ValueError`, no global-filter mutation.
- **Tests (`test_fem_solver.py`, +2 → 16 green):** `test_solve_does_not_globally_promote_warnings_to_errors`
  (solve leaves no leaked "error" filter) + `test_singular_system_raises_clear_valueerror` (NaN→ValueError
  preserved). Square-lattice `predict_shape` hand-verified end-to-end (2×2 SQ bundle → 768 positions + RMSF).
  `just test`: 4055 passed (3 pre-existing/flaky fails unrelated — mrdna analytic `n_loops` 56≠18 fails on
  stashed master too; oxDNA/NAMD real-binary tests pass in isolation, flake under parallel xdist).
- **Sibling flagged, not fixed:** `mrdna_convergence.py:207` uses the same global-mutating
  `warnings.simplefilter("ignore")` in a threaded path — only *suppresses* (can't 500), left alone.

### SQUARE-LATTICE REGISTER OVER-TWIST — FEM oracle fixed + CanDo-validated **2026-07-04** (user-driven)
**Symptom:** autorefine "fails to twist correct" square-lattice struts (`3x6x400_Sq_test`) — it kept 0 edits
and the FEM predicted ~0° twist regardless of skips. **Root cause: the FEM never modelled the square
lattice's intrinsic REGISTER over-twist.** SQ crossover geometry demands ~10.67 bp/turn
(`SQUARE_TWIST_PER_BP`=33.75°/bp) while the duplex's natural helicity is ~10.5 bp/turn
(`BDNA`=34.3°/bp); that **0.55°/bp mismatch** is a rest-twist eigenstrain the crossovers can't relax → a
global bundle twist that exists **with zero loop/skips**, and deletions are placed to RELIEVE it. The old
`assemble_prestress_force` had only a loop/skip term (intercept 0, and skips *added* twist) — inverted vs
reality. **CanDo IS lattice-invariant** (34.3°/bp everywhere; twist emergent from crossover register — the
Abaqus deck confirms: uniform `*Initial Conditions TEMPERATURE` eigenstrain + prescribed-displacement
register `InitialDisp→HJgen→Unloding` release, no lattice constant). NADOC's geometry layer *is* SQ-aware
(draws straight at 33.75°/bp) but the FEM threw the winding away (bare-axis nodes, identical per-helix
frames) → register mismatch = 0 → no emergent twist. See [[REFERENCE_DNA_TOPOLOGY]] / [[feedback_crossover_no_reasoning]]
(direction taken from CanDo data, never reasoned).

**CanDo ground truth (bild twist, `workspace/cando validation/3x6x400_Sq_test*.zip`, fine+square+matched
constants):** unskipped **+64.0°**, 150-skip **+24.8°** — skips relieve, design under-corrected (zero-crossing
~245 skips → needs ~95 more; matches the user's "needs more skips"). 2x3x100 (independent geometry) is
directionally consistent (register-only would give +27°, CanDo is small <10° → substantial relief) but its
twist is too small/near-square to re-pin the factor.

**Fix** (`fem_solver.assemble_prestress_force`, SQ-gated): per helix
`φ0 = _SQ_REGISTER_TWIST_PER_BP_RAD·N_bp + SQ_SKIP_RELIEF_FACTOR·Σδ·(2π/bp_per_turn)`.
- `_SQ_REGISTER_TWIST_PER_BP_RAD = BDNA_TWIST_PER_BP_RAD − SQUARE_TWIST_PER_BP_RAD` (≈+0.55°/bp) — **zero
  free parameters**; reproduces the +64° intercept (FEM +67°).
- `SQ_SKIP_RELIEF_FACTOR = 0.5` — each deletion relieves ~½ bp of natural twist (the least-documented CanDo
  per-skip recipe; calibrated to the 150-skip +24.8° point → FEM +24.2°). Exposed as a constant to refine.
- Honeycomb: `natural == lattice` → register term **exactly 0**, old branch unchanged → exp36 battery + all
  prestress/curvature tests untouched (verified: `test_fem_solver` + `test_fem_curvature_validation` green).
- Model is physically clean: bundle stays straight (sag ~0.02 nm), monotonic, twist ∝ eigenstrain.
- Test `test_square_lattice_register_overtwist_present_and_relieved_by_skips` (SQ pre-stress ≠0 at 0 skips,
  HC =0, skips shrink the predicted deformation). `just test`: 4059 passed, 0 failed (2026-07-05).

**Objective correct — ENGINE now fixed too (2026-07-05):** `fem_measure` RMSD-vs-straight is 1.73(0)→0.58(150)→
1.08(298), a proper minimum near the right density. The greedy single-skip-per-hotspot search kept 0 edits (a
plain SQ strut has NO local hotspot — the register over-twist spreads the deviation uniformly, and one skip
moves RMSD ~0.004 nm < the accept bar). **FIX = a global skip-DENSITY sweep** mirroring `skip_twist_tuning`'s
period sweep but with the fast FEM oracle (`backend/core/cando_autorefine.py`):
- `periodic_skip_marks(design, period)` — uniform `sq_lattice_periodic_skips`→`relocate_marks_off_forbidden`,
  skips-only, `{}` for non-square, NO re-sequence (oracle reads geometry).
- `sweep_skip_period(base, ...)` — coarse geometric pass over the period range + 0-skip point → ternary
  `_search_min_period` refine to the integer optimum. ~20 FEM solves (seconds each). Returns
  `{status, best_period, best_marks, best_measure, baseline_measure, curve}`; emits `density_trial`/`density_best`.
- `fem_refine` now composes TWO strategies: **SQUARE → density sweep FIRST** (adopt only if it beats the
  design as loaded — never a regression), then the greedy hotspot pass mops up local residual (usually none on a
  plain strut); **honeycomb → greedy only** (unchanged). Output gains `density` (sweep report; `None` for HC).
- Route guard (`routes_cando_autorefine.py`) relaxed: a bare SQUARE strut (no marks/no deformation) is now
  refinable (the sweep adds the twist-relieving skips); bare honeycomb still rejected (no register term).
- **VALIDATED** on a 2×3×336 SQ strut: greedy=0 edits → density sweep picks **period 48 (42 skips), RMSD
  1.369→0.443** (0.32×), best off crossovers/ends, skips-only. Tests `test_cando_autorefine.py` **16** (4 new:
  periodic-marks purity, sweep-finds-min, plain-strut-tunes-where-greedy-kept-zero, should_stop). `just test`
  **4063 passed** (was 4059).
**Reconstruct the submitted `3x6x400` calibration design:** load workspace file (now 0-skip) → `apply-loop-skips`
tool (`sq_lattice_periodic_skips`→`relocate_marks_off_forbidden`→`apply_loop_skips`) → 150 skips. `2x3x100_Sq_test`
source already carries its 12 skips.

### AUTOREFINE "0 EDITS / NO IMPROVEMENT" ON 3x6x400 — was a FRONTEND reporting bug (2026-07-05, user-reported)
After the density-sweep engine landed, the user still saw "0 edits / no improvement" on `3x6x400_Sq_test.nadoc`.
**The ENGINE was fine** — headless `fem_refine` on the real 18-helix strut: baseline RMSD **1.734 → 0.459**,
density **period 40, 180 skips**, `edits_kept=0`. The bug was in the PANEL: `cando_jobs_panel.js` gated the whole
result + Apply button on `edits_kept.length`. The density sweep writes its skips to **`converged_marks`, NOT
`edits_kept`** (edits_kept only counts the greedy hotspot pass, which correctly keeps 0 on a uniform-twist strut),
so a real 1.73→0.46 improvement rendered as "No improving edit found" with no Apply button.
- **Fix (frontend):** new pure `refineMarkCounts(result)` (sums skips/loops in `converged_marks`) +
  `refineImproved(result)` (true when `after.rmsd < before.rmsd`). `_renderArResult` now gates on
  `refineImproved && converged_marks non-empty` (Apply applies `converged_marks` — always did); `autorefineResultHtml`
  headlines the density sweep (`skip density: period 40 → N deletions`); status shows total marks. Tests:
  `cando_jobs_panel.test.js` (+ density-result/refineImproved/refineMarkCounts) + NEW jsdom
  `cando_jobs_panel.autorefine_result.test.js` (density-only done run → Apply button renders + calls apply, no
  "No improving edit"). Frontend suite **2166**.
- **Headless validation (user ask "automate + headless validation tests"):** new harness oracle
  `automation_harness.assert_fem_autorefine_relieves_twist(design)` (non-vacuous start + RMSD drop ≤ ratio +
  non-empty off-forbidden skips-only marks — the "0 edits" regression fails it) + `tests/test_cando_autorefine_
  validation.py` builds a **3×6 = 18-helix** square strut HEADLESSLY (real design's cross-section; workspace/ file
  is gitignored so build, don't load) and asserts it: 3×6×160 → 0.806→0.206 (ratio 0.26), period 40 (== real
  design). Registered slow in `conftest.py`. `just test` **4064 passed**.
- **NOTE:** the density sweep runs FIRST for SQ but the greedy hotspot pass still runs after and can burn time
  (real 3x6x400: 8 hotspots × trials × full solve ≈ 200s, all rejected on a plain strut). Works, but a future
  optimization = skip/limit the greedy pass when the post-density field has no hotspots.

### AUTOREFINE JOB TYPE — auto-apply + retained FEM analysis + all displays **2026-07-05** (user-requested)
Promoted autorefine from a separate "run" (manual Apply click) into a first-class **CanDo JOB kind** so the
result is a persistent, displayable job that AUTO-APPLIES its marks. New `kind` field on `CandoJob` (`"predict"`
default | `"autorefine"`); the Autorefine button now creates `kind=autorefine` (user chose "repoint existing
button").
- **`cando_runner._run_autorefine_job`**: sets `doc_context` to the job's `doc_id` (multi-doc safe) → loads
  snapshot → `fem_refine` (live `refine_note` per progress event) → if improved, `build_refined_design`
  (re-sequenced) + `mutate_with_feature_log(op_kind="cando-autorefine-marks")` on the doc's active design →
  re-snapshots the refined design → `predict_shape` (with RMSF) → `_cache_fem_analysis` (display.json + rmsf.json
  + axis). So the completed job behaves EXACTLY like a predict job: deform / flex / deviation / cylinder toggles
  + snapshot-geometry all work off its cache. **No-improvement path still caches** the analysis (displays work,
  design untouched).
- **`build_refined_design`** promoted from `routes_cando_autorefine._build_refined_design` to
  `cando_autorefine.py` (core) — shared by the REST apply route + the job runner. Builds in an isolated scratch
  doc, handed to `mutate_with_feature_log` as a pure replacement (build OUTSIDE the callback → no state-lock
  self-deadlock).
- **New `CandoJob` fields:** `kind`, `doc_id`, `refine_applied/before_rmsd/after_rmsd/n_marks/period`,
  `refine_note` (live status line, server-built). `load()` back-compat defaults → old job.json = predict job.
- **`routes_cando`**: `CreateCandoJobRequest.kind`; create captures `doc_context.get_current_doc()`→`doc_id`;
  `start_job` dispatches `kind=="autorefine"`→`_run_autorefine_job` else `_run_job`. Job status/list already
  serialize all fields (asdict), so the panel gets `refine_note` + result fields for free.
- **Frontend (`cando_jobs_panel.js`):** Autorefine button → `createCandoJob({kind:'autorefine',nonlinear:false})`;
  new `_pollAutorefineJob` polls `/cando/jobs/{id}`, shows live `refine_note`, on completed calls `api.getDesign()`
  (design auto-applied server-side → refresh editor + feature log) + selects the job (displays ready). New pure
  `autorefineJobStatusText`/`autorefineJobResultHtml` (no Apply button — already applied). Old run-based
  formatters kept (the `/design/cando/autorefine/*` API still exists) but unwired from the panel.
- **VERIFIED headlessly** (2×3×160 SQ strut): job completed, applied 26 marks (period 36), RMSD 0.72→0.19,
  feature-log entry `cando-autorefine-marks`, active design 0→26 marks, display/axis/rmsf cached (2252/960/960).
- **Tests:** backend `test_cando_job.py` +3 (kind roundtrip+back-compat; SQ apply+log+cache-all-displays [slow];
  HC no-improvement still-caches); frontend `cando_jobs_panel.test.js` +job-helper pure tests + rewritten jsdom
  `cando_jobs_panel.autorefine_result.test.js` (button→job→applied-result→getDesign, no Apply button). Frontend
  **2171**; backend green.
- **NOT hand-driven in a live browser** — jsdom + headless prove the flow; the live gesture + on-job display
  rendering is MV-pending. **Caveat:** auto-apply builds from the job's SNAPSHOT (design at launch), so edits made
  during the run are superseded by the refined design (reversible via the feature-log entry / undo).

### THE 4 "PRE-EXISTING/FLAKY" SUITE FAILS — ROOT-CAUSED + FIXED **2026-07-04** (user-driven)
The recurring `just test` fails (mrdna analytic + oxDNA real-binary ×2 + NAMD benchmark) turned out to be
TWO distinct bugs, both now fixed — none was a physics/engine bug.
- **mrdna `test_analytic_curvature_from_marks` (deterministic, not flaky):** loaded `workspace/6hb_curved.nadoc`,
  which is **gitignored** — workspace/ isn't synced across the two computers, so the local file had drifted to
  56 loops/55 skips (13 nm) vs the test's expected 18/18 (~35 nm). Fix: made the test self-contained via a new
  deterministic conftest builder **`make_6hb_curved_design()`** = plain 192-bp 6hb + `bend_loop_skips` at R=40 nm
  → exactly 18 loops + 18 skips, pred radius 34.9 nm. Sibling `..._no_marks_is_straight` was the same
  gitignored-fixture fragility (`6hb_sim_v2.nadoc`) → now uses plain `make_6hb_design(192)`. No `workspace/`
  reads left in `test_mrdna_jobs.py`.
- **oxDNA ×2 + NAMD (genuine parallel-xdist flakes):** all three pass in isolation, fail only in the full
  12-worker `-n auto` run. **Root cause = CPU oversubscription.** The NAMD benchmark test launched `+p{cpu_count()}`
  = +p12 WITH core-pinning (`_core_binding_prefix`), seizing every core mid-suite and starving the ~11 concurrent
  workers running real oxDNA CPU sims (single-threaded), blowing their 120 s wall-clock deadlines; NAMD itself
  contended → blew its 300 s. Fixes: (1) NAMD test capped to `+p2` (a 32-bp proxy needs no more; "does it
  complete" not throughput) so no single test monopolizes the box; (2) widened deadlines as belt-and-suspenders
  for residual contention — oxDNA 120→300 s (both lifecycle + http, incl. production leg), NAMD 300→600 s.
- **Verify:** `just test` full parallel run — all 4 now green (see log). NAMD +p2 still 56 s in isolation.

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
