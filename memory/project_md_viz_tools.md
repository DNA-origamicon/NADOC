---
name: md-viz-tools
description: MD jobs panel trajectory-scrub + flexibility-map (RMSF) tools — reuse the oxDNA display controller via an API adapter
metadata: 
  node_type: memory
  type: project
  originSessionId: 515d0592-f4a2-4e8a-8812-9d875d0bd184
---

The MD jobs panel got oxDNA-parity visualization tools (trajectory scrub + flexibility/RMSF map) to replace VMD for viewing NAMD runs. Built 2026-06-22.

**Architecture — reuse, don't reimplement.** `initOxdnaDisplay({api, ...})` is a factory that takes its data source as an injected `api` dep and calls it through oxDNA-named methods (getOxdnaTrajectory, getOxdnaRmsf, ...). The CG/nadoc-bead trajectory + RMSF payloads are byte-identical between oxDNA and MD (`md_trajectory.py` mirrors `oxdna_health`'s shapes). So a SECOND controller instance pointed at `mdVizApiAdapter(api)` (frontend/src/ui/md_viz_adapter.js — maps getOxdnaTrajectory→getMdTrajectory, getOxdnaRmsf→getMdRmsf) gives NAMD jobs the whole scrub/colour/recolor machinery with ZERO changes to the validated oxDNA controller. `mdViz` is created in main.js right after `oxdnaDisplay` (same renderer deps) and passed to initMdJobsPanel as `getMdViz`.

**Backend.** `md_rmsf()` in backend/core/md_trajectory.py pools ALL written segments (user chose "all segments" gating), Kabsch-aligns each sampled frame via the existing `_extract_md_nadoc_frame`, returns the oxDNA `/rmsf` shape. Route: `GET /md/jobs/{id}/rmsf` in routes_md.py. Trajectory endpoints (`/trajectory`, `/trajectory-meta`, `/frames-atomistic`, `/frames-surface`) already existed. RMSF default max_frames=150 (statistics fine; bounds per-frame Kabsch cost).

