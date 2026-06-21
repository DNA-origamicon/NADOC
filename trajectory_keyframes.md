# Trajectory Keyframes — oxDNA/MD trajectory animation export

Feature loop tracker. Goal: let an animation keyframe **play a range of frames from an
oxDNA or NAMD/MD trajectory** (instead of lerping between design poses), so simulation
trajectories can be composed into exportable animations (WebM/GIF now, photo-mode later).

UI seed: split the single "Add Keyframe" button into **`+ Add Keyframe`** and
**`+ Add Trajectory`**. The trajectory button creates a *special purple keyframe* that keeps
the normal text/delete/pose controls but swaps the State row for a **trajectory-job dropdown**
+ an embedded **range slider** (stage-marked ticks) selecting the `[start,end]` frames to play
through before the next keyframe.

Three-Layer Law: a trajectory is **Physical/display-state only** — applied via
`designRenderer.applyFemPositions(...)` (the same sink oxDNA/MD display already use). Never
written back to topology.

---

## Locked decisions (user, 2026-06-21)

| Question | Decision |
|---|---|
| Engine scope, phase 1 | **oxDNA first, NAMD later.** oxDNA's `/trajectory` returns all frames at once (cached, synchronous) → instant scrub + deterministic export. NAMD streams async over WebSocket (`{action:'seek',frame_idx}`) → deferred to Phase 2 (needs all-DCD-frames pre-buffer for the synchronous export loop). |
| Frame-range → playback time | **Reuse the keyframe's hold window.** The `[start,end]` range plays across this keyframe's `hold_duration_s` seconds; the `transition_duration_s` window is the camera lead-in (model frozen at `frame[start]`). The next keyframe transitions away from the trajectory's last frame. |
| Camera during a trajectory segment | **Lerp toward this keyframe's pose** (existing pose-dropdown behavior; camera arrives by `transEnd`, holds during playback). No camera-code change needed. |
| Representations that follow | **CG + atomistic/surface** (heavy). Phase 1 ships **CG** (`applyFemPositions`); **Phase 1b** adds per-frame atomistic/surface reconstruction (downsampled, the expensive part). |

---

## Known reference points (grounded 2026-06-21)

