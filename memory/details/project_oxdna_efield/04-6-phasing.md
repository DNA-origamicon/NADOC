# 6. Phasing — supporting detail

[Topic head](../../project_oxdna_efield.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

- **"Anchor lets the strand move" diagnosis (2026-06-18).** User reported a field run drifting 10s of
  nm despite an overhang anchor. Investigation (real binary, on `1hb_efield_test`):
  - Anchors ARE correctly applied at creation (verified the live job's `field_forces.txt`: 10 traps,
    `stiff=1000`) and ARE immobile — anchored beads drift **0.022–0.026 nm** in the raw sim frame.
  - What moves 10s of nm is the **un-anchored** part. Demo: overhang anchor (10 nt) → anchored 0.022 nm,
    free duplex 15.7 nm; **cluster anchor (all 94 nt) → everything 0.026 nm, nothing free**. A
    single-stranded overhang is a flexible HINGE, so anchoring it can't constrain the rigid duplex's
    swing. Fix is anchor-SELECTION: anchor the duplex/cluster to hold the whole structure.
  - The ~2 nm extra wobble the display adds is the whole-structure Kabsch alignment (it doesn't treat the
    anchor as the fixed frame) — not the dominant effect here.
  - GOTCHA for future: oxDNA's `ConstantRateForce` (type=string) **rejects dash-RANGE particle specs**
    ("couldn't get from particle 0 to particle 41") — for a DNA system `a-b` is a 5'→3' topology
    walk, not an index span, so it throws when a,b aren't strand-connected. For anchors we keep
    `particle = -1` (the stiff trap holds them regardless). **UPDATE 2026-07-17: a comma LIST
    `particle = 0,1,…,K-1` IS viable** — `Utils::get_particles_from_string` splits on commas first
    and validates each index; the forces file has no line-length cap (`getdelim`), so listing ~14k
    origami indices on one line works. This is how surface capture-strand exclusion from the field
    is implemented (`field_string_block(..., n_particles=K)`; see [[project_surface_strands]]). Only
    the *range* syntax was unviable, not per-index selection.
- **Field-run display: anchor = positional-only reference (2026-06-18).** Clicking "OxDNA display"
  on a field run flung the structure to distant positions because the display Kabsch-aligned the WHOLE
  structure (rotation+translation, all beads) — the swung duplex dominated the fit, rotating away the
  very reorientation being studied and throwing the anchor. Fix: `unwrap_align_to_reference` gained
  `align_keys` (alignment subset) + `rotate` flag. For a field run the display now PBC-unwraps (keeps
  the structure whole) then does a **translation-only** fit on the ANCHORED beads — anchor → its design
  position, NO rotation — so the field-induced swing stays visible. Anchor keys are stored on
  `child.efield["anchor_keys"]` at creation (`write_field_forces` returns them); `get_oxdna_display`
  passes `align_keys=…, rotate=False` when present. Verified on a fresh run: anchored offset ~0.8 nm
  (CM pinned; residual is the anchor's free orientation = "positional not rotational"), free swing 8.8 nm
  preserved, max coord 16 nm (not flung). CAVEAT: only NEW field jobs store `anchor_keys` (old jobs fall
  back to whole-structure Kabsch). Tests: `test_unwrap_anchor_positional_no_rotation` +
  `test_write_field_forces_returns_anchor_keys`. (Flex-map/trajectory still use whole-structure Kabsch —
  a follow-up could thread `align_keys` through `production_rmsf`/`composite_trajectory` too.)
  - **FOLLOW-UP root cause (structure STILL showed tens of nm off-origin):** the field child's
    `conf.dat` IS the parent's relaxed `last_conf`, which the relaxation MD diffuses far off-origin (no
    positional anchor during relaxation). Measured on `1hb`: design geom 6.7 nm from origin, relaxed
    seed 14.2 nm, field last_conf 22.5 nm — so anchoring onto the seed displayed everything ~14 nm out.
    FIX: align the field display to a regenerated origin-frame DESIGN geometry (`_design_ref_conf` →
    cached `design_ref.dat` via `_geometry_for_design`+`write_configuration`), NOT the job's `conf.dat`.
    After fix: displayed anchor 0.13 nm from its design position, structure COM 8.8 nm from origin (was
    22.5). Test `test_field_display_aligns_to_design_not_drifted_seed` (a +30-ox-drifted seed still
    displays at the design position). Works for OLD field jobs too (ref regenerated from the design
    snapshot) — though old jobs still lack `anchor_keys` so they fall back to whole-structure Kabsch;
    re-run to get the positional display.
- **Live mode composes any element set (2026-06-23, follow-up).** Live now mirrors the consolidated
  run: it composes E-field / hard surface / anchors independently (only a field requires ≥1 anchor;
  anchors-only / surface-only / nothing=free dynamics all allowed). Backend: `LiveStartRequest` carries
  `field`/`surface`/`anchors` (like `RunRequest`); `routes_oxdna_live._prepare_live_rundir` uses
  `write_run_forces` + `build_run_stage`; `_OxpyStepper` tolerates a fieldless run (`self._field=None` →
  `set_field` no-ops). Frontend: the Live controller takes `getRunElements` (the SAME closure the panel's
  Full Sim run uses) and only blocks field-without-anchor. The **"Start Production" button is renamed
  "Full Sim"**. Verified on real oxpy (field+anchor / anchors-only / free dynamics all step + stop +
  clean up). Tests: `test_oxdna_live_session.py` 14 + `oxdna_live_controller.test.js` updated.
- **Display-toggle protection during Live (2026-06-23, follow-up).** While a live session runs, the
  panel's **OxDNA display / Flexibility map / View trajectory** toggles are DISABLED (they share the one
  bead overlay) so a click can't fight Live. `oxdna_jobs_panel._updateButtons` computes `liveOn =
  oxdnaLive.isOn()` and locks all three (display had no gate before); the controller dispatches
  `nadoc:oxdna-live-start` AFTER `_on=true` (so `isOn()` is true when the panel locks) and
  `nadoc:oxdna-live-stop` on teardown (panel re-runs `_updateButtons` → unlock). Pinned in
  `oxdna_jobs_panel.test.js` (toggles flip disabled on start / enabled on stop) + controller event tests.
- **Phase 3 (not built):** Deflection-map viz (`/deflection` route via `measure_field_response`'s
  displacement + a frontend `deflectionColorMap`). → MV-EFIELD.

## Field+anchor setup viz (2026-06-19, SHIPPED)
While configuring a field run, the field direction + the pinned elements are now made obvious:
- **Thick 3D arrow**: `scene/efield_gizmo.js` arrow is a solid **cylinder shaft + cone head**
  mesh (`MeshStandardMaterial`, emissive) instead of `THREE.ArrowHelper`'s 1-px line. Same API
  (setVector/getVector/setColor/handle at origin+dir·len); group `efield-gizmo`, arrow subgroup
  `efield-gizmo-arrow`. Shows whenever the E-field card is open **OR a selected oxDNA job
  applied/is applying a field** (2026-06-19): `efield_setup` decouples arrow visibility from the
  card via `_jobFieldActive` (set by `applyConfig`) + `_syncGizmo()` (arrow on if `_open ||
  _jobFieldActive`); `applyRunConfig` no longer force-opens the card; leaving the Dynamics tab still
  drops the arrow. Tests in `efield_setup.test.js` (collapsed-card arrow / null hides it / tab-change drops it).
- **Purple anchor glow**: `scene/anchor_glow.js` (`initAnchorGlow({designRenderer, store})` +
  pure `resolveAnchorEntries`) maps anchor descriptors → backbone entries (overhang→`nuc.overhang_id`,
  domain→`strand_id`+`domain_index`, cluster→`clusterMemberFilter`) → `designRenderer.setAnchorGlow`
  (new purple `createGlowLayer(scene, 0xb14aff, 3.6, 'anchorGlow')`, cleared on rebuild, refreshed in
  `refreshAllGlow`). **UPDATED 2026-07-16 — the field gate is GONE.** It used to show only when
  **field enabled (`efieldSetup.isEnabled()`) AND ≥1 anchor**, which meant an added anchor stayed dark
  until something turned a field on (clicking a job row restored the job's field first — the reported
  bug). An anchor is pinned regardless of any field, so main.js `_refreshAnchorGlow` now shows the
  ACTIVE ENGINE's anchors, full stop. Every engine's card fires `nadoc:anchors-change {engine,
  anchors}` (one `_emit()` per mutation, never at construction → no TDZ on the main.js consts); main.js
  caches per engine and `engineSelector.onSelect` re-refreshes. `efield_setup.onChange` no longer
  touches the glow. Cleared on leaving the Dynamics tab, restored on return. See
  [[project_simulate_panel_overhaul]] for the full entry. Tests: `anchor_glow.test.js` (9) + gizmo tests still
  green. Live-verified the arrow is a solid cyl+cone mesh + the anchorGlow layer is wired (throwaway
  e2e introspection). Live purple-on-actual-beads = human-eye → MV-ANCHGLOW.

## Live (ephemeral, re-aimable) field mode (2026-06-23, SHIPPED)
A **"Live" toggle** (`#oxdna-jobs-live-btn`, between ▶ Relax and Start Production) runs an
**ephemeral in-process oxpy field session** that stores NOTHING — no `OxdnaJob`, no jobs-list
entry, no persisted frames, just a temp rundir removed on stop. It reuses the batch field
physics wholesale (`backend.physics.oxdna_live.LiveOxdnaSession` + `_OxpyStepper`, the AF-21
engine driven by `headless_oxdna_build._prepare_field_rundir`); the live re-aim mutates
`force.F0`/`force.dir` between bursts (needs the [[oxpy-binding-patch]]).
- **Backend.** `backend/core/oxdna_live_runner.py` — an in-memory `LiveSession` registry + a
  background-thread worker (`with session: set_field → loop{apply pending field; run(burst);
  capture frame}`), single-active-session policy (`stop_all()` before each start), thread-safe
  latest-frame + pending-field. `backend/api/routes_oxdna_live.py` (mounted in `main.py`):
  `GET /oxdna/live/available` (probes `oxpy.forces.BaseForce` has F0/dir), `POST /oxdna/live/start`
  (seeds from a completed relaxed job's `_latest_relaxed_conf` via `_prepare_field_rundir`, ≥1
  anchor required), `POST …/{id}/field` (live re-aim), `GET …/{id}/frame` (current config as an
  applyFemPositions payload — `read_configuration_unwrapped` against an origin-frame design_ref,
  anchor-keys positional/no-rotation, true backbone site), `POST …/{id}/stop` (teardown + rmtree).
