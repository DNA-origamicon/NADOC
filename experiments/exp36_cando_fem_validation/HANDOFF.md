# CanDo-replica FEM — Handoff & Refinement Plan

Multi-session handoff for the native CanDo-replica FEM shape predictor. Read this +
`memory/project_cando_fem.md` (the running log) + `cando_reference_values.json` (targets)
to resume. Goal: reproduce CanDo's twist/bend/RMSF on the loaded design, zero export.

---

## 1. Scorecard vs CanDo (2026-07-03)

| Quantity | Status | FEM vs CanDo |
|---|---|---|
| **RMSF** | ✅ solved | 0.8–0.97 across 2/6/18HB; robust (insensitive to crossover stiffness) |
| **Twist** (+ cross-section scaling) | ✅ largely solved | no-nick: 2HB 111/84, 6HB 40/45, 18HB 28/23 (~10–30%). WITH nicks: over-predicts 1.3–1.7 |
| **Bend** | ✅ **~0.9 (was falsely ❌0.68)** | The 0.68 was an estimator artifact (FEM end-tangent vs CanDo arc-span). Consistent arc-span: FEM 0.82–1.01 (mean ~0.91) linear, nonlinear refines clean cases (05→0.94). Residual only at extremes (2HB, 180°). See CORRECTION in `bend_diagnostics_results.md`. |

