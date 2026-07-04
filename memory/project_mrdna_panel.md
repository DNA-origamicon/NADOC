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
- **Crossover `extra_bases`**: ✅ HANDLED (2026-07-04). `_build_nt_arrays`
  (mrdna_bridge) now reuses oxDNA's owning-strand junction map
  (`crossover_extra_base_junctions`, lazy-imported from oxdna_interface) to
  materialize each insert as ssDNA beads: `bp=-1` (unpaired), evenly lerped along
  the chord between the two flanking real nts, threaded prev_real→eb…→next_real in
  BOTH the 3′ chain (Pass 3 via strand_seqs) and the stacking chain (explicit
  post-Pass-4 loop — the domain walk skips inserts). Base char from `extra_bases`,
  not `strand.sequence`. Inserts are NOT added to `nt_key` (so `index_to_key`/display
  leave them None — CG display of inserts is a follow-up, like oxDNA Phase 1). mrDNA
  `model_from_basepair_stack_3prime` accepts them → each insert opens a new
  SingleStrandedSegment; ARBD simulates fine. Pins: `tests/test_mrdna_extra_bases.py`
  (10: count grows by extra-base total, unpaired, 3′+stack threading can-go-red, FENE-safe
  even spacing, base identity, flank-key naming, ssDNA-segment build, slow opt-in real-ARBD
  6hb-TT-all that also checks both display toggles). Validated live on RTX 3080 Ti (2hb TT×2
  → 92→96 nts, 1→3 ss segments, DCD written). (oxDNA equivalent: [[project_oxdna_extra_bases]].)
  - **DISPLAY — both toggles surface inserts (2026-07-04):**
    - **CG-beads toggle** already shows them: the coarse model beads each insert (2hb TT×2 →
      DNA beads 12→14, NAS 1→3), and `_extract_beads_aligned` keeps DNA beads, so they join
      the cloud + connect (no floating). No change needed.
    - **Deform toggle** needed wiring: `_display_positions` (mrdna_runner) now appends
      `{helix_id:"__xb__", bp_index:crossover_id, direction:k}` entries — each insert
      chord-lerped between its two flanking real nucleotides' RELAXED positions, via new
      `mrdna_bridge.extra_base_flank_keys` (reuses the oxDNA owning-strand map). The frontend
      already routes `__xb__` (oxDNA Phase 1: `toFemUpdates` passes through →
      `applyFemPositions` → `partitionExtraBaseUpdates` → `setExtraBaseInstanceFromSim`), so
      NO production frontend change. `_DISPLAY_VERSION` 2→3 regenerates stale display.json.
      Orientation = design base-normals (option B, same as real nts). Live gesture (toggle →
      see beads/slabs move) owes [[manual_validation_debt]] MV-MRDNA-JOBS (WebGL visual).