**P-ORDER MAPPING BUG — fixed 2026-07-02 (many-strand "map not ready").** `_build_md_nadoc_ctx` originally built the P-atom→(helix,bp,dir) order ONLY via `build_p_pdb_order`, which keys off the reference PDB's SINGLE-char chainID. CHARMM psfgen collapses NADOC's multi-char chain ids (`A`,`AA`,`AB`,…) into one letter, so for many-strand designs the keys collide → atoms DROPPED → `len(p_order) != ` universe DNA-P count → md_rmsf's strict guard `len(p_nm)!=n_keys` skips EVERY frame → `ready:false` with no reason → frontend fallback text "not ready" (oxdna_display.js:525). Real case: 3x6x200 (77 strands) mapped 6758 of 7229 P atoms. FIX: extracted `_select_p_order(u, cm, run_dir, coordinate_path)` — tries the segid map (`load_segid_chain_map`+`build_p_order_from_universe` from charge_audit.json) FIRST, falls back to PDB only when charge_audit absent/incomplete. This mirrors what ws.py's live-display NAMD branch already did (which is why live Display-MD worked but the flex map/trajectory didn't). md_rmsf now returns a real `reason` on total-drop (design/topology atom mismatch). Also: `_md_traj_inputs` + the trajectory route now analyse the job's FROZEN `design.json` snapshot (`_md_snapshot_design`, active-design fallback for legacy jobs) — like the oxDNA route — not the live active design. Regression: `tests/test_md_p_order_mapping.py` (fast, always-on, fakes the collision); heavy real 3x6x200 e2e in test_md_trajectory.py is env-gated `NADOC_RUN_HEAVY_MD_FIXTURE=1` (~20min: 3600-nt model build + 1M-atom unwrap).

**Panel (md_jobs_panel.js).** flex + traj toggles/controls mirror oxdna_jobs_panel; reuse `oxdna_trajectory_player.js`. Three display modes (live "Display MD" / flexibility map / trajectory) are MUTUALLY EXCLUSIVE — each deforms the same design model, so activating one calls stopAndRestore on the others. Rows now have `data-job-id` (for the e2e + the existing md_live_no_stale spec).

**v1 scope = CG/nadoc representation only.** Deliberate follow-ons: (1) heavy-rep (atomistic/surface) RMSF colouring — the per-frame atomistic data shapes differ between oxDNA (template) and NAMD (real DCD atoms), needs its own mapping, so the adapter intentionally omits the heavy methods (controller heavy path is a no-op for CG, fails closed for atomistic/surface scenes); ~~(2) the draggable colour-rescale widget~~ **DONE 2026-07-10** — see below.

**SHARED ADJUSTABLE LEGEND + COLORMAP PICKER (2026-07-10).** `flex_scale.js` is now the ONE adjustable
workspace legend for EVERY scalar sim map — oxDNA/MD flexibility (RMSF) + deviation maps and CanDo
RMSF/deviation/cylinder heat maps. Architecture: a single `flexScale = initFlexScale()` is created in
`main.js` and injected into every engine panel/controller; each drives it per-activation via
`flexScale.show({ title, min, max, mapType, onRecolor })` where `onRecolor(lo,hi,cmap)` is that map's live
recolour. The MD flex map reaches it because `mdViz` is the same `initOxdnaDisplay` controller (its
`recolorRmsf(lo,hi,cmap)` now takes a colormap) — `md_jobs_panel` gets `getFlexScale`. New shared colormap
registry `frontend/src/ui/colormaps.js` (10 ramps: viridis/magma/plasma/inferno/cividis/turbo/jet/coolwarm/
Green→Red/Grayscale) is the single source of truth — `oxdna_display`/`cando_display`/`cando_cylinders` all
delegate their ramps to it (killed the duplicate viridis/dev/jet LUTs). The picker is a small swatch button
in `#flex-scale` → popup of 10 gradient swatches; the choice is remembered **per map-type** in localStorage
(flex→viridis, deviation→Green→Red, cando→jet defaults) so each map keeps its "respective colours" unless
overridden. The old static `#cando-legend` + `cando_legend.js` were retired (deleted). Engines wired: oxDNA
(flex+deviation), MD (flex), CanDo (flex+deviation+cylinders), LAMMPS (flex+deviation). Known minor debt: the
in-panel static viridis mini-strips (`_setFlexLegend` in oxdna/md panels) still draw viridis regardless of the
picked colormap — candidate to remove or sync.

**MD ALL-ATOM VIEWS WERE COLOUR-BLIND — fixed 2026-07-28.** In a ball-and-stick / VDW scene the
"Display MD" toggle rendered every atom CPK and ignored the colouring buttons. Cause: the MD
all-atom payload is the SIMULATION's own atoms (`{serial, element, x, y, z}`) — unlike the design's
atomistic model, whose atoms carry `strand_id`/`helix_id`/`bp_index`/`direction`, which is what
`scene/atomistic_renderer/color_resolver.js` keys on. `strandColors.get(undefined)` missed for every
atom → CPK, and no colouring mode could reach it. The CG/`nadoc` path was never affected (it only
moves the design renderer's own beads, which keep their colours). New shared
`atomistic_to_nadoc.build_atom_design_meta(u, heavy_ag, p_order, model, chain_map, seg2chain)`
recovers identity per RESIDUE: residue's P atom → `p_order` key → the design model's own P atoms
(`md_pkey` → `strand_id`), so synthetic keys (`__xb__` extra bases, `__ext_` tails, loop copies)
resolve too; 5'-terminal residues (no P — pdb2gmx strips it) come back through `chain_map`, the same
route `build_termini_specs` uses for their positions. Wire: the identity is STATIC across frames and
a frame is ~10⁵ atoms, so the live WS sends it ONCE in `ready` as `atom_ident` — interned parallel
arrays (`intern_atom_design_meta`, mirroring the columnar bundle's intern tables) — and
`md_display_state.zipAtomIdentity` stamps it onto each frame's atoms in place. The batch trajectory /
surface path (`md_trajectory._extract_md_atoms_frame`, `_SurfAtom`) inlines the same fields per atom
instead (no streaming pressure there). md_panel also calls `refreshAtomColors()` once per load: MD
calls `atomisticRenderer.setMode()` itself, bypassing the representation switcher that normally
primes the mode + palette. Fails soft — an unmappable topology yields `atom_ident: null` and the old
CPK render, never a failed display. Pins: `tests/test_md_atom_design_meta.py` (5 fast),
`md_display_state.test.js` → `zipAtomIdentity` (4).

Follow-on the same day: **CPK now applies to crossover extra bases too** (ALL atomistic views,
not just MD). `color_resolver.js` had `if (colorMode === 'strand' || atom.aux_helix_id)` — the
`aux_helix_id` disjunct pinned extra-base atoms to their strand colour in EVERY mode, so they were
the one thing on screen that ignored the colouring buttons. Split into `_colorByMode`: CPK is
per-ELEMENT and needs no design key, so extra bases follow it like any other atom; 'base' still
falls back to strand colour for them because their stored key is the SOURCE nucleotide's and a
letter lookup would paint them with a neighbour's base. **Extension tails were never affected** —
they carry no `aux_helix_id` (verified against the pre-change resolver), though they do inherit
their ANCHOR nucleotide's `(helix, bp, dir)`, so 'base' mode shows them the anchor's letter. Fixing
that would mean changing extension atom identity in `atomistic.py` — not done, deliberately.
Pins: `color_resolver.test.js` (+5, CPK case proven to fail against the pre-change resolver).

**PERFORMANCE — per-frame extraction fixed 2026-07-02.** The old bottleneck was NOT the select/Kabsch (measured <0.03s/frame) — it was the whole-system `mda_unwrap` PBC make-whole transformation added in `_build_md_nadoc_ctx`: it make-wholes ALL ~1M solvated atoms on EVERY frame seek → **~180 s/frame** for the 3x6x200 (RMSF max_frames=2 took 24 min). FIX: removed the transformation entirely. Both per-frame extractors already reconstruct DNA from RAW wrapped coords — the bead path via the vectorised `_unwrap_min_image` + design-eq min-image correction, the heavy path via residue-local `minimum_image(atom−its P)`. The only thing the global unwrap affected was the P→C1' base-normal for a nucleotide split across PBC, now handled by a direct min-image on that 7229-vector. Verified numerically identical to the unwrapped reference to ~1.5e-8 nm (float32 noise) on real 3x6x200 frames. Result: **186 s → 0.01 s per frame** (~15000×); full 3x6x200 ctx build ~13s; a 150-frame flex map goes from hours to ~20s. Equivalence pin: `test_md_extraction_matches_unwrap_reference` (env-gated NADOC_RUN_HEAVY_MD_FIXTURE=1, reference side pays the slow unwrap). ws.py's live-display path still adds its own unwrap for interactive single-frame seeks — untouched, and the fast path's output matches it. Remaining v1 gaps unchanged: cache built ctx across requests; the "Loading…/Computing…" overlays still show.

**PERFORMANCE — oxDNA View-trajectory LOAD fixed 2026-07-10 (downsample-FIRST).** Distinct from the NAMD per-frame fix above: the *initial* "View trajectory" load for oxDNA runs was slow because `oxdna_health._aligned_downsampled_frames` read the ENTIRE `.dat` and PBC-unwrap+Kabsch-aligned EVERY frame, THEN `_stride_pick`ed down to ≤200 — a 5000-frame run aligned 5000 frames to keep 200 (~25× wasted). FIX: reordered to downsample first. `count_trajectory_frames` (cheap header scan) gives per-stage counts → compute the per-stage stride → new `oxdna_interface.read_trajectory_frames_at(path, design, indices, copies=)` (streams the file, parses ONLY the wanted header indices, returns `{header_idx: map}`) → align only those. Output is byte-identical (same stride math, seed still prepended at eff-position 0 of the first non-empty stage as a stride candidate; malformed/half-written frames drop out as before). `read_trajectory_frames_full` is UNCHANGED (default callers untouched); only the composite builder switched to the selective reader. **NAMD's `md_composite_trajectory` was already downsample-first** — this only closed the oxDNA gap.

**PERFORMANCE round 2 — vectorized the per-frame hot path 2026-07-10.** Downsample-first alone only helped the many-frames case; the real production trajectories here are FEW frames of a HUGE structure (e.g. 4 stages × 100 frames × 14774 nt, 1.5 GB) where all ~200 kept frames are parsed+aligned+flattened. Benchmarked (`workspace/oxdna_jobs/{e570176e6a02=2610nt, 7c0ffd3177c7=14774nt}`, cold `_ALIGNED_CACHE`): **2610 nt 27.5 s → 4.8 s; 14774 nt 179 s → 31 s (5.7×)**. Four output-preserving vectorizations, each golden-verified byte-identical (max abs diff ≤ 7e-15 vs the pre-change composite output on real frames):
1. **`_flatten_cg_frame`** — was one `np.cross` per nucleotide (522k calls, the single biggest cost); now gathers cm/a1/a3 into (N,3) and calls new `oxdna_interface.oxdna_backbone_sites` (batched cross) once per frame.
2. **`_parse_trajectory_frame_lines`** — new FAST PATH: `np.fromstring(" ".join(rows), sep=" ").reshape(N, ncol)` (one C parse per frame) + vectorized a1/a3 normalize; falls back to the tolerant per-row loop on a ragged/half-written frame. `_parse_box_nm` now reads only the file HEAD (8 lines via islice), not a full 406 MB slurp for line 2.
3. **Vectorized unwrap** — new `_build_unwrap_plan(relax, design)` replays the EXACT DFS once (seed order, LIFO, adj order) → `{order, parent, comp}`, cached per key set; new `_apply_unwrap_plan` does the min-image via the telescoped recurrence `K[v]=K[parent]−round((raw[v]−raw[parent])/box)` (vectorized local term + a cheap tree prefix-sum, skipped entirely when nothing wraps) + segment-sum component box-shift. `unwrap_align_to_reference` gained `plan=` (only the composite passes it; all other callers keep the byte-unchanged BFS path). The Kabsch APPLICATION also vectorized: 3 batched matmuls (`v@R.T`) instead of one `R@v` per nucleotide.
4. Adjacency/plan built ONCE per key set, not per frame (was rebuilt ~200×).

**PERFORMANCE round 3 — sibling frame reuse (common-parent recycling) 2026-07-11.** Switching to a job that shares a parent with the previously-viewed one re-did the WHOLE lineage (the whole-composite `_ALIGNED_CACHE` misses on a different stages tuple), even though siblings share every ancestor stage (root relaxation + shared production runs). New **per-FRAME aligned cache** `_FRAME_CACHE` in `oxdna_health` keyed by `(traj-file sig, reference CONTENT hash, copies, raw frame index)` → a sibling reuses the shared ancestor frames and re-parses/re-aligns ONLY its own leaf run. Keyed by reference *content* (`_ref_content_sig`, blake2b of the small `design_ref.dat`) because sibling jobs write byte-identical refs at different PATHS — a path key would never hit. Correct unconditionally (aligning frame *j* of a file to a given reference is deterministic, independent of the lineage/stride); reuse is best when the siblings have the same structure (identical stride → identical `needed` indices) and partial otherwise (per-frame, not per-stage). Bounded by cumulative nucleotide-frames (`_FRAME_CACHE_MAX_NT=3M`, memory-proportional; a growing file's sig changes → its frames re-align, stays live-correct). Also added a **frame-COUNT cache** (`_COUNT_CACHE` in `count_trajectory_frames`, keyed by file sig) so the per-load header-count of every ancestor file (needed to size the stride) doesn't re-stream hundreds of MB each time. Object-shared with `_ALIGNED_CACHE`/`ordered_frames` (consumers are read-only — the existing whole-composite cache already relies on that). Benchmarked on real siblings `979202023882`↔`2cd4a4211f2b` (both children of `734d7dd0491d`, GT_corner_v2 ~14 k nt): cold first view **30 s → sibling 9.2 s (3.3×) → re-view 4.3 s** (residual floor = the still-uncached flatten of all 200 frames; caching flat CG per frame is a possible round 4). Golden byte-identical (7e-15). Pin: `test_composite_trajectory_reuses_sibling_ancestor_frames` (spies `read_trajectory_frames_at`: sibling parses fewer frames, root NOT re-parsed, own leaf IS).

**SPARSE vs FULL trajectory + user-set frame density — 2026-07-21.** Two decimations existed and only
the second was recoverable. (1) WRITE side: `oxdna_protocol.print_conf_interval` was `steps//100`, i.e.
~100 frames per stage *regardless of run length* — a longer run got a COARSER trajectory, and what wasn't
written was gone. (2) READ side: the composite route strided the whole lineage down to a hardcoded 200.
Both are now user-visible/controllable:

- **`steps_per_frame`** (`RunRequest`, default `oxdna_protocol.DEFAULT_STEPS_PER_FRAME = 10_000`, from
  oxDNA's own `examples/NEW_RELAX_PROCEDURE/input_relax`). ABSOLUTE, not a fraction of `steps`, so a longer
  run yields a longer trajectory instead of a coarser one — and disk scales with run length, hence the hint
  line. Lands in the existing `OxdnaStageSpec.print_conf_interval_override` via `build_run_stage/
  build_production_stage(steps_per_frame=)`. **`print_conf_interval(spec)` now honours that override** — it
  didn't before, so the disk forecast + progress ETA would have described frames oxDNA wasn't writing.
  UI: `#oxdna-jobs-prod-steps-per-frame` in the Advanced card + `#oxdna-jobs-prod-frames-hint`
  ("→ 500 frames · ~1.1 GB trajectory", amber over 5 GB), from pure `trajectoryFrameEstimate` +
  `formatBytes` in oxdna_jobs_panel.js (130 B/nt/frame — MUST track `disk_guard._OXDNA_CONF_BYTES_PER_NT`).
- **`scope` query param** on `/trajectory`, `/trajectory-meta`, `/frames-atomistic`, `/frames-surface`.
  `lineage` (default) = old behaviour, whole ancestor chain strided to `routes_oxdna._SPARSE_FRAME_CAP=200`.
  `job` = THIS job's stages only, `max_frames=0` → **stride disabled** (`_keep_for` and
  `composite_trajectory_meta` both treat `max_frames <= 0` as unlimited). Radios: "View sparse trajectory
  (fast)" / "View full trajectory (slow)" — peers in the `oxdna-viz` group, one shared `_onTrajToggle`
  handler; switching between them needs an explicit `stopAndRestore` because BOTH are mode `'trajectory'`
  so the peer teardowns don't fire. Measured on real jobs: `0bb9742bae7e` (7-stage lineage) 29 own-frames
  sparse → 101 full. **`_trajScope` in oxdna_display must be repeated on every heavy per-frame fetch** —
  a frame index only means the same thing within one scope. **`_EXPORT_FRAME_CAP=240` is the real ceiling
  for exporting a full-scope trajectory** (it used to be slack because the composite was always ≤200).

**LOADING BAR (accurate frames-processed).** `composite_trajectory(..., progress=cb)` → `_aligned_downsampled_frames` calls `cb(done, total_kept)` per aligned frame (total = the downsampled budget, snaps to 100% at end). Route `GET /oxdna/jobs/{id}/trajectory` writes an in-memory `routes_oxdna._TRAJ_PROGRESS[job_id]={done,total}` via the callback (build runs in `run_in_threadpool` so the poll is served concurrently on the single worker), cleared in `finally`. New `GET /oxdna/jobs/{id}/trajectory-progress` → `{active,done,total}`. Frontend `oxdna_jobs_panel._refreshTraj` polls it every 250 ms while `_trajBusy` and renders `Loading trajectory… NN% (done/total frames)` into the existing `#oxdna-jobs-traj-status` line (no new DOM/CSS — a graphical bar is a follow-up; **NOT exercised in-app**, doc-context per-design-selection limit). `client.getOxdnaTrajectoryProgress`. **NAMD path (`md_composite_trajectory`) has NO progress callback yet** — mirror there if the NAMD trajectory load is reported slow.

Pins (tests/test_oxdna_relaxation.py): `test_read_trajectory_frames_at_matches_full_reader` (selective==full), `_empty_request`, `_composite_trajectory_downsamples_across_stages` (9+8, budget 10→5+5+one marker), `_keeps_all_when_under_budget`, `test_oxdna_backbone_sites_batched_matches_scalar`, `test_unwrap_plan_matches_bfs` (vectorized==BFS on a rotated+translated+wrapped structure — the equivalence pin), `test_composite_trajectory_reports_progress` (0→100% monotonic), `test_oxdna_trajectory_progress_endpoint_idle`. `_ALIGNED_CACHE` still memoizes the 2nd load; a still-growing trajectory re-strides each poll (bounded now). Remaining floor for the 14774-nt/1.5 GB extreme (~31 s): text parse (~6 s) + file streaming + array (re)builds — would need frame byte-offset indexing / threading arrays instead of dicts to push further.

**LOOP-INSERTION BASES NOW MOVE IN THE NAMD/MD PATH (2026-07-12).** Reported on `6hbx100_90deg`
(16 loop `+1` + 16 skip `−1` marks realising a 90° bend): loop bases stayed at their geometric start
after a NAMD relaxation in Display-MD + flex maps. Root cause = a **key collision**, not iteration:
a `+1` loop emits a SECOND nucleotide sharing `(helix_id, bp_index, direction)` with its base, and
the NAMD readback keyed by that bare 3-tuple (`md_pkey`) → the two collapsed. Crossover extra-bases
had a disambiguator (`crossover_id`→`__xb__`); loop copies never did, and the **oxDNA path already
carried a `copy` key** but the MD path was never brought to parity. Fix mirrors oxDNA: new
`Atom.copy_k` (set at loop-copy emission in `atomistic.py`) → `md_pkey` emits a 4-tuple
`(helix,bp,dir,copy)` for `copy≥1` (copy 0 stays a 3-tuple = byte-identical for every existing
consumer) → propagated through `build_chain_map`/`p_order`/`md_rigid_reference` (its dedup dict no
longer collapses the copies, so each gets its OWN Kabsch eq position) and the `md_rmsf` + `ws.py`
live-MD payloads now carry a `copy` field. Frontend: `applyFemPositions`/`rmsfColorMap`/`framesToUpdates`
were ALREADY copy-aware (`_copyKeyToEntry` in `helix_renderer.js`), so the flex map is fixed
backend-only; `md_panel.js`'s live-frame map gained `copy: p.copy ?? 0`. Verified on the real design:
1244 P atoms → 1244 distinct keys (was 1212 — 32 loop bases colliding). Tests:
`tests/test_md_loop_base_coverage.py` (6, in-memory: distinct keys, distinct eq positions, every base
moves after a fake relax, `md_rmsf` payload carries `copy`) + a loop-copy case in
`frontend/src/ui/oxdna_display.test.js` `rmsfColorMap`. Other 3-tuple `p_order` consumers hardened to
slice `key[:3]` (`_map_positions`, `_extract_universe`, `extract_from_pdb`, parameterization
`bundle_extract`/`local_crossover_extract`). `openmm_checker` builds its own 3-tuple map (unaffected;
its own loop collapse is pre-existing + out of the display path). **REAL end-to-end verified**: wrote a
PDB+PSF+DCD from the 90deg design (MDAnalysis DCD, frame 1 = a per-atom relax) and ran the actual
`md_rmsf` → `ready`, 1244 positions all carrying `copy`, 32 loop-copy entries, each loop key's base+copy
at DISTINCT positions (was 1212 distinct = 32 colliding). The specific `fc6a91577151` NAMD job dir was
cleaned up before this session, so the synthesized-but-real DCD stands in for the live job.

**"DISPLAY DOESN'T WRAP" STREAKS = A DESIGN MISMATCH, fixed by design-aware live Display (2026-07-16).**
Reported on a current 24hb_2xT k=0 production run: live Display (nadoc/beads) drew long straight lines
shooting across the whole box. **Root cause is NOT PBC** (initially mis-hypothesized — see the pose-first
note below). Confirmed on REAL production frames: with the run's OWN design loaded the reconstruction is
already perfect (`build_p_order_from_universe` n_unmapped=**0**/7320, 6524 intra-helix bp adjacencies, 0
gaps >2 nm). The streaks come from the live `ws.py` `_load_sync` building its P-atom→(helix,bp) map from
**`store.currentDesign`** — whatever design is open in the editor — NOT the run's design. With a different
design open, the segid map (design-independent) can't resolve the atoms against that design's chain map
(measured: 10hb open → **7089/7320 unmapped**) → falls back to the collision-prone single-char-chainID PDB
path → beads land in the WRONG slots → cross-structure streaks. (The trajectory/flex-map paths were already
fixed to use the frozen snapshot in 2026-07-02; the LIVE path was missed.) FIX:
- Frontend sends `job_id` in the WS `load` message (`md_panel.js` `displayLatest`/`prewarmLatest` gained a
  `jobId` opt; `md_jobs_panel` passes `job.job_id`).
- Backend `ws.py` load handler resolves the RUN's own design via new `routes_md.md_display_design_for_job(job_id)`
  → `_md_run_design(job)` = frozen `design.json` snapshot (walks parent chain) ELSE the recorded
  `design_source_path` `.nadoc` — **no active-session fallback** (that fallback IS the bug). The open-design
  payload is now only a last resort when job resolution fails.
- **Mismatch guard** in `_load_sync`: when the segid map is present and >25 % of DNA-P atoms are unmapped,
  it RAISES a clear error ("This trajectory doesn't match the design being displayed … built from
  '<name>'. Load that design …") → the WS sends it as an `error` frame (spinner clears) instead of drawing
  garbage. A correct design gives 0 unmapped; a wrong one ~97 % → the 25 % threshold cleanly separates.
- **Validated end-to-end on the real run** (7935f0749701): `md_display_design_for_job` → design + name
  '24hb_2xT'; correct design → 0 unmapped (guard silent, clean display); wrong design (10hb) → 7089 unmapped
  → guard fires. Tests: `test_md_draft.py` (4 — source-path resolution, None-when-unresolvable, id→(design,name),
  unknown id). **NOT click-verified in the browser** (the job_id-threaded WS load is logic-reviewed).

**POSE-FIRST PBC REASSEMBLY — separate latent-bug hardening, NOT the streak fix (2026-07-16).** While
chasing the streaks I first (wrongly) blamed PBC: for a 1.3 M-atom system the whole-system make-whole is
skipped (`_UNWRAP_MAX_ATOMS`), and `_seek_sync` Step 2 placed the design reference by TRANSLATION ONLY then
nearest-image-snapped — which WOULD stream once an origami larger than half the box rotates (24hb_2xT DNA
137×133×**517 Å** in a 157×153×528 Å box; long axis 517 vs half-box 264). But real production frames showed
the OLD code already reassembles correctly there (the structure hadn't drifted past half-box in ~2 ns), so
this was not the cause. Kept anyway as regression-safe hardening for a LONG unrestrained production that
eventually tumbles past that thin ~12 Å-shell half-box. FIX = pose-first: new pure
`atomistic_to_nadoc.reassemble_to_posed_reference` (+ `_pbc_circular_centroid`, `_nearest_image_to`,
`_kabsch_rotation`) estimates the rigid-body pose (PBC-robust circular centroid → image rigid atoms to it →
seed Kabsch → one inlier refinement dropping atoms >¼·min(box) off) and poses the design reference
(rotation+translation) into the box frame BEFORE snapping, so even end atoms image correctly. `_seek_sync`
Step 2 now calls it (free ssDNA keeps its sequential-unwrap position; downstream dynamic-T + display Kabsch
unchanged). **Strict generalization** — un-rotated/un-split ⇒ R≈I, circular≈plain centroid ⇒ byte-identical
to the old snap (pinned). Tests: `test_atomistic_to_nadoc.py::{TestPbcCircularCentroid,TestNearestImageAndKabsch,
TestReassembleToPosedReference}` (7). e2e `test_md_run_ws_dcd_alignment_matches_design_eq` green. See
[[md-live-model-cache]].

**Verification gotchas (cost real time).** The dev backend uses uvicorn `--reload`; editing backend files under load WEDGES it on WSL2 (the smoke config runs WITHOUT --reload for this reason). The single-worker dev backend SERIALIZES requests, so concurrent heavy trajectory/RMSF reads + a Playwright run starve each other. Headless Playwright boot can CLEAR the active design (the trajectory/RMSF routes need it via get_or_404 → 404 "no trajectory yet" is really "no design"). The stable e2e (e2e/md_viz_tools.spec.js) asserts the toggle FIRES the right endpoint (page.waitForRequest) rather than waiting for the multi-minute compute — proves DOM→handler→mdViz→adapter→endpoint without the flaky slow path. See also [[md-job-system]] and [[md-panel-implementation-status-and-algorithm-details]].


## "Align to design pose" now governs EVERY visualization (2026-07-16, out-of-session work)

The Align checkbox moved out from under the oxDNA-display radio to the top of the Visualizations card
and now applies to **trajectory, flexibility (RMSF) and deviation** too, not just the relaxed display.
Flipping it live re-fetches whichever viz is active; the PDB export honours it
(`align: active[0].alignment?.() ?? true`). Both display controllers expose `alignment: () => _align`.

**HAZARD — RESOLVED 2026-07-16. It had already bitten.** `align` was inserted BEFORE `signal`
(`getOxdnaTrajectory(id, align = true, signal)`, ditto `getOxdnaRmsf`/`getOxdnaDeviation`/`getOxdnaDisplay`/
the four `getLammps*`). `md_viz_adapter` was still on the older `(id, signal)` shape, so the controller's
`align` bound to its `signal` param: the **real AbortSignal was dropped** and `api.getMdTrajectory(id, true)`
made `fetch` reject with `TypeError: Expected signal ("true") to be an instance of AbortSignal`. **NAMD
trajectory scrub + flexibility map were dead in the app with a fully green suite** — every adapter test
called the adapter directly on the old 2-arg contract, so nothing noticed. See [[LESSONS]] D14.

**The fix — three layers, so it cannot be silent again:**
1. **Options object.** All ten viz fetchers are now `(id, { align, signal })`
   (`getOxdnaRmsfSurface` is `(id, params, { align })`). There is no positional boolean to mis-bind.
2. **Tripwire.** `_vizOpts(opts, fn)` in `client.js` THROWS on a positional boolean or AbortSignal, on a
   non-boolean `align`, and on a non-AbortSignal `signal` — naming the function.
3. **Choke point.** `_oxdnaJSON` now type-checks `signal` (was `if (signal)`, which waved `true` straight
   through to fetch) and throws naming the route. This backstops the ~15 fetchers still on the
   unambiguous `(id, signal)` shape (`getMd*`, `getCando*`, `getSnupi*`, `getMrdna*`).

`mdVizApiAdapter` takes `(id, { signal } = {})` and deliberately does NOT forward `align`: `/md/jobs/{id}/
trajectory` and `/rmsf` have no align param (md_trajectory.py always Kabsch-aligns). If MD ever needs
align=false it must be honoured server-side, not silently ignored in the adapter.

**Caches are keyed on align** (frontend `_rmsfCache = {jobId, align, resp}`; backend
`_PRODUCTION_RMSF_CACHE`, `_ALIGNED_CACHE`, per-frame `_frame_cache`) — without this, toggling served
stale cross-mode frames.

**`align=False` does NOT change deviation NUMBERS.** In `geometry_deviation_map`, `dev` is always
computed after Kabsch; `align_output=False` only changes the EMITTED `backbone_position` (raw
`cur_pos`) and leaves `a1`/`nx,ny,nz` unrotated. Unaligned coords still carry alignment-based
magnitudes — do not read it as "deviation in the raw frame".

Backend: every oxDNA/LAMMPS trajectory/rmsf/deviation route + `frames-atomistic|surface`,
`rmsf-atomistic|surface` gained `align: bool = True` (back-compatible). `PdbVisualizationSource` gained
`align`. **Bug fixed:** `GET /lammps/jobs/{id}/display` already accepted `align` but never forwarded it
to `composite_trajectory` — it was silently ignored. NB `composite_trajectory` is called POSITIONALLY
in `routes_oxdna.py` (`…, ref, 200, _prog, align`).

Also: `design_renderer.js` sim-frame path now calls `refreshAllGlow()` — "simulation frames mutate the
existing backbone entry positions rather than replacing currentGeometry", so the store subscriber
cannot observe playback/scrub mutations and position-backed overlays must be refreshed per frame.

**STRAIN MAP — new oxDNA scalar viz, 2026-07-27.** A fourth false-colouring mode alongside
relaxed / flexibility (RMSF) / deviation: `GET /oxdna/jobs/{id}/strain?metric=backbone|wc&align=`.
Radio `#oxdna-jobs-strain-toggle` + metric `<select>` `#oxdna-jobs-strain-metric` in the
Visualizations card; controller methods `displayStrain(resp)` / `recolorStrain(lo,hi,cmap)`,
`_mode === 'strain'`.

- **What it measures.** SIGNED, DIMENSIONLESS engineering strain `(L − L0)/L0`, per nucleotide.
  `backbone` → FENE backbone-bond stretch (`L0 = FENE_R0_OXDNA2`), each bond attributed to BOTH
  endpoints by largest MAGNITUDE (a junction reports its worst bond, not an average that hides it).
  `wc` → Watson–Crick base-site separation (`L0 = HYDR_R0_OXDNA2 = 0.4` units, new constant); pairs
  with no designed partner (ssDNA loops, overhangs, ragged ends) are OMITTED, not coloured 0.
  Deviation asks "is this base where the design put it"; strain asks "is its own local geometry
  under load" — independent signals, and a rigid-but-misplaced region shows only in deviation.

- **NEVER strain the mean structure — average the FIELD (the load-bearing bug this shipped with,
  caught in-app).** The obvious build (reuse `production_rmsf_cached(...)["average_frame"]` for the
  values, like the deviation map does) is WRONG: averaging positions collapses bond lengths
  (|⟨r_a⟩−⟨r_b⟩| ≤ ⟨|r_a−r_b|⟩). Measured on `workspace/oxdna_jobs/6b775c8acff4` (1hb_efield_test):
  mean-structure read **−26 % mean backbone / −67 % mean WC**, where any single frame reads
  **−1.8 % / +0.9 %**. It looks like a totally melted structure. So `production_strain_field(_cached)`
  does its OWN bounded trajectory walk (`_STRAIN_MAX_FRAMES = 60`, evenly sampled via `_even_indices`,
  budget split across pooled runs in proportion to length), computes `strain_field` per frame and
  averages that. `full_map`/`average_frame` supplies ONLY the display positions, so the beads still
  sit exactly where the RMSF/deviation overlays put them. Frames are PBC-unwrapped
  (`unwrap_align_to_reference(..., align=False)`) but NOT rotated — strain is rotation-invariant, so
  the Kabsch step is skipped. Pin: `test_mean_strain_over_frames_is_not_the_strain_of_the_mean_structure`.

- **Signed + diverging + a robust auto-range.** Default colormap `coolwarm`
  (`DEFAULT_COLORMAP_FOR.strain`); default bounds are SYMMETRIC ±half-width (`strainBounds()` in
  oxdna_display.js) so the ramp midpoint is exactly 0 = relaxed (blue compressed / white relaxed /
  red stretched). The half-width is the backend's `display_abs_strain`, NOT the max — and its
  percentile is PER-METRIC (`_STRAIN_DISPLAY_PERCENTILE = {backbone: 98, wc: 90}`) because the tails
  differ physically: a FENE bond cannot exceed ~+33 % (measured p50 4 % / p98 7 % / max 8 %) while a
  melted WC pair is unbounded (same bundle: p90 8 %, p95 81 %, p98 233 %, max 469 %). Ranging WC on
  p98 flattened the whole intact duplex onto the midpoint colour. Outliers still saturate the ramp's
  end (colormapHex clamps); the status line says "(outliers clipped)" and quotes both the colour
  scale and the true data range, since they disagree by design.

- **5′/3′ EXTENSION TAILS + CROSSOVER EXTRA BASES ARE INCLUDED** (backbone metric). The
  reference in `production_strain_field` is read with `include_extra_bases=True,
  include_extensions=True`, so `__ext_<id>` tail beads and `__xb__` inserts are measured
  like any other nucleotide — on VoltronCoreScad that is 334 ext + 1132 xb on top of 14702
  real (16168 total). This is the point of the map: per
  [strand_extensions_sim](project_strand_extensions_sim.md) a tail has THREE distinct
  blow-up modes and a too-SHORT bond kills a run as dead as a too-long one, so a strain map
  that dropped tails would omit exactly what it exists to find. Three consequences:
  - They are kept OUT of the Kabsch fit (`align_keys` = non-synthetic keys). Unpaired ssDNA
    flails; letting it bias the superposition is the same trap `atomistic_to_nadoc` masks
    against, and it would also land the mean frame in a different pose than the
    RMSF/deviation overlays.
  - They are kept OUT of the `wc` metric (`_strain_index` filters `is_synthetic_nuc_key`).
    A tail key is a 3-tuple carrying a direction string, so it is otherwise *eligible* to
    pair with anything sharing its synthetic helix id — the exact trap the topic file warns
    about. Pin: `test_wc_strain_never_pairs_synthetic_particles`.
  - `strain_map` emits `bp_index` RAW (as `/display` does). An `__xb__` key's bp_index slot
    holds a crossover id, which may be a STRING — an early version called `int()` on it.
  Display positions for them come from `production_strain_field`'s own mean frame, merged
  under `production_rmsf_cached`'s `average_frame` (which drops synthetic keys); real
  nucleotides still take the RMSF frame so all three overlays coincide exactly.
  **Where each kind actually draws** (verified against the real design, don't re-derive it):
  tail beads are ordinary `_geometry_for_design` nucleotides — all 334 of VoltronCoreScad's
  address a drawn bead under `__ext_<id>:i:DIR:0`, so `helix_renderer.applyScalarColors`
  colours them with no special casing. Extra bases are NOT in that geometry; they are
  crossover-ARC beads recoloured separately at `design_renderer.js:210` via
  `colorByKey["__xb__:<xoId>:<k>"]` — the 3-part alias `strainColorMap` already emits for
  copy 0. A probe that only checks `_geometry_for_design` will report extra bases as
  "0 % drawn" and be wrong.

- **TORN-UNWRAP FRAME GATE — the second load-bearing bug, and it was silent.**
  `unwrap_align_to_reference` box-shifts each bonded component toward its reference image;
  once the assembly has diffused far from the design reference (late frames of long/RESUMED
  runs — `trajectory.r1.dat`, `trajectory.r2.dat`) neighbouring components snap to DIFFERENT
  periodic images and are torn apart, leaving bonds of order the box size. Measured on
  `fb83ff00287a`: violation fraction 0.0000 for every frame of the first run, then
  0.0015 → 0.3861 through the resumes; the raw backbone map read **+4669 % max, 38 % of
  nucleotides FENE-impossible**. Two guards, both physics-derived, no tuned magic numbers:
  1. `_fene_violation_fraction` + `_STRAIN_FRAME_REJECT_FRAC` (0.001) — a production frame
     cannot hold a bond outside `r0 ± delta` (oxDNA aborts at config load), so any is proof
     the frame's *reconstruction* failed. Reject the frame WHOLE, for BOTH metrics. This
     matters most for `wc`, which has no bound of its own: a torn frame there is
     indistinguishable from real melting. Before/after on the same job, WC p50 **14 % → 1.8 %**
     — and the job's own `bp_retained_fraction` is 0.9885, i.e. barely melted, which is what
     told us 14 % had to be wrong.
  2. Per-bond FENE-window rejection inside accepted frames for the stragglers.
  Both surfaced (`rejected_fraction`, `n_rejected`, `n_frames_torn`) and shown in the status
  line — a map built from a poorly reconstructed trajectory must not look as solid as a clean
  one. **This tearing is pre-existing and shared with the RMSF/deviation maps**, which just
  don't expose it (averaging positions hides what bond lengths cannot).

- **The WC display bound scales on the BONDED population only.** A WC field is intrinsically
  bimodal — every real origami frays at its ends — so ranging over both modes puts the whole
  intact duplex on the midpoint colour. `_display_strain_bound` cuts at `WC_UNPAIRED_STRAIN`
  (= `BP_FORMED_CUTOFF_NM` re-expressed in WC-strain units, +134.8 %; derived, not tuned) and
  takes p90 of what is left. Result: VoltronCoreScad ±22 %, corner_miter ±3.4 % — each scaled
  to its own intact duplex, with frayed/melted bases saturating the ramp end.

- **Copies.** `backbone_bond_pairs` collapses loop copies to the 3-tuple key, so the physics is
  indexed by the 3-tuple (copy 0 wins) and broadcast back to every 4-tuple copy — every loop bead
  still colours.

- **Perf — 16 m 26 s → 16.8 s (59x) on VoltronCoreScad** (15 k nt, 3.6 GB trajectory, 805 frames);
  corner_miter 9.4 s → 0.6 s. Three rounds, in order of payoff:
  1. **Do NOT borrow `production_rmsf_cached`'s `average_frame` for display geometry.** That was
     16 m 26 s of a 16 m 47 s response — it walks EVERY frame — against 21 s for the strain walk
     itself. `production_strain_field` already computes a mean frame over its own bounded sample,
     so ONE walk now yields both the values and the positions. Profiled split before this:
     parse/IO 6.3 s, unwrap+align 13.1 s, strain math 1.8 s, ref read 0.2 s.
  2. **Reuse the unwrap plan** (`_build_unwrap_plan` cached per key set, passed as `plan=`) —
     the same fix the composite-trajectory builder already had. Unwrap was the single biggest
     term; total 21.4 s → 16.8 s.
  3. Vectorized `strain_field`: `_strain_index` builds the endpoint arrays ONCE per key set,
     `_strain_values` does one batched `oxdna_backbone_sites` + a magnitude-sorted scatter for
     the worst-bond attribution instead of a per-bond Python loop (2 m 32 s → 1 m 29 s at the time,
     byte-identical output).
  For scale: the FLEXIBILITY map's `production_rmsf` on the same job measures **1079 s**. The
  strain map is now ~64x faster than its siblings, not merely comparable.
  Strain VALUES are byte-identical before/after (max |delta| 0.0e+00).

- **The mean frame is NOT the RMSF map's mean frame, and that is deliberate.** Measured on
  VoltronCoreScad they differ by **3.47 nm median / 7.3 nm max**, and the cause is fully isolated:
  it is ENTIRELY the torn-frame gate (gate-on vs gate-off over the same 805 frames = 3.468 nm, the
  identical figure), NOT sampling (60 vs 733 frames = 0.24 nm) and NOT a rigid offset (Kabsch
  residual == raw). **`production_rmsf` averages 72 of 805 torn frames into its mean structure**, so
  the flexibility and deviation overlays are displaced by up to 7 nm on long/resumed runs; the strain
  map's frame is the clean one. Consequence the user sees: the structure shifts slightly when
  switching between strain and flex/deviation on such a job. Applying the same gate inside
  `production_rmsf` would fix all three and make them coincide — NOT done here because
  `average_frame` also feeds PDB export, atomistic reconstruction and the shape descriptors, so it
  needs sign-off. A side benefit of dropping the merge: positions used to come from TWO different
  means (real keys from the 805-frame contaminated one, synthetics from the clean 60-frame one), i.e.
  tails were placed in a different mean structure than the duplex they hang off. Now one source.

- **Scope.** CG beads only (like deviation — excluded from `drivesHeavy`). oxDNA only: no LAMMPS
  (`strainToggle` force-disabled in `selectLammpsJob` + `_updateButtons`) and no NAMD/MD (`/md/...`
  has no strain route, so `md_viz_adapter` can't map it). Adding MD = a `md_trajectory.py` mirror of
  `strain_map` + a route, then the same panel block in `md_jobs_panel.js`.

- **Verified in-app** (corner_miter_optimized / job 48b20e31754c): both metrics render, legend +
  colormap picker work, mode switching tears down the peers, off restores; zero console errors.
  Coverage checked numerically — strain/backbone colours the IDENTICAL 1023-nucleotide set as the
  RMSF map, strain/wc the identical set as the deviation map.

- **`positions` IS THE MOVE LIST, not just the colour list** (third load-bearing bug).
  `applyFemPositions` deforms only the beads it is given; anything omitted keeps its DESIGN
  coordinates while its neighbours move. The `wc` metric measures only paired bases, so the
  original "skip unmeasured" emit left **2260 beads stranded in mid-air** on VoltronCoreScad
  (794 unpaired real ssDNA — overhangs + unstapled scaffold loops — plus 334 extension tails
  and 1132 extra bases). `strain_map` now emits EVERY key in `full_map` with `strain: None`
  where nothing was measurable; the frontend's `strainColorMap` puts all of them in
  `updates` but only finite-strain ones in `colorByKey`, so they ride along at their
  simulated positions in their native colour. `n_shared` = measured, `n_positions` = emitted;
  the status line reports "N bases coloured (M moved)". Pin:
  `test_wc_map_emits_unpaired_bases_so_they_still_move`.

- **"dsDNA only" display option** (`#oxdna-jobs-strain-dsdna-only`) — colour only what the
  design intends to be duplex, so a disrupted duplex flares instead of competing with ssDNA
  that is floppy *by design*. Classification is TOPOLOGICAL (`designed_ssdna_flags`): a
  `(helix, bp)` column with nucleotides on BOTH directions is duplex, everything else is
  ssDNA — unstapled scaffold (a deliberate loop, see
  [staples_are_user_intent](feedback_staples_are_user_intent.md)), overhangs, tails, extra
  bases. Never inferred from how the simulation ended up. Synthetic keys are forced ssDNA so
  two tails of one extension on opposite directions can't fake a duplex column.
  - The flag is a pure DISPLAY choice over the payload already in hand:
    `oxdnaDisplay.setStrainDsdnaOnly()` recolours from cache — no refetch, no second
    trajectory walk. It `clearScalarColors()` FIRST, because `applyScalarColors` leaves keys
    it isn't given alone and the excluded ssDNA would otherwise keep its old colour.
  - The backend ships a companion `dsdna: {min,max,mean,abs_max,display_abs,n}` block
    computed over the duplex subset, so the scale rescales with the toggle instead of letting
    one flailing overhang set the range for the duplex being inspected.
  - Excluded bases still MOVE — only the colour is withheld.
  - The quoted mean and data RANGE follow the filter too (`strainStats`), not just the colour
    scale: reporting the overall mean while colouring only the duplex misdescribes the map.
    Measured on corner_miter backbone: all = mean −3.8 %, range −8.1…+3.6 %; dsDNA-only =
    mean −4.0 %, range −8.1…+2.4 % (the most-tensioned bases there were ssDNA).
  - `wc` + dsDNA-only is a no-op by construction — that metric only ever measures designed
    pairs — so the two agree exactly. Expected, not a wiring bug.

- **Loading visualizer.** `#oxdna-jobs-strain-bar` + `_setStrainBar('computing'|'done'|'off')`
  mirrors the flexibility map's indeterminate stripe, with a metric-specific status line
  ("Averaging backbone bond strain over the trajectory…"). A targeted in-panel bar rather
  than the global "Working…" popup, per [busy_popup_threshold](feedback_busy_popup_threshold.md).

- Pins: `tests/test_oxdna_strain_map.py` (23, backend) + `strainBounds`/`strainColorMap` blocks in
  `frontend/src/ui/oxdna_display.test.js`.

**Test-fixture note:** the first version of the backend tests used bond lengths like 2.0 units
(+164 % strain). Those are physically impossible and the FENE-window guard correctly started
rejecting them — the fixtures were wrong, not the guard. Keep synthetic bond fixtures inside
`r0 ± delta` unless the test is specifically about rejection.