- **Frontend.** `ui/oxdna_live_controller.js` `initOxdnaLive({oxdnaDisplay, getSelectedJob,
  getFieldSpec, getAnchors})` owns the toggle: on start it POSTs, polls `…/frame` every 500 ms →
  `oxdnaDisplay.displayLiveFrame(positions)` (a NEW `'live'` mode in `oxdna_display.js`, CG-only —
  no heavy rep, no jobId), and pushes field re-aims (throttled 150 ms) when the efield gizmo/inputs
  change (main.js wires `efieldSetup.onChange → oxdnaLive.onElementsChanged()`; the anchor halo no
  longer keys off the field, so it is NOT refreshed from here — 2026-07-16).
  Mutual exclusion: starting Live dispatches `nadoc:oxdna-live-start` → panel `_allDisplaysOff()`;
  the panel calls `oxdnaLive.stop()` from the Relax/Production buttons + the display/flex/traj
  toggles. Leaving the Dynamics tab / switching design / selecting another job stops Live. main.js:
  +1 import + factory init + the panel `oxdnaLive` dep + the onChange wrap (wiring only).
- **Verified.** Backend `test_oxdna_live_session.py` (12, GPU-free fakes; full suite 3066). Frontend
  `oxdna_live_controller.test.js` + `displayLiveFrame` in `oxdna_display.test.js` (suite 1654);
  vite build + smoke clean. **REAL oxpy route verified end-to-end on this box** (RTX 2080 + patched
  ~/oxDNA): start → 504-position frame → live re-aim advances bursts → stop → rundir cleaned. The
  in-browser button→gizmo-drag→structure-follows + Relax/Production-stops-Live gesture is human-eye
  only → **MV-OXLIVEFIELD** (distinct from MV-OXLIVE, which is the display-follow-a-running-job item).