**BEND DIAGNOSIS DONE (2026-07-03):** B1–B4 CanDo results (`bend_diagnostics_results.md`)
prove CanDo bend is **crossover-density-INDEPENDENT** (B1 flat 86–90° over 112→28 xovers) and
a near-ideal LINEAR converter (~0.95 flat across angle/length/cross-section). Coupling refuted
3 ways. Our FEM ~0.68 with a strain-growing deficit = axial-relief loss. **Rest-curvature fix
TRIED + REJECTED** (κ geometry exact but per-element moments → only end-couples → a long
coupled bundle won't bend uniformly; 6HB 0.62/4HB 0.42/420bp 0.32, worse than axial; reverted).
**Real next step = a STIFFNESS-model change** (enforce plane-sections: full-station rigid
cross-section MPC — pairwise links don't rigidify — or B31H inter-helix shear/warping). Gate:
bend→~0.95 flat across B1/B2/B3/B4 with twist(0.26)+RMSF unmoved.

CanDo reference values (all honeycomb, 210 bp): bends ~95–102% of analytic and
cross-section-INDEPENDENT; twist heavily damped and cross-section-DEPENDENT (2HB 0.49 →
6HB 0.26 → 18HB 0.14 of the naive single-helix analytic). Full table in
`cando_reference_values.json`.

---

## 2. What's implemented — `backend/physics/fem_solver.py` (+ `tests/test_fem_solver.py`, 9 green)

Two-node Hermitian beam FEM, one node per **duplex-core** bp (matches CanDo node count).
CanDo-faithful constants: `FEM_RISE_PER_BP=0.34`, `HELIX_DIAMETER=2.25`, `BP_PER_TURN=10.5`,
EA/EI/GJ = 1100/230/460, `NICK_FACTOR=0.01`.

- `build_fem_mesh` — duplex-core nodes (`_duplex_bp_per_helix`), DNA beam elements, nick
  softening at strand termini (`_nick_bps_per_helix` → beams ×0.01 bend/torsion), crossovers
  as **rigid links** (`FEMRigidLink`), ssDNA crossovers as WLC springs.
- `assemble_global_stiffness` — beams + rigid-link penalty (exact constraint Cd=0) + springs.
- `assemble_prestress_force(mesh, design, axial=, torsion=)` — loop/skip eigenstrain →
  equivalent nodal forces (per-element stiffness; validated: reproduces the free analytic
  twist to 0.1°). `axial=/torsion=` toggles for diagnostics.
- `compute_rmsf_nma` — free-free NMA (projects out 6 rigid modes), 200 modes @ 298 K. CanDo-matched.
- `solve_prestress_shape` — incremental corotational nonlinear solve (converges; barely moves
  the bend → bend gap is NOT large-deflection).
- `apply_boundary_conditions` (centroid pin, for the static solve), `solve_equilibrium`.

Pipeline scripts: `scratchpad/gen_cando_battery.py`, `gen_extra_structures.py`,
`analyze_cando_pdb.py` (all in exp36 or scratchpad). Battery + reference data in
`workspace/cando validation/`.

---

## 3. The BEND gap — diagnosis so far (what's RULED OUT)

Bend is only ~68% of CanDo. Systematically eliminated:
- **NOT large-deflection** — corotational nonlinear solve barely changes it (35→36°, 64→71°).
- **NOT the crossover model** — rigid-link MPC is numerically identical to the stiff beam;
  bend is insensitive to crossover stiffness (scale 10→1e5).
- **NOT the torsional eigenstrain** — axial-only eigenstrain gives the same bend as axial+torsion.
- **NOT a net-force bug** — eigenstrain net force is exactly 0 (per-helix + total).

**Leading hypothesis: inter-helix SHEAR-LAG.** ~32% of the outer/inner length differential
relieves as internal axial strain — between discrete crossovers the helices slide axially
relative to each other, bleeding off the differential instead of bending. (Diagnostic: even
net-0 middle helices "stretch" +6 nm via the coupling; bend 59° coexists with this relief.)
Nicks improved the bend (0.38→0.68) precisely by softening the helices so more differential
converts — consistent with a shear/stiffness-partition story.

---

## 4. ★ PRIORITY: designs to run through CanDo to diagnose the bend gap ★

The core question: **does CanDo also lose bend to shear-lag (making our model right, needing
only tuning), or is CanDo's bend density-independent (making our shear coupling too weak)?**
These designs answer it. Generate crossover/end-clean (per `feedback_loopskip_no_crossover_ends`),
honeycomb, submit as honeycomb + fine model + NMA. Suggested naming `B1_*`…`B5_*`.

1. **★★★ Crossover-density sweep (THE key diagnostic).** Same 6HB, same 90° bend program,
   at 3–4 staple-crossover densities (e.g. full auto-crossover; every-other; sparse ~1 per
   21 bp; minimal for connectivity). **If CanDo bend stays ~87° across all densities but our
   FEM drops as crossovers thin out → our inter-helix shear coupling is too weak (the fix).
   If CanDo bend ALSO drops with sparse crossovers → shear-lag is real physics and our ~0.68
   is closer than it looks; re-examine the reference.** This single sweep is the highest-value run.

2. **★★ Bend-angle series** — 6HB, one length (210 bp), programmed 30° / 45° / 60° / 90° /
   135°. Is the conversion ratio constant (~0.68, → a linear stiffness partition we can
   calibrate) or angle-dependent (→ geometric/large-deflection after all)? Cheap, tightly
   diagnostic.

3. **★★ Length series at fixed curvature** — same programmed radius, lengths 105 / 210 / 420
   bp. Shear-lag has a characteristic length; if the conversion efficiency rises with length,
   that fingerprints shear-lag directly.

4. **★ Minimal cross-sections** — 2HB and 4HB 90° bends. With few crossover pairs, shear-lag
   should be extreme; compare CanDo vs FEM to isolate per-crossover shear coupling. (2HB
   needs seamless routing for a single scaffold — see `gen_extra_structures.py`.)

5. **★ Bend direction / lattice** — one square-lattice 6HB bend (SQ inter-helix geometry +
   10.67 bp/turn) to confirm the conversion isn't a honeycomb-geometry artifact. Multiple of
   32 bp length.

Keep every fixture's `.nadoc` + `.cadnano.json` + `_sequences.csv`; capture from CanDo the
`structure_NLSA_deformedShape.bild` (bend measured via `analyze_cando_pdb.py`) + the `.inp`.

---

## 5. Cheap diagnostics (no CanDo run needed) — STATUS 2026-07-03

- **CanDo `.inp` census for 05 — DONE.** `05_bend_90.zip/structure_NLSA.inp`:
  **1225 BDNA + 33 NICKDNA beams, 117 HJ crossover elements, 5 ssDNA connectors**
  (1264 nodes = bp). **117 HJ ≈ our 122 crossovers → CanDo does NOT mesh denser
  inter-helix coupling.** HJ = finite-length **compliant B31H beams** (span 2.25–3.8 nm,
  DNA section EI=230/GJ=460), NOT rigid links. ⇒ **the sparse-coupling form of the
  shear-lag hypothesis is refuted** — the bend gap is the crossover *model* (rigid link
  vs compliant beam) and/or the eigenstrain→bend conversion, not too-few crossovers.
- **FEM dense-coupling + axial/bend-partition experiments — script `fem_bend_diagnostics.py`**
  (results folded into the running log `memory/project_cando_fem.md`). Dense coupling adds
  a rigid link at every duplex bp between adjacent helices; if bend does NOT rise toward
  87°, coupling isn't the lever (consistent with the .inp) and the fix is the eigenstrain
  formulation (impose rest-curvature / prevent along-helix slide at crossovers).

## 5b. CanDo bend-gap battery GENERATED (2026-07-03) — awaiting user submission
15 designs `B1_*`…`B5_*` in `workspace/cando validation/`; submit per
`BEND_DIAGNOSTICS_SUBMISSION.md` (honeycomb + fine + NMA; **B5 = square**). All verified:
single scaffold, 0 marks on crossovers/ends, `?`-free CSV. B1 (staple crossovers
112/56/28/1 at fixed 90° bend) is the decisive run.

---

## 6. STATUS 2026-07-03 — validation COMPLETE, solver ready for Phase 5

Bend/twist/RMSF all validated vs the real CanDo battery. Scorecard: **RMSF ✅, TWIST ✅,
BEND ✅ (~0.92 linear / ~0.95 nonlinear** — the earlier "0.68" was an estimator artifact, see
`bend_diagnostics_results.md`). No solver rework needed. **Shape-prediction entry point
shipped:** `fem_solver.predict_shape(design, nonlinear=True, n_steps=20, with_rmsf=True)` —
the single public function the UI calls; **nonlinear is the default** (validated closest to
CanDo). Returns `{solver, positions:[{helix_id,bp_index,direction,backbone_position}], rmsf:
[{helix_id,bp_index,rmsf_nm}]}`. Three-Layer Law: **Physical/display-only, never mutates
topology.** Test `test_predict_shape_defaults_to_nonlinear...`; `just test` green.

Known envelope for the UI: linear ≈ 0.92·CanDo (fast, for previews); nonlinear ≈ 0.95 (slow,
~1 min+ on 6HB/210, longer on 18HB → **must run as a background job, not synchronously**).
180° hairpins are the one soft spot (measurement + high-strain nonlinear). RMSF NMA currently
uses the undeformed-K (CanDo does it at the relaxed minimum — a later refinement).

---

## 7. PHASE 5 — in-app CanDo FEM feature (HANDOFF, 4 items)

Foundation = `predict_shape()`. Mirror the existing Dynamics-tab sections (oxDNA / mrDNA / MD)
module-for-module (FEATURE_DEVELOPMENT.md module-first law: new tested modules + thin main.js
wiring). **Zero export, display-only.** Suggested naming: `cando_*`.

### Item 1 — Full frontend dynamics section (jobs list + coarse/fine + advanced) ✅ SHIPPED 2026-07-03
Done. `backend/core/cando_job.py` + `cando_runner.py` (daemon-thread `predict_shape` lifecycle,
snapshot→`display.json`+`rmsf.json`→completed; no subprocess/GPU — in-process scipy),
`backend/api/routes_cando.py` (registered in `main.py`; `/api/cando/...`, `/available` always
true), `frontend/src/ui/cando_jobs_panel.js` + `#cando-jobs-panel` HTML + client fns
(`candoAvailable`…`getCandoRmsf`) + thin `main.js` init (`candoDisplay:null`). Coarse=linear,
Fine=nonlinear. Advanced exposes `n_steps`+`with_rmsf` (EA/EI/GJ/NICK deferred — module
constants, threading overrides risks exp36 calibration). Tests: `test_cando_job.py` (5) +
`cando_jobs_panel.test.js` (15). Fixed a shared-with-mrdna bug: `_run_job` now sets
`job.status=running` so progress/ETA show. Full HTTP lifecycle verified vs live server; browser
gesture path NOT hand-driven (MV pending). Detail: `memory/project_cando_fem.md` P5 Item 1.

**Item-1 leftovers to fold into Item 2/3:** the panel already has a disabled "Predicted shape
(deform model)" toggle wired to an optional `candoDisplay` dep — Item 2 just builds
`cando_display.js` and passes it in `main.js` (`candoDisplay: initCandoDisplay({...})`). The
`/api/cando/jobs/{id}/rmsf` endpoint + `getCandoRmsf` client fn already exist for Item 3's flex map.

### Item 1 (original spec — mirror, one-to-one):
- **Backend job:** new `backend/core/cando_job.py` ← copy the lifecycle of `oxdna_job.py` /
  `mrdna_job.py` (create → run(async) → status → result → archive). `run()` calls
  `predict_shape`. **Coarse = `nonlinear=False`** (linear, seconds, interactive preview);
  **Fine = `nonlinear=True`** (full corotational, background). Expose `n_steps`, EA/EI/GJ,
  `NICK_FACTOR` as advanced params.
- **Backend routes:** new `backend/api/routes_cando.py` ← mirror `routes_oxdna.py` /
  `routes_mrdna.py` (`POST /api/cando/jobs`, `GET /api/cando/jobs`, `GET .../{id}`, result).
  Register in the app router; add path-scope to `.claude/rules/physics-fem.md`.
- **Frontend panel:** new `frontend/src/ui/cando_jobs_panel.js` ← mirror
  `oxdna_jobs_panel.js` / `mrdna_jobs_panel.js` (jobs list with status/spinner, Coarse/Fine
  calculate buttons, an **Advanced card** for params). Client ← `mrdna_relax_client.js`.
  Wire into the Dynamics tab beside the oxDNA/mrDNA panels (thin `main.js` init only).

### Item 2 — CanDo "Predicted shape (deform model)" toggle ✅ SHIPPED 2026-07-04
Done. `frontend/src/ui/cando_display.js` (`initCandoDisplay({designRenderer, api})`) — a
deform-only sibling of `mrdna_display.js` (no CG-beads mode; the FEM carries only deformed
backbone positions). Interface matches what the Item-1 panel already called:
`showDeform(id)` (→ `api.getCandoDisplay` → `toFemUpdates` → `designRenderer.applyFemPositions`),
`stopDeform()` (→ `applyFemPositions(null)`), `stopAndRestore()`, `deformActive()`, `deformJobId()`.
Both Coarse (linear) and Fine (nonlinear) jobs land in the same deform path — the solver mode is
baked into the job's cached positions. Wired in `main.js` (`const candoDisplay = initCandoDisplay(...)`
replacing the `null` placeholder; +1 import +1 init, pure wiring — main.js cohesive LOC flat).
Three-Layer Law: **display-state only, topology untouched.**
- **Tests:** `cando_display.test.js` (6 vitest, verbatim lift of the exercised mrdna deform logic:
  toFemUpdates mapping + showDeform/stopDeform/stopAndRestore/epoch-staleness). `just test-frontend`
  green (2038). `just smoke` green (23).
- **BUGFIX 2026-07-04 (stranded ssDNA/loops):** first ship stranded ssDNA scaffold ends + loop
  bases at native while the duplex swung → stretched fanning lines (user screenshot). Root cause:
  `deformed_positions` emitted only duplex-core mesh nodes. Fixed by mirroring mrDNA's gap-fill
  (uncovered nucleotide rides along nearest covered bp) → full nucleotide coverage. My initial
  "verified in app" was a FALSE PASS (asserted panel status text, not the render; smoke-config was
  multi-doc "No active design"). **Now VISUALLY verified** on 6hb_curved via a doc-pinned dev-server
  screenshot (OFF vs ON): coherent deform, no stranding. Validation: `test_predict_shape_covers_
  every_nucleotide_no_stranded_ssdna_or_loops`. `just test` 3834 passed. Detail in the running log.
- **NOTE for Item 2 original spec:** the "cylinders per helix/per-bp" rendering idea is SUPERSEDED —
  the shipped Item-1 panel already committed to a deform-in-place toggle ("deform model"), so Item 2
  = deform the existing rep via applyFemPositions (identical mechanism to mrDNA), NOT drawing new
  cylinder geometry. Simpler + reuses the shared FEM-position display path.
- **⚠ SOLVER BUG surfaced (out of Item-2 scope, log later):** `predict_shape` raised
  `"axis 1 is out of bounds for array of dimension 1"` on a tiny synthetic 200-bp scaffolded part
  (loadScaffoldedPart fixture). 6HB/larger real designs solve fine. A numpy-shape edge case in the
  solver for small/degenerate meshes — candidate `issues_ledger` ISSUE-N.

### Item 3 — RMSD / flex map + deviation maps (à la oxDNA) — CORE SHIPPED 2026-07-04
On-structure maps done; the 2D graph card + PNG/CSV export deferred to Item 3b.
- **Flex map** ✅ = per-bp RMSF heatmap on the structure (viridis). `/cando/jobs/{id}/rmsf` +
  `cando_display.showFlex`. Radio "Flexibility map (RMSF)".
- **Deviation map** ✅ = per-bp |FEM-predicted − intended-geometry| → green→red; global **RMSD**.
  `backend/core/cando_deviation.compute_deviation` + `/cando/jobs/{id}/deviation` +
  `cando_display.showDeviation`. **NB native target = the DISPLAYED geometry
  (`deformed_nucleotide_positions`, what the FEM was Kabsch-aligned to), NOT straight
  `nucleotide_positions`** — diffing vs straight would just re-report the DeformationOp bend.
  Semantics tested (`tests/test_cando_deviation.py`): unrealized-bend RMSD ≫ realized-bend RMSD ≈ 0.
- **Item 3b ✅ SHIPPED 2026-07-04:** "Graphs and Metrics" card in the CanDo panel — per-bp Flexibility
  (RMSF) + Deviation SPATIAL graphs (one polyline per helix) with PNG/CSV export. FEM is a static solve
  → NO temporal domain, NO background compute (data already on the completed job). New frontend modules
  `cando_metrics.js` (pure) + `cando_metrics_card.js` (child of the jobs panel, mirrors
  `oxdna_metrics_card`); reuses `metric_graph.js` + `metric_export_modal.js`. No backend change (Item-3's
  `/rmsf` + `/deviation` are the data path). GOTCHA: `helix_id` is a string + `bp_index` can be negative
  → numeric-aware sort. Verified in-app on real 6hb_curved job (both graphs draw, 0 console errors).
  Detail: `memory/project_cando_fem.md` P5 Item 3b.

### Item 4 — Autorefine for CanDo (reuse the oxDNA autorefine loop)
Plug `predict_shape` in as the **fast in-loop shape oracle** for design refinement, replacing
the slow oxDNA CUDA sim. Mirror `routes_autorefine.py` + the oxDNA autorefine process
([[regional_autorefine]] / `profile_guided_refine.py` in [[skip_twist_curvature_sweep]]):
iterate loop/skip placement so the **FEM-predicted shape matches the NADOC native/intended
geometry** (minimize the Item-3 RMSD). CanDo-FEM is ~1 min vs oxDNA's hours → the autorefine
inner loop becomes practical. Gate each iteration on the deviation map shrinking.

**Build order:** Item 1 (jobs/panel) → Item 2 (viz toggle) → Item 3 (maps) → Item 4 (autorefine,
depends on Item 3's RMSD). Each is a mirror of a shipped oxDNA/mrDNA module — reuse, don't invent.

---

## 7. Reproduce / run

```bash
export PATH="$HOME/.local/bin:$PATH"
just test                      # full suite (FEM tests in tests/test_fem_solver.py)
uv run python experiments/exp36_cando_fem_validation/analyze_cando_pdb.py <pdb> --expect-bend .. --expect-R ..
# FEM on a design: build_fem_mesh → assemble_global_stiffness → assemble_prestress_force →
#   apply_boundary_conditions → solve_equilibrium; measure bend/twist from deformed positions.
```
Reference data + all fixtures: `workspace/cando validation/`. Constants + method + the
CanDo `.inp` decode: `cando_reference_values.json` + `README.md` in this folder.
