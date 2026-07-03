---
name: project_mrdna_panel
description: "mrDNA/ARBD coarse-grained relaxation job panel in the Dynamics tab — single Run button + display toggles, mirroring the oxDNA panel"
metadata: 
  node_type: memory
  type: project
  originSessionId: dd668d19-36d4-447d-b2af-4eda01216418
---

# mrDNA relaxation panel (Dynamics tab)

Shipped 2026-07-02. Brought the mrDNA/ARBD coarse-grained relaxation engine to
the frontend as a managed job system + panel, mirroring the oxDNA panel
([[project_oxdna_relaxation]]). Before this, mrDNA existed only as the one-shot
`/ws/mrdna-relax` WebSocket + the pure `mrdna_bridge.py` library — no job store,
no panel, no display.

## The single-button UX decision (user, 2026-07-02)
mrDNA's **coarse** stage begins from an energy minimisation, so it IS the
relaxation — there's no need for a separate "relax then run" split. So: **one
"Run mrDNA relaxation" button, one stage (`coarse`, `fine_steps=0`), no
production/field/child-job machinery.** Display = **deform the NADOC model AND
show the CG bead cloud** (both toggles, independent).

## Architecture (mirrors the oxDNA trio, simplified to one stage)
- **`backend/core/mrdna_job.py`** — `MrdnaJob` dataclass + `MrdnaStatus` +
  `MrdnaStageStatus` (single `coarse` stage). Persists to
  `workspace/mrdna_jobs/{id}/job.json` (atomic write), restart-surviving. Reuses
  the kind-generic `job_archive` helpers with kind `"mrdna_jobs"`.
- **`backend/core/mrdna_runner.py`** — background **daemon-thread** runner (NOT
  the oxDNA asyncio dance): mrDNA's `model.simulate()` is a blocking Python call
  that spawns ARBD itself, so we can't own the subprocess. `_run_job` builds the
  parameterized model (`mrdna_model_from_nadoc_parameterized(design,
  CrossoverPotentialOverride.from_database("T0"))` — same as the old WS),
  simulates INTO the job dir (persistent, not `/tmp`), then extracts + caches
  `display.json` (relaxed positions) + `beads.json` (CG cloud). `stop_job` kills
  the detached ARBD child found by scanning `/proc` for the job dir + `arbd` in
  cmdline (self-verifying), which unblocks `simulate()`. `reconcile_mrdna_status`
  recovers a restart-orphaned `running` job from its cached `display.json`.
  `mrdna_available()` = `find_mrdna()` AND `find_arbd()` both resolve.
  - **Progress is time-based** (`_estimate_seconds`, capped <1.0 until the thread
    ends) — mrDNA/ARBD progress is hard to parse from a blocking call; the true
    completion signal is the thread finishing. Ref: ~635 beads·1e5 steps ≈ 21s.
  - **Extraction** (`extract_mrdna_results`): positions via
    `nuc_pos_override_from_mrdna_coarse` + per-helix intra-helix gap-fill (same as
    the old WS `_extract`); beads via `_extract_beads_aligned` (last DCD frame DNA
    beads, Kabsch-aligned onto the initial coarse PDB which is in NADOC frame).
    Both in nm. **No relaxed base-normal** → the display omits nx/ny/nz (option B:
    `applyFemPositions` keeps design orientation, moves only the backbone).
- **`backend/api/routes_mrdna.py`** — mounted in `main.py`. `POST /mrdna/jobs`
  (create+prepare+autostart; 400 if mrDNA/ARBD missing or no helices — NO
  sequence gate, CG model doesn't need WC sequences), `GET /mrdna/jobs`,
  `GET .../{id}`, `.../{id}/progress`, `POST .../start|stop`, `DELETE`,
  `GET .../{id}/display` (cached applyFemPositions list), `.../{id}/beads`
  (cached CG cloud), `.../{id}/error-log`, `GET /mrdna/available`. Shares the
  oxDNA staleness fingerprint for the out-of-date ⚠.

## Frontend
- **`frontend/src/ui/mrdna_display.js`** — `initMrdnaDisplay({designRenderer, api,
  beadOverlay, connectionOverlay, setDesignVisible})`. Two modes:
  `showDeform`/`stopDeform` (via `applyFemPositions`) + `showBeads`/`hideBeads`.
  **CG beads is a STANDALONE representation** (user, 2026-07-02): `showBeads` draws
  the bead cloud (reused **`md_overlay`** InstancedMesh) AND the bond connections
  (backbone + crossover, via `connectionOverlay`) AND **hides the native NADOC
  model** — whatever rep it's in — via `setDesignVisible(false)` (= main.js
  `_setDesignGeometryVisible`, the coordinated 5-module hide from
  [[feedback_design_renderer_visibility_rule]]). `hideBeads` restores it. `_epoch`
  guards stale async. Pure `toFemUpdates` + `beadsToPoints` + `edgesFrom`.