### Fine-stage display collapses a tight-bundle helix → coarse fallback (FIXED 2026-07-04)
Toggling the deform display on a FINE `2hb_2xT` job squashed ONE helix into a bead
**ring** (the other stayed a rod). Root cause: `nuc_pos_override_display_from_coarse`
assigns each relaxed bead to the nearest **design** axis, but `_sim_paths` feeds a fine
job the highest CG stage (`mrdna_relax-2`), whose initial structure has already DRIFTED
off the design frame (it's a multiresolution intermediate, not the clean B-DNA frame).
On a 2hb the two helices sit ~2.3 nm apart, so one helix's drifted beads get dumped onto
its neighbour (measured: h_XY_1_1 got 7 beads / 3 distinct bp vs h_XY_0_1's 35) → its
spline collapses to a 3.2 nm blob (≈38% of its 8.3 nm contour). The COARSE stage
(`mrdna_relax-0`) beads still sit cleanly at the design axes (7/7 split, perp 0.27 nm).
Straight 6hb ALSO collapsed a helix on fine (h_XY_0_3 → 51%); only well-separated
bundles were unaffected.
- **Fix (`mrdna_runner`):** `_display_positions` runs the fine reconstruction, then
  `_override_has_collapsed_helix` checks each helix's 3-D bounding-box diagonal vs
  `length_bp × rise`; if any helix is a blob (< 0.45×), it recomputes from the coarse
  stage (`_coarse_sim_paths` = lowest-numbered CG stage) and uses that if clean.
  `_DISPLAY_VERSION` 3→4 regenerates stale caches on read.
- **Collapse metric = 3-D bounding DIAGONAL, NOT axial projection (KEYSTONE):** a
  genuinely BENT helix (curved design's loop/skip bend) has a short axial projection but
  still spans a large arc — even a 180° semicircle keeps ~64% diagonal. Using axial extent
  would false-fire on curvature and drop the fine reconstruction the curvature readout
  needs. The diagonal only trips on a true collapse. So curved designs KEEP fine; only
  tight straight bundles fall back to coarse.
- Validated: 2hb → both helices 7.7/7.8 nm (ring gone), live `/display` API confirmed,
  Playwright screenshot (`frontend/e2e/mrdna_display_collapse.spec.js`) shows two extended
  strands. Pins: `test_mrdna_jobs.py::test_collapse_detector_flags_blob_but_not_full_or_bent`
  (blob trips, full rod + full-contour bent arc do NOT).

### Overstretched backbone bonds (partial mis-assignment) → same coarse fallback, generalised (2026-07-04)
6hb_2xT's fine display was a jumbled blob with long stray bonds (max 2.2 nm; 29 backbone
bonds > 1.3 nm). NOT a full collapse (so the diagonal detector missed it): the fine stage
assigned a helix only a **sparse, gappy** set of beads (h_XY_1_2 got 19 beads at bp
-1..11, 18, 39..42 — bp 12–38 nearly empty), and the per-helix spline **leaps across the
gaps** → 2.2 nm consecutive-backbone jumps on both strands. Same fine-stage
nearest-design-axis mis-assignment root cause as the 2hb collapse, just partial.
- **Generalised the fallback:** `_display_positions` now scores the fine reconstruction
  with `_reconstruction_badness` = `1000 × collapsed-helix + _count_stretched_backbone_bonds`
  (consecutive same-helix backbone steps > 1.3 nm; canonical helical P–P ≈ 0.67 nm) and
  falls back to the coarse stage when it scores **distinctly cleaner** (fires on
  collapse OR ≥12 stretched bonds, switches only if coarse's badness is strictly lower).
  6hb_2xT: fine 29 → coarse **14** stretched, max 2.2 → 2.0 nm, blob → recognizable
  bundle. `_DISPLAY_VERSION` 4→5.
- **Bond-stretch is a LOCAL metric → safe for curved designs:** bending doesn't stretch
  backbone P–P bonds, so a genuinely curved fine reconstruction is NOT penalised and keeps
  fine (unlike an axial-extent metric). The ≥12 gate + strictly-cleaner rule also keeps a
  clean fine reconstruction, so only artifact-heavy fine displays fall back.
- **CURVATURE tradeoff (accept + flag):** curvature (`load_curvature` → `measured_curvature`)
  reads the SAME display positions, and the coarse stage carries no twist → less bend
  (~2° vs fine's ~12–16° on 6hb_curved, LESSONS A9). So a design whose fine reconstruction
  is artifact-heavy now shows LOWER simulated curvature. This is acceptable: an
  artifact-heavy (jumpy) fine axis gives a NOISY/unreliable curvature anyway; a clean fine
  reconstruction (few stretched bonds) is kept and its curvature preserved. If a curved
  design regresses, decouple curvature onto its own fine-stage reconstruction path.
- **RESIDUAL (not fixed):** coarse still leaves ~14/700 stretched bonds on 6hb_2xT (≤2.0 nm),
  at crossover-adjacent bp and helix-end/negative-bp spline endpoints — inherent to splining
  through sparse 5 bp/bead CG beads + ideal duplex reconstruction. Eliminating them needs a
  reworked reconstruction (spline endpoint handling / crossover backbone), a larger change.
- Pins: `test_stretched_bond_detector_and_badness`; Playwright `mrdna_6hb_bonds.spec.js`
  (reports max/median/over-threshold + screenshot).

### Beadless helix-end → flat ring; fixed AT THE SOURCE by straight extrapolation (2026-07-04)
Re-running the fine display on `6hb_2xT` still showed a **ring of bases** (a helix end
"collapsed onto a 2-D plane to make a circle") near the top of the bundle, even after the
coarse-fallback work above. Root cause is NOT the fallback — it's the reconstruction itself.
`nuc_pos_override_display_from_coarse` (mrdna_bridge) placed each nucleotide on the per-helix
cubic spline at **`t = np.clip(bp, t_lo, t_hi)`** where `t_lo/t_hi` = min/max **bead-covered**
bp. When the fine stage's nearest-design-axis assignment leaves a helix END beadless (the same
tight-bundle drift as the collapse/stretched-bond modes, localized to one terminus), **every bp
past `t_hi` was pinned to the single point `cs(t_hi)`**, and the duplex twist fan (line ~772)
then splayed those pinned nucleotides into a flat circle of radius **HELIX_RADIUS** — literally
the reported ring.
- **Why BOTH fallback detectors miss it (KEYSTONE):** the whole-helix bounding **diagonal**
  stays large (the rest of the helix is extended, so ~16 nm ≫ 0.45×contour → `_override_has_collapsed_helix`
  silent), AND ring neighbours are only `2R·sin(twist/2) ≈ 0.58 nm` apart (well under the 1.3 nm
  jump threshold → `_count_stretched_backbone_bonds` silent). On the stochastic re-run 6hb_2xT
  scored fine-badness **11**, one under the `≥12` gate — the metric was both blind to end-rings
  AND riding a knife-edge. So a detector tweak can't fix this; the source must.
- **Fix (source):** new pure helper **`mrdna_bridge._relaxed_axis_at_bp(cs, bp, t_lo, t_hi,
  ideal_axis_hat, rise_ang)`** — inside `[t_lo,t_hi]` evaluates the spline; BEYOND it continues
  the axis **straight along the endpoint tangent at ideal B-DNA rise** instead of clipping.
  Linear (not cubic) extrapolation keeps the tail bounded and canonically spaced, so it never
  trips the stretched-bond fallback. Display fn now calls it in place of the `clip`+`cs(t)` axis
  lookup. `_DISPLAY_VERSION` **5→6** (stale ring caches regenerate on read). Only the DISPLAY fn
  had the bug: the re-idealised siblings (`nuc_pos_override_from_mrdna_coarse` L548,
  `nuc_pos_override_from_arbd_strands` L937) set position from `ideal_axis_pt = ax_s +
  local_i·rise·ideal_axis_hat`, so their clip only picks the tangent direction — no pin, no ring.
- On the clean on-disk 6hb_2xT job the fix is a strict improvement (per-helix diagonals 16→19–22
  nm = full contour as the ends extend; stretched-bond count unchanged at 11 → no new jumps).
- Pins: `test_mrdna_pipeline.py::TestBeadlessEndNoRing` (2 pure unit tests, no mrdna/ARBD/MDA:
  extrapolation-not-pinned + full-duplex-tail-extends-vs-clip-makes-a-flat-HELIX_RADIUS-ring).
  Both proven can-go-red by reverting the helper to clip. This also partly addresses the
  "helix-end/negative-bp spline endpoints" RESIDUAL noted in the stretched-bonds section above.

### Far-end single-stranded scaffold crossovers → stretched bonds; fixed by ssDNA harvest + both-ends anchor (2026-07-04)
After the ring fix, 6hb_2xT's deform display still showed **scaffold backbone bonds
stretched 4–6 nm at the far ends** (worst 6.36 nm, a helix-to-helix crossover at bp −12).
Mechanically diagnosed (NO geometric reasoning): the helix ENDS (bp −1..−12, 42..53) are
**genuinely single-stranded** — 104 unpaired scaffold nts, ZERO with a complementary
staple (checked via `_build_nt_arrays` pairing + design presence). mrDNA correctly models
them as ssDNA (`NAS` beads); there are NO dsDNA (`DNA`) beads there. So the crossovers DO
register in the sim (short `NAS` bonds) — the stretch was a **display** artifact: the
reconstruction phantom-duplexed each unpaired nt onto the dsDNA helix spline (extrapolated
straight past the beadless end), so at a crossover the two helices' extrapolated ends
diverge and the connecting scaffold bond stretches.
- **Fix (`_display_positions`, mrdna_runner):** after the ds reconstruction, merge the
  relaxed ssDNA positions from **`nuc_pos_override_ssdna_from_arbd(..., prefer_continuity=True)`**
  (the SAME harvest the MD seed uses), `{**ds, **ss}` so ss wins at unpaired keys.
- **`prefer_continuity` flag (new, DISPLAY-only):** the seed's ss placement maximizes
  CLEARANCE (avoid MD clashes) and will leave a run at its detached-ideal design position —
  wrong for display (floats the junction). Display needs CONTINUITY: pick the
  highest-fidelity anchored candidate instead of the farthest-from-body one.
- **Both-ends "blend" (KEYSTONE):** the far-end scaffold runs are **bridging loops**
  (ds…ss→crossover→ss…ds) with a relaxed root at BOTH ends; anchoring only one (the seed's
  single root) floats the far ss/ds junction (4.2 nm). `_ssdna_runs` now returns
  `root5_key`/`root3_key` (both sides); the new pure `_blend_run_both_ends(ideal, d5, d3)`
  adds each nt its NEAR root's ideal→relaxed displacement, linearly blended 5′→3′ — pins
  BOTH ends one bond from their relaxed roots while preserving the ideal loop shape. Result
  on 6hb_2xT: max scaffold bond **6.36 → 2.02 nm** (residual 2.02 is the pre-existing
  ds-spline artifact, not a crossover); far-end crossovers now reconstruct at **1.4–1.9 nm =
  their design inter-helix gaps** (1.99/2.00/1.42). Placement: 30/30 runs `blend`.
- **Seed path UNCHANGED:** `prefer_continuity` defaults False, so the blend candidate is
  skipped and the clearance selector + single-root behavior are byte-identical for the MD
  seed. `_ssdna_runs` only ADDS keys. `_DISPLAY_VERSION` 6→7.
- Pins: `test_mrdna_pipeline.py::TestSsdnaBridgeContinuity` (3 pure unit: `_ssdna_runs`
  both-roots for a bridging run via monkeypatched `_build_nt_arrays`; `_blend_run_both_ends`
  pins both ends where single-anchor floats; n==1 centers). Free overhangs (one root only)
  keep spline/translate — unchanged.

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

## Three-Layer Law
mrDNA output is **Physical / display only** — relaxed positions deform the render
via `applyFemPositions` and draw the bead overlay; NEVER written into topology.
The MD-seed handoff is likewise Physical-layer: the relaxed structure is a
NAMD/GROMACS INPUT artifact, never topology. Same discipline as the oxDNA + MD displays.

See also: [[project_mrdna_arbd_setup]] (install), [[project_mrdna_bead_model]]
(1 bead/bp fine-stage caveat — but this panel uses the COARSE 5bp/bead stage),
[[project_md_engines_panel]] (mrDNA/ARBD install rows), [[feedback_cg_pipeline_lessons]].
