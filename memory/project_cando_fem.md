---
name: project_cando_fem
description: "Native CanDo-replica FEM shape predictor (twist/curvature/RMSF). Phase 0 research DONE — GO w/ conditions. Method spec, reference-data path, phase plan."
metadata:
  type: project
---

# Native CanDo FEM shape predictor

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

**Two ZIPs per CanDo job:** `*_atomic.zip` (multimodel PDB, B-factors ZERO) + `*.zip`
coarse (RMSF txt HERE, deformedShape.bild=cleanest geometry, **structure_NLSA.inp=the
Abaqus deck**). Deck CONFIRMS EA=1100/EI=230/GJ=460 (Å units) + reveals:
**pre-stress = TEMPERATURE eigenstrain + prescribed disp→register, then staged nlgeom
relaxation (InitialDisp→HJgen→Unloding1-6 w/ *Temperature op=mod→NMA).** Elements: B31H
(hybrid Timoshenko), NICKDNA (I,J÷100), HJ (crossover beams), CONN3D2 (ssDNA nonlinear).
This is the exact Phase-2/3 blueprint. Pending CanDo (re-run honeycomb): 01,02,03,04,06.

## Phase plan
- P0 feasibility — **DONE (GO w/ conditions)**. First-wave CanDo battery generated.
- P1 restore+modernize archived linear FEM into live tree, tests green (baseline).
- P2 pre-stress (axial ΔL from ins/del + torsional from over/under-twist & ins/del)
  + calibrate to CanDo constants; GATE: linear small/moderate bends match
  predict_radius_nm in direction AND magnitude. (NO twist-stretch coupling.)
- P3 geometric nonlinearity — corotational 3D beam + Newton-Raphson w/ load-stepping
  (REQUIRED for 90° bends + global twist).
- P4 validate vs REAL CanDo (user-supplied reference); iterate to stated tolerance.
- P5 in-app "Predict shape (FEM)" → deform to equilibrium (Physical layer) + RMSF
  heatmap + twist/curvature readout. Zero export.