- **`frontend/src/scene/mrdna_connections.js`** — `initMrdnaConnections(scene)` →
  `{update(points, edges), clear()}`: cylinder **sticks** (an InstancedMesh, one
  lit cylinder per bond, pale blue-grey, r≈0.13 nm) through the bead cloud — NOT GL
  lines (1px lines were invisible against the beads). Bond edges come from the
  coarse PSF (`_psf_dna_edges`: backbone chain + crossover links, remapped to the
  DNA-bead index space; bonds to non-DNA `NAS`/orientation beads dropped since only
  DNA beads render).
  - **Lazy edge backfill** (`load_beads_with_edges`): jobs completed BEFORE the
    connections feature have a `beads.json` with no `edges` key → the `/beads` route
    recomputes edges from the on-disk PSF on first read and re-caches (no re-run
    needed). Live-confirmed on a stale 69-bead job: 0 → 75 edges backfilled.
- **`frontend/src/ui/mrdna_jobs_panel.js`** — `initMrdnaJobsPanel({mrdnaDisplay,
  getWorkspacePath})` → `{refresh, getSelectedJob}`. REST-poll (1.5s while active,
  like oxDNA — no WS). Single Run button, per-design job list
  (`filterJobsForPart`), detail block w/ single-stage timeline + stop/delete +
  the two display toggles. Pure helpers: `formatProgress`, `jobDisplayName`,
  `mrdnaJobIsActive`, `detailStatusText`, `coarseStageChip`.
- **`client.js`** — `mrdnaAvailable/createMrdnaJob/listMrdnaJobs/getMrdnaJob/
  getMrdnaProgress/startMrdnaJob/stopMrdnaJob/deleteMrdnaJob/getMrdnaDisplay/
  getMrdnaBeads/getMrdnaErrorLog` (through the shared `_oxdnaJSON` transport).
- **`index.html`** — `#mrdna-jobs-panel` inserted after `#oxdna-jobs-panel` in the
  Dynamics tab (`mrdna-jobs-*` IDs).
- **`main.js`** — pure wiring: 3 imports, `initMdOverlay(scene)` +
  `initMrdnaConnections(scene)` + `initMrdnaDisplay({..., setDesignVisible: (v) =>
  _setDesignGeometryVisible(v)})` + `initMrdnaJobsPanel(...)`; `'mrdna-jobs-panel'`
  in `_DESIGN_PANEL_IDS`. `_setDesignGeometryVisible` is a hoisted fn decl (defined
  ~L5047, referenced in the ~L1910 init via a lazy arrow). Ratchet held.

## Validation
- Backend `tests/test_mrdna_jobs.py` (13). Full backend suite **3703 pass**.
- Frontend `mrdna_display.test.js` + `mrdna_jobs_panel.test.js` (17). Full
  frontend **1962 pass**; `vite build` ok; `just smoke` render gate green.
- **LIVE end-to-end on this box's real GPU (2026-07-02):** a 2000-step run on the
  loaded 26-helix Bundle went queued→running→**completed in 17.4s → 1066 CG
  beads**; `/display` returned 10400 relaxed positions, `/beads` 1066 beads;
  delete cleaned up. The in-browser Run-click → live tick → visual deform/beads
  toggle owes [[manual_validation_debt]] **MV-MRDNA-JOBS** (WebGL gesture/visual).