- **Model**: `AnimationKeyframe` — [backend/core/models.py:1420](backend/core/models.py#L1420). Container `DesignAnimation` at :1469.
- **Keyframe routes**: [backend/api/routes_animations.py](backend/api/routes_animations.py) — `CreateKeyframeBody` (:52), `PatchKeyframeBody` (:73), `create_keyframe` passthrough (:159), `update_keyframe` uses `model_fields_set` so explicit values propagate (:208). No new route needed.
- **Panel add-button**: `#animation-add-kf-btn` [index.html:4131](frontend/index.html#L4131); handler [animation_panel.js:964](frontend/src/ui/animation_panel.js#L964). Row builder `_makeKfRow` (:473); purple-accent precedent = strand-anim kf (:485,:495). State row (:779). Timing row (:876).
- **Player**: [animation_player.js](frontend/src/scene/animation_player.js) — factory deps (:51), `_buildSchedule` (:244), `_bakeStates` (:386), `_applyAt` (:712), `stop()` (:1028). Segment carries `{fromState,toState,startT,transEnd,endT,...}`.
- **Display sink + frame mapping**: `oxdna_display.js` `framesToUpdates(keys, frame)` (:89) — 6 floats/key (xyz + a1 nx,ny,nz); `loadTrajectory`/`showFrame` (:202,:220). Trajectory response shape: `{ready, n_frames, keys:[[h,bp,dir],…], frames:[flat6N…], markers:[{frame,label,kind,stage_name}], stages}`.
- **Trajectory player ticks**: `oxdna_trajectory_player.js` `markerPositions(markers,nFrames)` (:16) — reuse for the row's stage ticks.
- **Client helpers**: `listOxdnaJobs()` [client.js:1958](frontend/src/api/client.js#L1958), `getOxdnaTrajectory(id)` (:1973). Job filter `filterJobsForPart(jobs,partPath,showAll)` + `jobDisplayName(job)` in `md_jobs_panel.js`/`oxdna_jobs_panel.js`.
- **main.js wiring**: player init [main.js:1505](frontend/src/main.js#L1505) (has `getDesignRenderer`); panel init ~:6091.

---

## Phases

### Phase 1 — oxDNA CG trajectory playback  ✅ CODE COMPLETE (2026-06-21) — live gesture owes MV-TRAJ-KF
Scope: the trajectory keyframe end-to-end with **CG** geometry only; live playback + WebM/GIF export.

Tasks:
1. **Backend model** — add to `AnimationKeyframe`: `trajectory_job_id: Optional[str]=None`,
   `trajectory_engine: Literal["oxdna","namd"]="oxdna"`, `trajectory_frame_start: Optional[int]=None`,
   `trajectory_frame_end: Optional[int]=None`. Mirror into Create/Patch bodies + `create_keyframe`
   passthrough. (Presence of `trajectory_job_id` = "this is a trajectory keyframe".)
2. **Pure module** `frontend/src/scene/trajectory_range.js` — `frameAtProgress(start,end,p)`,
   `clampRange(start,end,nFrames)`. Vitest.
3. **index.html** — split the add row into `#animation-add-kf-btn` + `#animation-add-trajectory-btn`.
4. **animation_panel.js** — trajectory add handler (creates kf with `trajectory_job_id:null` +
   `trajectory_engine:'oxdna'`); in `_makeKfRow`, detect trajectory kf → purple row + "Trajectory"
   badge + job dropdown (`listOxdnaJobs` filtered to current design) + range slider with stage ticks.
5. **animation_player.js** — new dep `onFetchTrajectory(jobId)`; `_buildSchedule` tags segment
   `trajectory={jobId,frameStart,frameEnd}`; `_bakeStates` fetches trajectory once per job into
   `_bakedTrajectories`; `_applyAt` trajectory branch (camera as normal, geometry from frame, early
   return); `stop()` clears `_bakedTrajectories`.
6. **main.js** — `onFetchTrajectory:(id)=>api.getOxdnaTrajectory(id)` (1 line); ensure panel has
   `getWorkspacePath`.
7. **Verify** — `just test` + `just test-frontend`; exercise in-app on a completed oxDNA job →
   `MV-TRAJ-KF` row in `manual_validation_debt.md`.

Known Phase-1 limitation (accepted, user flagged "may be messy"): the K→K+1 boundary jumps from the
trajectory's last (Physical) frame back to the next keyframe's design-CG geometry — no morph. Clean
fix (treat trajectory-end as a baked from-state) is deferred.

### Phase 1b — atomistic + surface follow the trajectory  ✅ CODE COMPLETE + BACKEND-VALIDATED (2026-06-21)
Per-frame atomistic/surface reconstruction from each aligned trajectory frame, baked at a **downsampled**
subset (caps: 40 atomistic / 20 surface frames per job) and snapped to the nearest baked frame at playback.
- **Backend:** refactored `composite_trajectory` → `_aligned_downsampled_frames` (ordered full per-nuc
  dicts) + `_flatten_cg_frame`; added `composite_trajectory_atomistic` / `composite_trajectory_surface`
  (reuse `build_atomistic_model` nuc_pos/axis overrides + `compute_surface`) in
  [oxdna_health.py](backend/core/oxdna_health.py); routes `POST /oxdna/jobs/{id}/frames-atomistic` +
  `/frames-surface` with a shared `_composite_inputs` lineage helper in
  [routes_oxdna.py](backend/api/routes_oxdna.py). Same wire format as the design atomistic/surface batches.
- **Frontend:** `getOxdnaFramesAtomistic/Surface` client helpers; player gained
  `onFetchTrajectoryAtomistic/Surface` deps, `_bakedTrajAtom`/`_bakedTrajSurf` maps, a Phase-2 heavy bake
  in `_bakeStates` (per-job union range → `strideIndices` → batched fetch), and a snap-to-nearest apply in
  `_applyAt` (`applyPositionLerp(arr,arr,0)`). Pure `strideIndices`/`nearestOf` added + tested.
- **Validated on real job `6ad892196278`:** atomistic = 66150 floats/frame (== design atom count → atom
  order matches the design batch); surface meshes vary topology per frame (66886 vs 61282 verts → frontend
  rebuilds). Both HTTP routes return 200 with correct shapes.
- **Tests:** backend `just test` 2924 passed (+2: atomistic-matches-design-atoms, surface-shape); ruff
  clean. Frontend `trajectory_range.test.js` 17 passed (+strideIndices/nearestOf/formatJobTime); `vite
  build` OK; `just smoke` 23/23. Live in-app playback with heavy reps active → folds into MV-TRAJ-KF.

### UX polish (2026-06-21) — computation indicators ✅
- Trajectory-job dropdown options now show a **timestamp** (`name · Mon D HH:MM` from `created_at`) so
  same-named runs are distinguishable (`formatJobTime`).
- **Loading spinner** in the range row while a trajectory's metadata downloads (`makeSpinner` +
  "Loading trajectory…"); "Loading jobs…" placeholder while the job list fetches.
- **Heavy-rep notice** under the slider ("Atomistic / surface reps re-build each frame — playback +
  export are slower"); the bake popup now says "Building atomistic / surface frames — this can take a
  while…" when heavy reps are active.

### Phase 2 — NAMD/MD trajectories  ⬜ NOT STARTED
Add MD jobs to the dropdown. Pre-buffer all DCD frames (solve async WebSocket seek for the synchronous
`seekTo()` export loop).

### Phase 3 — photo-mode export of trajectory animations  ✅ WORKS BY CONSTRUCTION (2026-06-21) — pending live verify
No new code needed. Photo-mode preview ([photo_panel.js:931](frontend/src/ui/photo_panel.js#L931)
`player.play(anim)`) and export ([export_video.js:91](frontend/src/scene/export_video.js#L91)
`exportPhotoVideo` → `player.play` bakes, then `player.seekTo(t)` per frame → `photoRenderer.renderToBlob`)
drive the **same** `_applyAt` path that handles the trajectory branch. So a trajectory keyframe's CG +
atomistic/surface frames render through photo mode exactly as in the normal WebM/GIF export. Confirmed by
reading the export loop; the live high-res render is human-eye (folds into MV-TRAJ-KF). Caveat to check in
app: if a photo **export-representation upgrade** activates surface/atomistic in a way the player's
`getSurfaceRenderer()/getAtomisticRenderer()` mode doesn't reflect at bake time, that rep won't have been
baked for the trajectory — verify with the rep you intend to publish.

### Phase 2 — NAMD/MD trajectories (CG)  ✅ CODE COMPLETE + BACKEND-VALIDATED (2026-06-21)
NAMD jobs now appear in the trajectory-keyframe dropdown and play through the same animation path as
oxDNA. Solved the async-WebSocket problem by adding a **synchronous REST composite endpoint** that
mirrors oxDNA's shape, so the player path is reused unchanged.
- **Backend:** new `backend/core/md_trajectory.py` — `md_composite_trajectory(topology, segments, ref,
  design)` returns the SAME `{ready, n_frames, keys, frames, markers, stages}` payload as oxDNA's
  `/trajectory` (6 floats/nuc: backbone xyz + a1 base normal). The per-frame DNA→NADOC bead extraction
  (PBC unwrap → hybrid design-eq correction → Kabsch align → P→C1' normals) is **ported from the live
  Display-MD WebSocket** (`ws.py` `_load_sync`/`_seek_sync`, nadoc path) into a self-contained
  random-access reader — **`ws.py` is left untouched** (zero regression risk to the validated live
  display; keep the math in sync). Route `GET /md/jobs/{id}/trajectory` ([routes_md.py](backend/api/routes_md.py),
  `_md_segment_dcds` gathers every written segment's newest DCD; loads all into one Universe with
  per-segment boundary markers; deforms the **active** design like the live MD toggle).
- **Frontend:** `listMdJobs`/`getMdTrajectory` client helpers; the trajectory dropdown lists oxDNA **and**
  NAMD jobs tagged `[oxDNA]`/`[NAMD]` (+ timestamps), and selection stores `trajectory_engine`; the player
  threads engine through `onFetchTrajectory(jobId, engine)` (oxDNA vs MD endpoint) and **skips heavy-rep
  baking for NAMD** (NAMD all-atom topology ≠ design atomistic serial order → Phase 2b).
- **Validated on real NAMD job `5c6a87247a60` (2hb, 25-frame DCD):** composite returns 25 frames × 168
  nucleotides × 6 floats; **frame-0 rigid RMSD to design eq = 0.154 nm** (alignment correct); normals
  present; full HTTP route via TestClient (active design = 2hb) returns ready + correct shape.
- **Tests:** `tests/test_md_trajectory.py` (2, skipif-guarded on the real fixture) — composite
  shape+alignment + the route. Full backend suite green (one unrelated pre-existing flaky test —
  `test_field_validation_oracle_passes_with_deflecting_mock`, a stochastic mock oracle — passes on rerun
  + 3/3 in isolation). Frontend `vite build` OK; `just smoke` 23/23. Live NAMD-trajectory gesture →
  MV-TRAJ-KF.

### Phase 2b — NAMD heavy reps (atomistic/surface)  ✅ CODE COMPLETE + BACKEND-VALIDATED (2026-06-21)
NAMD trajectory keyframes now also drive atomistic + surface. Chose **Option B (render MD atoms
directly)** over mapping onto the design's idealized template — more accurate (shows the real all-atom MD
geometry) and reuses the live Display-MD ballstick extraction.
- **Backend** ([md_trajectory.py](backend/core/md_trajectory.py)): `_build_md_nadoc_ctx(..., with_atoms=True)`
  also builds the DNA heavy-atom index/elements (ported from `ws.py` `_load_sync` ballstick setup);
  `_extract_md_atoms_frame` (ported from `_seek_sync` ballstick: residue-local reconstruction + Kabsch) →
  `[{serial,element,x,y,z}]`; `md_frames_atomistic` → `{idx:{atoms,bonds:[]}}`; `md_frames_surface`
  (`compute_surface` on the MD heavy atoms, uniform colour v1) → `{idx:{vertices,faces}}`. Routes
  `POST /md/jobs/{id}/frames-atomistic` + `/frames-surface` ([routes_md.py](backend/api/routes_md.py),
  shared `_md_traj_inputs`). `ws.py` still untouched.
- **Frontend:** `getMdFramesAtomistic/Surface` client helpers; the player no longer skips NAMD in the
  heavy bake — it threads `engine` to the fetchers. **Surface** reuses the oxDNA path verbatim (same
  `{vertices,faces}` shape). **Atomistic** is the new bit: NAMD frames carry their OWN atom set, so the
  player calls `atomisticRenderer.update({atoms})` to swap it in (only when the snapped frame changes),
  vs oxDNA's `applyPositionLerp` over the design buffer. A `_mdAtomsActive` flag + `_ensureDesignAtoms()`
  (new `onRestoreDesignAtomistic` dep → `_atomSurface.applyAtomisticMode`) restores the design atom buffer
  before any design/oxDNA atomistic apply, so mixed animations don't address the wrong buffer; stop()
  resets it (the existing stop handler rebuilds design atoms).
- **Validated on real NAMD job `5c6a87247a60` (2hb):** atomistic = 3513 DNA heavy atoms/frame
  (P count 168 = nucleotide count → correct selection), elements O/C/N/P sane; surface = 10892 verts /
  21968 faces; both HTTP routes 200 via TestClient.
- **Tests:** `tests/test_md_trajectory.py` +1 (atoms+surface shapes; 3 total, skipif-guarded). Backend
  suite **2927 passed**; `vite build` OK; `just smoke` 23/23 (one flaky assembly-exit failure that passed
  on isolated rerun + full rerun). Live NAMD heavy-rep gesture → MV-TRAJ-KF.
- **v1 caveats:** NAMD surface is uniform-coloured (no per-strand colour — MD atoms lack the strand key);
  atomistic snaps to the downsampled baked subset (caps 40/20 per job) like oxDNA.

---

## Known issues / fixes

- **2026-06-21 — oxDNA jobs never populated the slider (MD did).** Root cause: the trajectory dropdown
  read `j.id` for oxDNA jobs, but oxDNA (and MD) jobs key their id as **`job_id`** — so oxDNA option
  values were `undefined` → selecting one stored an empty job id → `_loadMeta(null)` → "no trajectory
  yet", sliders disabled. (MD used `j.job_id` and worked.) **Fix:** extracted the oxDNA+MD normalization
  into the tested pure `normalizeTrajJobs(oxJobs, mdJobs, partPath)` (both engines map `job_id → id`);
  pinned by `animation_panel.normalize.test.js` (5). This was the real reason oxDNA trajectory keyframes
  didn't work; the meta-endpoint fix below is a separate perf improvement.

- **2026-06-21 — slider stuck on "no trajectory yet" / slow.** Root cause: the keyframe slider fetched
  the ENTIRE composite trajectory (oxDNA 14.6 s / 24 MB; MD reads+aligns the whole DCD) just to read
  `n_frames` + markers, and `_trajMeta` cached `null` permanently on any (slow/aborted) failure → stuck
  with no retry. **Fix:** lightweight `GET /oxdna|md/jobs/{id}/trajectory-meta` endpoints
  (`composite_trajectory_meta` / `md_composite_meta`) compute `{n_frames, markers, stages}` from frame
  COUNTS only (oxDNA `t = ` header lines; MD DCD header via `DCDReader`) — **205× faster** (0.064 s vs
  13 s), indices identical to the full composite (pinned by `test_composite_trajectory_meta_matches_full`
  + downsample + MD variants). `_trajMeta` now uses the meta endpoint and caches only successes (transient
  failures retry). Full frame DATA is still fetched only at play/bake. Live: meta endpoint 0.089 s / 375 B.

## Log

- **2026-06-21** — Plan locked; this tracker created. Phase 1 implementation started.
- **2026-06-21** — Phase 1 code complete. **Backend:** `AnimationKeyframe` gained `is_trajectory`
  (discriminator), `trajectory_job_id`, `trajectory_engine`, `trajectory_frame_start/end`
  ([models.py:1452](backend/core/models.py#L1452)); mirrored into Create/Patch bodies + `create_keyframe`
  passthrough ([routes_animations.py](backend/api/routes_animations.py)). **Frontend:** pure
  `scene/trajectory_range.js` (+9 vitest); `+ Add Trajectory` button (index.html) + purple trajectory
  row with job dropdown + dual-handle range slider + stage ticks in `animation_panel.js`; player gained
  `onFetchTrajectory` dep, `_bakedTrajectories`, a `_buildSchedule` tag, a `_bakeStates` fetch, an
  `_applyAt` trajectory branch (camera as normal, geometry from frame via `applyFemPositions`, early
  return), and `stop()` cleanup. **main.js:** +2 wiring lines (`onFetchTrajectory` on player,
  `getWorkspacePath` on panel) — ratchet held. **Tests:** backend `just test` 2922 passed / 55 skipped
  (+2 new); frontend trajectory vitest green; `vite build` OK; `just smoke` 23/23. Live trajectory
  gesture NOT hand-driven → `MV-TRAJ-KF` row added. Range slider = two stacked handles (single-track
  dual-handle polish deferred).
- **2026-06-21** — **Phase 1b + UX polish + Phase 3 confirmation.** Atomistic/surface now follow the
  trajectory (downsampled per-frame reconstruction, snap-to-nearest) — backend-validated on real job
  `6ad892196278` over HTTP. Added job timestamps, loading spinners, and heavy-rep "slower" notices so the
  user always sees computation happening. Confirmed photo-mode export already drives the same player path
  → trajectories render through it by construction. Backend `just test` 2924 passed; frontend 17 +
  smoke 23/23. **Phase 2 (NAMD) deferred** with a detailed handoff (async-WebSocket/DCD → needs a new
  `GET /md/jobs/{id}/trajectory` REST endpoint mirroring oxDNA's composite shape; validate with a real
  NAMD job).
- **2026-06-21** — **Phase 2 (NAMD CG) shipped.** New `md_trajectory.py` ports the live Display-MD nadoc
  extraction into a synchronous composite (`ws.py` untouched); `GET /md/jobs/{id}/trajectory` route;
  dropdown lists oxDNA + NAMD jobs; player threads engine. Validated on real 2hb DCD (frame-0 RMSD 0.154
  nm). Backend suite green (+2 guarded MD tests); smoke 23/23. NAMD heavy-rep → Phase 2b (deferred:
  MD-atom↔design-atomistic ordering). Live NAMD gesture folded into MV-TRAJ-KF.
- **2026-06-21** — **Phase 2b (NAMD atomistic + surface) shipped.** Chose render-MD-atoms-directly
  (Option B): ported the live ballstick extraction into `md_frames_atomistic`/`md_frames_surface` +
  routes; player swaps the MD atom set in via `update()` with a design-atoms restore guard
  (`_ensureDesignAtoms`/`onRestoreDesignAtomistic`); surface reuses the oxDNA path. Validated on real 2hb
  job (3513 heavy atoms, 10892-vert surface). Backend 2927 passed; smoke 23/23. **All trajectory-keyframe
  phases (1, 1b, 2, 2b, 3) now complete** — only live human-eye validation (MV-TRAJ-KF) remains.
- **2026-06-21** — **Job-list polish (oxDNA + MD panels + trajectory dropdown).** New shared
  `ui/job_status_symbol.js` (`statusKeyFor`/`statusBadge`/`makeStatusLegend` + 7 vitest) maps each status
  to a distinct shape+colour (▲ production-ready green, ■ production-done blue, ◆ completed, ⟳ running,
  ○ queued, ✕ failed, ◼ stopped, ⏸ paused). Both job lists now render **`[N]` index · name · timestamp ·
  status-symbol** (spinner while active; tooltip = label) with a legend under the list; the trajectory
  dropdown shows `[N] [oxDNA|MD] <symbol> name · time`. Pure tests 7; panel suites still green (92);
  `vite build` + `just smoke` 23/23. Live row/legend visual is cosmetic — human-eye (NOT app-verified
  beyond the console-error gate).