## Live latency speedups — CUDA + in-memory readout (2026-06-23)
Profiled the live loop (`set_field → run(burst) → capture_frame → poll`) for "immediate visual
feedback" while playing with field/surface/anchors. Three physics-preserving wins shipped:
- **#1 Live steps on CUDA (was hardcoded CPU).** `_prepare_live_rundir` built the stage
  `backend="CPU"`; flipped to `"CUDA"`. Benchmarked oxpy steps/sec on THIS box (RTX 2080 SUPER,
  WSL2) over real jobs — CPU vs CUDA: N=94 5472/6531 (1.2×), **N=1076 241/3677 (15×)**,
  **N=6012 43/4114 (96×)**, **N=14774 15/2391 (163×)**. CPU is only competitive below ~200 nt; a
  6k-nt design is ~12 s/500-step-burst on CPU vs ~0.12 s on CUDA. CUDA has a per-burst floor
  ~75–210 ms (launch+sync) so tiny systems stay snappy too. **Live field steering VERIFIED on CUDA**
  (mutating `force.F0`/`force.dir` between bursts propagates to the GPU: free beads swing 21.8 nm on
  a +x→−x re-aim, anchors hold 0.014 nm — same as CPU). Decision (user): **always CUDA**, matching
  the relaxation jobs. CUDA works fine under WSL — the "may be worse on WSL" worry did NOT
  materialize, so NO automation-ledger handoff was filed.