## Display reconstruction — show the REAL relaxed shape (fix 2026-07-02)
The "mrDNA display (deform model)" toggle IS the CG→NADOC-beads-and-slabs
translation: it reconstructs per-nucleotide backbone positions from the CG spline
and moves the native beads+slabs there via `applyFemPositions`.
- **KEYSTONE BUG:** the runner first used `nuc_pos_override_from_mrdna_coarse`,
  which is the **GROMACS-bridge** reconstruction — it fixes axial spacing + twist to
  IDEAL B-DNA and captures only global axis *bending*, so a mostly-straight bundle
  reconstructs to ≈ the design (a 6hb showed **3/644 nucleotides moved** → "one base
  moves and that's all"). That function is deliberate (ideal backbone bond lengths
  for the topology) and still used by [[project_multiresolution_roadmap]] /
  `routes_export_structure` — do NOT repurpose it for display.
- **FIX:** new `mrdna_bridge.nuc_pos_override_display_from_coarse` — spline through
  the ACTUAL relaxed bead positions (Kabsch-aligned into the NADOC frame), axis
  point = `cs(t)` (real, not ideal), duplex radius+twist reconstructed around the
  real axis; crossover keys KEPT. Same 6hb now moves **604/644, mean 0.9 nm, max
  4.1 nm**. `mrdna_runner._display_positions` wraps it + gap-fill.
- **Versioned cache:** `display.json` carries `version` (`_DISPLAY_VERSION`);
  `load_display` REGENERATES stale caches (old/absent version) from the on-disk
  PSF/DCD on read, so jobs relaxed before the fix show the real shape with no re-run
  (same lazy-backfill pattern as the beads `edges`).
- Slab ORIENTATION still uses design base-normals (no nx/ny/nz — the coarse model
  has no per-strand backbone); positions are relaxed, orientation is option-B.

## Feature coverage (skips/loops/overhangs/linkers/extra-bases) — audited 2026-07-02
`_build_nt_arrays` (mrdna_bridge) walks `design.strands → domains → domain_bp_range`;
display reconstruction walks `design.helices → bp_start..length_bp`.
- **Skips**: ✅ omitted (`delta≤-1 → continue`); validated by the round-trip harness.
- **Direct dsDNA overhang connections**: ✅ HANDLED + VALIDATED end-to-end on
  `2x2_OH_test.nadoc`. Apply relocates BOTH overhang tips onto a dedicated duplex
  helix (`h_XY_2_0`, bp 40–55 = its full length); `_build_nt_arrays` pairs them
  FORWARD↔REVERSE (16/16 bp paired), ARBD simulates the duplex, and all 32
  nucleotides move in the display (22 coarse beads on it). mrDNA reads TOPOLOGY, so
  it works regardless of the `duplex.bound`/`binding.applied` flags.
- **ds linkers**: ✅ HANDLED + VALIDATED on `linker_test.nadoc`. A ds linker creates
  a real bridge helix `__lnk__<id>` (length = linker bp) carrying FORWARD (bp0→N)
  + REVERSE (bpN→0) strands → a paired duplex (30/30 paired), simulated + displayed
  (all 30 nts move). It's an ordinary helix in `design.helices`, so nothing special.
- **ssDNA free overhangs** (`6hb_sim_v2.nadoc`): flow through as UNPAIRED beads but
  the coarse display reconstructs them as a phantom duplex (FORWARD+REVERSE at
  HELIX_RADIUS) and they barely move — **user accepts** (ssDNA dynamics don't matter).
- **Loops**: ⚠️ in the fine model (distinct copies) but the coarse display collapses
  all copies of a bp to one position; 5 bp/bead doesn't resolve single-nt bulges.
- **Crossover `extra_bases`**: ❌ NOT HANDLED — absent from the entire mrDNA path
  (stored on `Crossover`, never walked); silently dropped. (oxDNA handles these; see
  [[project_oxdna_extra_bases]].) The one real gap if it matters.

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

## Three-Layer Law
mrDNA output is **Physical / display only** — relaxed positions deform the render
via `applyFemPositions` and draw the bead overlay; NEVER written into topology.
Same discipline as the oxDNA + MD displays.

See also: [[project_mrdna_arbd_setup]] (install), [[project_mrdna_bead_model]]
(1 bead/bp fine-stage caveat — but this panel uses the COARSE 5bp/bead stage),
[[project_md_engines_panel]] (mrDNA/ARBD install rows), [[feedback_cg_pipeline_lessons]].