- **#2 In-memory readout (no per-frame file round-trip).** The frame builder did
  `print_configuration()` (write `last_conf.dat`) + `read_configuration_full` (parse) + the parse was
  THEN re-done inside `read_configuration_unwrapped` (which also re-parsed the constant design_ref) —
  3 full-config parses + 1 disk write per frame, one fully redundant. New
  `oxdna_interface.configuration_full_from_particles(particles, design)` builds the identical
  `(h,bp,dir)→{pos_nm,a1,a3}` map straight from oxpy `config_info().particles()`: **a1 = orientation
  col 0, a3 = col 2** (verified equal to the `.dat` a1/a3 to 1e-14), `pos_nm = p.pos × OXDNA_LENGTH_UNIT`.
  `_OxpyStepper.configuration_map()` + `.box_nm()` expose it; the redundant `.configuration()` call in
  `_make_frame_builder` is gone. End-to-end the in-memory display frame == the old file frame to
  **7e-13 nm** (real 1076-nt crossover design, 300 live steps) — the BFS-unwrap+box-shift+Kabsch
  absorbs the in-memory-pos box-image offset.
- **#3 Cache the constant per-frame work.** `unwrap_align_to_reference` grew an optional `adj=` param
  (the bond-adjacency, factored into `_build_unwrap_adjacency`); `_make_frame_builder` parses the
  origin-frame `design_ref` ONCE and builds the graph ONCE, reusing both every frame. Per-frame cost
  now: in-memory particle read + BFS + Kabsch (no file I/O, no graph rebuild, no ref re-parse).
- **NOT yet done (further levers, deferred):** push frames over WebSocket (mirror `ws/md-jobs`) instead
  of the 500 ms REST poll; adaptive/smaller burst size now that per-frame overhead dropped; binary/typed
  frame transport. The CUDA-burst floor + poll interval are the remaining latency, not the readout.
- **Tests.** GPU-free: `test_configuration_full_from_particles_matches_file_readout`,
  `test_unwrap_precomputed_adj_matches_builtin` (test_oxdna_relaxation). Real-oxpy gated (CPU, convention
  lock): `test_configuration_map_matches_file_readout_real_oxpy` (test_oxdna_live_session). Existing live
  + headless oxdna suites green; ruff clean. **Live in-browser snappiness on a big design is human-eye →
  owes MV-OXLIVE-CUDA** (steering responsiveness + structure-follows at CUDA speed, not yet app-verified).
