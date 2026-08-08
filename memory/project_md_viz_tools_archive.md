---
name: md-viz-tools
description: MD jobs panel trajectory-scrub + flexibility-map (RMSF) tools — reuse the oxDNA display controller via an API adapter
metadata:
  node_type: memory
  type: project
  originSessionId: 515d0592-f4a2-4e8a-8812-9d875d0bd184
---

The MD jobs panel got oxDNA-parity visualization tools (trajectory scrub + flexibility/RMSF map) to replace VMD for viewing NAMD runs. Built 2026-06-22.

## Display-MD readiness dot: "off" used to mean "shrug" (fixed 2026-08-07)

`GET /md/jobs/{id}/display` returned a bare `ready: false` with no reason, and the panel
collapsed every such case to `'off'` — which **hides the indicator**. A run going on a
rented RunPod GPU therefore looked identical to having no job at all: toggle Display MD,
get nothing, no explanation anywhere.

`backend/core/md_display_status.display_not_ready()` (pure, tested) now classifies the four
genuinely different cases, and only one of them is a problem:

| code | meaning | dot |
|---|---|---|
| `no_package` | never built — nothing exists to show | hidden (the one honest absence) |
| `pending` | running here, no frames yet; resolves itself | `no frames yet` (dim) |
| `remote` | trajectory is on the pod/cluster; waiting will NOT help, it needs a fetch | `on the pod` (amber) |
| `empty` | terminal having written no trajectory | `error` |

`mdDisplayReadinessFromMeta()` in `md_display_state.js` maps code → state; the reason rides
in the dot's tooltip. A **null** meta (request failed) is `error`, not `off` — saying "off"
would claim the display had been assessed and found empty.

Two Alpine-isms fixed alongside: the toggle-on status line said *"Running on Alpine"* for a
RunPod job (`mdIsRemoteRunning` is Alpine-only, so it fell through to a generic "waiting"),
and `liveFrameLabel` labelled every snapshot "Alpine". Both take the execution target now.
The **spinner is reserved for waits that end on their own** — a trajectory sitting on a pod
gets none, because spinning promises an arrival that will never come.

All four cases verified in the running app, zero console errors.

⚠️ Testing this in Playwright needs `#md-jobs-show-all` checked: `filterJobsForPart` drops a
mock job that carries no part path, so `_selectDisplayJob()` returns null and the dot stays
'off' no matter what the meta says. That cost a while to spot.

**Architecture — reuse, don't reimplement.** `initOxdnaDisplay({api, ...})` is a factory that takes its data source as an injected `api` dep and calls it through oxDNA-named methods (getOxdnaTrajectory, getOxdnaRmsf, ...). The CG/nadoc-bead trajectory + RMSF payloads are byte-identical between oxDNA and MD (`md_trajectory.py` mirrors `oxdna_health`'s shapes). So a SECOND controller instance pointed at `mdVizApiAdapter(api)` (frontend/src/ui/md_viz_adapter.js — maps getOxdnaTrajectory→getMdTrajectory, getOxdnaRmsf→getMdRmsf) gives NAMD jobs the whole scrub/colour/recolor machinery with ZERO changes to the validated oxDNA controller. `mdViz` is created in main.js right after `oxdnaDisplay` (same renderer deps) and passed to initMdJobsPanel as `getMdViz`.

**Backend.** `md_rmsf()` in backend/core/md_trajectory.py pools ALL written segments (user chose "all segments" gating), Kabsch-aligns each sampled frame via the existing `_extract_md_nadoc_frame`, returns the oxDNA `/rmsf` shape. Route: `GET /md/jobs/{id}/rmsf` in routes_md.py. Trajectory endpoints (`/trajectory`, `/trajectory-meta`, `/frames-atomistic`, `/frames-surface`) already existed. RMSF default max_frames=150 (statistics fine; bounds per-frame Kabsch cost).

**P-ORDER MAPPING BUG — fixed 2026-07-02 (many-strand "map not ready").** `_build_md_nadoc_ctx` originally built the P-atom→(helix,bp,dir) order ONLY via `build_p_pdb_order`, which keys off the reference PDB's SINGLE-char chainID. CHARMM psfgen collapses NADOC's multi-char chain ids (`A`,`AA`,`AB`,…) into one letter, so for many-strand designs the keys collide → atoms DROPPED → `len(p_order) != ` universe DNA-P count → md_rmsf's strict guard `len(p_nm)!=n_keys` skips EVERY frame → `ready:false` with no reason → frontend fallback text "not ready" (oxdna_display.js:525). Real case: 3x6x200 (77 strands) mapped 6758 of 7229 P atoms. FIX: extracted `_select_p_order(u, cm, run_dir, coordinate_path)` — tries the segid map (`load_segid_chain_map`+`build_p_order_from_universe` from charge_audit.json) FIRST, falls back to PDB only when charge_audit absent/incomplete. This mirrors what ws.py's live-display NAMD branch already did (which is why live Display-MD worked but the flex map/trajectory didn't). md_rmsf now returns a real `reason` on total-drop (design/topology atom mismatch). Also: `_md_traj_inputs` + the trajectory route now analyse the job's FROZEN `design.json` snapshot (`_md_snapshot_design`, active-design fallback for legacy jobs) — like the oxDNA route — not the live active design. Regression: `tests/test_md_p_order_mapping.py` (fast, always-on, fakes the collision); heavy real 3x6x200 e2e in test_md_trajectory.py is env-gated `NADOC_RUN_HEAVY_MD_FIXTURE=1` (~20min: 3600-nt model build + 1M-atom unwrap).

**EXPLICIT SOLVENT + PERIODIC CELL ARE NOW DRAWN (2026-07-30).** Three checkbox layers in the
Visualizations card — Water, Ions, Periodic box — over the trajectory view. Until now every display
path funnelled through the positive DNA whitelist `_GRO_DNA_RESNAMES` (`md_trajectory.py:131-138`),
so none of the simulated solvent ever reached the viewer.

- **`backend/core/md_solvent.py` is the single owner** of (a) the display affine, (b) solvent
  selection/imaging, (c) the wire format. A guard test
  (`test_atomistic_to_nadoc.py::test_no_path_reimplements_the_solvent_display_transform`) fails if
  `box_corners`/`apply_xform`/`DisplayXform` are defined anywhere else under `backend/` — the same
  shape of guard as the PBC-snap one, for the same reason.
- **The affine is HANDED OVER, never re-derived.** A served coordinate is
  `(pos_pre - mob_c) @ R_align.T + eq_centroid`, computed at four sites today
  (`md_trajectory` heavy :468 + bead :292, `ws.py` :761 + :947) and previously discarded at all four.
  `_extract_md_atoms_frame(..., frame_out={})` now returns it plus `pos_raw`/`pos_pre`; return value
  and every existing caller unchanged. Verified on a real job: the emitted affine reproduces the
  served DNA coordinates to **exactly 0.0 nm**.
- **Water is bounded, ions never are.** Hydration shell (default 5 Å, adjustable) measured to DNA
  HEAVY atoms via `capped_distance`; "whole box" also selectable. Ions max out ~15 k so they are
  always drawn in full. **MGH gets no special case**: the MG atom is the ion, its six waters are
  water — which is why each Mg sphere visibly carries its own hydration shell on screen. Consequence
  for counts: drawable water = the charge audit's bulk `n_waters` **+ 6·n_mg**.
- **"I can't see the Cl⁻" is usually not a rendering bug — a Mg-neutralised box barely has any.**
  Since the 2026-07-30 protocol switch, `ion_counts` neutralises with Mg(H₂O)₆²⁺ and adds Cl⁻ only to
  zero the *system* (`n_cl = 2·n_mg − |q_DNA| + n_nacl`, `namd_solvate.py:1266`), with `nacl_mM = 0`.
  For a small design that rounds to almost nothing: real 2hb_1xT job — |q| = 93 e → 47 Mg, **1 Cl**,
  confirmed in the PSF. Bigger boxes are fine (10hb: 948 Na / 38 Cl / 19 Mg). **Read
  `charge_audit.json` → `ionization` before suspecting the overlay**; the panel's ion legend already
  prints the per-species counts. More chloride only comes from bulk salt above neutralisation.
- **The ion legend and the ion RENDER answered to two different sources — fixed 2026-08-06.** The
  render draws what MDAnalysis finds in the PSF; the legend read `charge_audit.json`. Two ways they
  diverged, both seen live on the running **6hbx100_noT** production job: (1) not every package
  writes a standalone `charge_audit.json` — replica packages hardlink only structure files and some
  builders fold the audit into `manifest.json` — and `md_solvent_meta` had no manifest fallback, so
  it answered `ready:false, species:{}`; `{}` is truthy in JS, so the panel printed **"no ions in
  this job"** over a cell full of Mg²⁺ (and priced every fetch off `n_waters:0`). (2) the audit only
  tracks Na/Cl/Mg, so a K⁺ or Ca²⁺ job was invisible to it. Fix, both layers: `md_solvent_meta`
  falls back to `manifest["charge_audit"]` (same fallback `atomistic_to_nadoc._segid_chain_map`
  already used), and the legend now takes its counts from the **landed frame** —
  `tallyIonSpecies(parsed.ionSpecies, parsed.speciesTable)`, exact because ions are never
  shell-bounded or capped — falling back to the audit only before a frame exists and rendering
  NOTHING when neither can back a claim. `setJob` also retries the audit while it is `ready:false`
  instead of caching the not-ready answer for the life of the panel. **Rule: metadata prices a
  fetch, it never makes a negative claim about the structure.**
  Because of this, **Cl⁻ and Mg²⁺ are deliberately OFF-CPK** (CPK puts both in green and leaves
  radius as the only cue): Cl⁻ = pure green `0x00E000`, Mg²⁺ = yellow `0xFFD400`, in BOTH
  `scene/md_solvent_overlay.js::ION_STYLE` and `scene/atomistic_renderer/atom_palette.js` — change
  the two together. One chloride among 47 magnesiums has to be findable by hue alone.
- **The box origin is the STRUCTURE, not the lab cell.** A NAMD DCD stores cell lengths but no
  origin, so the cell is drawn centred on `c_box` (the PBC-robust DNA centroid the reassembly already
  computes). Lengths + orientation are the simulation's own, so it breathes with the barostat and
  rotates with the design alignment. It is a rotated cuboid in view space — `Box3Helper` is wrong;
  `md_box_overlay.js` writes the 12 edges into a 72-float buffer directly.
- **EVERY BLOCK IS OPTIONAL, and the header must say which are present — format v2
  (2026-07-30).** The three toggles are independent, so any subset of water/ions/box can be
  absent. v1 wrote an EMPTY block for a disabled species while the header still advertised the
  full ion count and the reader always consumed a fixed 24-float cell, so any combination with a
  gap put every later read at the wrong offset, `parseSolventBin` bailed, and **Water-alone and
  Ions-alone silently drew nothing** — only all-three-on (and ions+box, by luck) lined up.
  Reported from the app. Fix: `n_ions` / `has_box` / `per_frame_nw` / `n_serials` now describe
  what was WRITTEN, totals ride separately as `n_waters_total` / `n_ions_total`, and
  `pack_solvent_bin` ASSERTS block-vs-header agreement so a caller cannot reintroduce the desync
  silently. Version bumped 1→2 and the parser rejects anything else, so a stale tab fails closed
  instead of misparsing. Pins: all 8 combinations round-trip (pytest) + all 7 non-empty
  combinations parse (vitest, incl. real backend bytes for the water-only case). **Lesson: a
  fixed-layout binary format needs a test per on/off combination, not just the all-on one** — my
  original fixtures always populated every block, which is exactly why the suite was green while
  the feature was broken.
- **Binary wire format** (`pack_solvent_bin` ↔ `scene/md_solvent_bin.js`, magic `NSLV`), mirroring
  `pack_surface_bin`. Whole-box atomistic water is millions of numbers/frame; JSON would be tens of
  MB plus a `JSON.parse` that materialises a JS number array first. JSON header is zero-padded to 4
  bytes so the Float32 views are legal. `include_dna` piggybacks the frame's DNA coords so an
  atomistic-rep scrub pays the ~30 s context build ONCE per chunk instead of twice.
- **The molecule set changes every frame** (a shell is a distance query; water diffuses — measured
  20 595 then 19 837 at 5 Å on the same run). Two consequences baked into the overlay: it is
  **capacity-allocated** (grow-only, only `mesh.count` moves) rather than rebuilt like
  `md_overlay.js`, and it **SNAPS to a frame, never lerps** — molecule *k* of frame *i* is a
  different molecule from molecule *k* of frame *i+1*.
- **Ions are ONE MESH PER SPECIES.** A single mesh cannot carry per-species radii under impostors
  (the painted radius is a material uniform). They first shipped 7× oversized because the impostor
  test was `atomInstanceScale(1) === 1`, which is true in BOTH paths — caught by screenshot, not by
  a unit test. Pinned now.
- **Measured on the real 11 M-atom VoltronCore job:** 250 458 shell waters + 15 178 ions = 3.2 MB
  per frame, 36 s (≈30 s of that is the per-request MDAnalysis context build). The ion cloud renders
  as a cast of the origami — Na⁺ condensed on the polyanion — which is the physical check that the
  imaging and the transform are right.
- **TWO TRANSPORTS, one overlay.** The trajectory view fetches + caches over REST; the live
  "Display MD" stream gets solvent pushed over the job WebSocket (`{"action":"set_solvent",…}` →
  a BINARY message beside each JSON frame; the client sets `ws.binaryType='arraybuffer'`).
  `setEnabled(on, 'live'|'traj')` picks the transport, and switching between them drops the cache
  (a live frame index is a stream position, not a composite trajectory index — fetching against it
  would return some other frame's solvent). Three things this cost:
  - **`heavy_idx` is now built for EVERY ws mode, not just ballstick.** The shell is measured to
    DNA heavy atoms, and the coarse branch had only P atoms; a phosphate-anchored shell would be a
    different quantity from the trajectory view's at the same setting. The selection is cheap — the
    expensive `atom_meta` + design-identity build stays ballstick-only.
  - **`md_solvent.reconstruct_heavy_pre`** hoists the residue-local
    `heavy = corrected_P + minimage(raw_heavy − raw_P)` reconstruction so the coarse branch can
    produce anchors. Vectorised, with the anchor rows memoised on `_ctx` (they are a topology fact).
  - **The request is replayed on reconnect.** A representation change tears the socket down and
    rebuilds it; without the replay in `onopen` the overlay silently goes dark on a rep switch.
    Pinned (`md_panel.test.js`, proven to fail without it).
  Verified against the real VoltronCore job in both modes: CG 90 k shell waters + 15 178 ions in
  15 s; atomistic the same in 18 s with real O+2H molecules. Cross-check that the anchoring is
  right: the same water set is ≤2.8 Å from the nearest DNA **heavy** atom but up to 13.4 Å from the
  nearest **P** — which is exactly what a heavy-atom shell should look like measured against beads.
- Files: `backend/core/md_solvent.py`, `md_trajectory.md_frames_solvent`, routes
  `POST /md/jobs/{id}/frames-solvent-bin` + `GET /md/jobs/{id}/solvent-meta` (the latter reads
  `charge_audit.json` + `manifest.json` only — no MDAnalysis, answers in ms so the panel can price a
  fetch before making one); `scene/md_solvent_bin.js`, `scene/md_solvent_overlay.js`,
  `scene/md_box_overlay.js`, `ui/md_solvent_controls.js` (own module — the panel gains only wiring),
  `md_display_state.solventRepMode`. Pins: 4 fast pytest files (61) + 5 vitest files (~100) + a
  cross-language byte pin + `tests/test_md_solvent_extraction.py` (16, slow/`md`).

**Frame steppers ◂/▸ (2026-08-01).** Every trajectory scrubber in the app now has ±1-frame arrow
buttons flanking its slider: oxDNA/LAMMPS + NAMD (both via `oxdna_trajectory_player.js`'s new
`prevBtn`/`nextBtn` opts), SNUPI, BLADE, and the live `#md-panel` scrubber. Dragging a range input
across a few hundred frames moves several frames per pixel, so landing on a specific frame was luck.
Shared module: `frontend/src/ui/frame_steppers.js` (`stepFrameIndex` / `frameStepperDisabled` pure +
`initFrameSteppers({prevBtn,nextBtn,count,current,onStep,wrap})`); markup is `.frame-step-btn` in
index.html next to each scrubber. Clamps at the ends (buttons grey out) except SNUPI/BLADE, whose
playback already wraps, so their steppers wrap too. Stepping always pauses playback. The live
`#md-panel` one moves its own readout optimistically before the WS `seek`, so rapid clicks step from
the last click rather than the last delivered frame. Pins: `frame_steppers.test.js` (18) +
`oxdna_trajectory_player.test.js` `◂ / ▸ frame steppers` block (4).

**Panel (md_jobs_panel.js).** flex + traj toggles/controls mirror oxdna_jobs_panel; reuse `oxdna_trajectory_player.js`. Three display modes (live "Display MD" / flexibility map / trajectory) are MUTUALLY EXCLUSIVE — each deforms the same design model, so activating one calls stopAndRestore on the others. Rows now have `data-job-id` (for the e2e + the existing md_live_no_stale spec).

**v1 scope = CG/nadoc representation only.** Deliberate follow-ons: (1) heavy-rep (atomistic/surface) RMSF colouring — the per-frame atomistic data shapes differ between oxDNA (template) and NAMD (real DCD atoms), needs its own mapping, so the adapter intentionally omits the heavy methods (controller heavy path is a no-op for CG, fails closed for atomistic/surface scenes); ~~(2) the draggable colour-rescale widget~~ **DONE 2026-07-10** — see below.

**⚠️ (1) IS NOW HALF-DONE — the per-frame TRAJECTORY heavy reps work; the FLEX-MAP ones still
don't (2026-07-29).** Reported as "switching to atomistic during View trajectory just shows the
NADOC native positions". Cause was exactly the omission above: `md_viz_adapter` mapped no
`getOxdnaFramesAtomistic`/`Surface`, so `_applyHeavy`'s trajectory branch called `undefined`, the
`catch` swallowed it, and the heavy rep sat at design coordinates. Three parts to the fix:
- **The two shapes are genuinely different and the controller now branches.** oxDNA reconstructs
  the DESIGN's atoms → flat XYZ laid over a per-job topology template fetched by
  `_ensureJobAtomistic`. NAMD renders the SIMULATION's own atoms → each frame is a self-describing
  `{atoms, bonds}` set. Feeding the latter down the oxDNA path is precisely what failed:
  `_ensureJobAtomistic` has no MD topology route to call, returned false, and nothing painted. New
  `_pushMdAtoms` in oxdna_display.js calls `ar.update({atoms, bonds})` instead — the same recipe
  `animation_player.js:906` already used for NAMD trajectory keyframes. Guarded by `_mdAtomKey`
  (`update()` rebuilds every mesh, so it must not re-run while the snapped frame is unchanged);
  cleared in `_restoreHeavy`.
- **`_trajStride` is repeated on every heavy fetch, exactly like `_trajScope`.** Composite frame
  indices only address the same frame within one downsample.
- **The composite→raw index bug is FIXED (it was silent).** `md_frames_atomistic`/`md_frames_surface`
  indexed the RAW concatenated universe while every caller passes COMPOSITE indices — identical only
  while nothing was dropped, i.e. runs under the cap, which is why it was never noticed. New
  `composite_raw_frame_map(segments, max_frames, stride)` (DCD headers only) translates; keys stay
  composite. Also fixes the animation player's NAMD trajectory keyframes on >200-frame runs.
  `MdFramesAtomisticBody`/`MdFramesSurfaceBody` gained `stride`.
- **NAMD atomistic is atoms-only — `bonds: []` is the established contract**, not a regression here:
  the live WS ballstick path (`ws.py` sends `atom_meta` + `atom_ident`, no bonds) and the animation
  player do the same. Ball-and-stick therefore draws spheres without sticks for NAMD everywhere.
  Adding real bonds means emitting the PSF bond list once and caching it across frames — a change to
  all three paths, not done.
**ALL-ATOM TRAJECTORY IS NOW PREBUILT, NOT RECONSTRUCTED WHILE YOU SCRUB (2026-07-29).**
Follow-up to the above. Two costs made the lazy approach untenable, both measured on
`76759a458653` (VoltronCore, 302 197 DNA heavy atoms, serials to 469 350):
- **Memory.** A frame as JSON atom OBJECTS is 53 MB on the wire and ~72 MB of JS objects.
  Twelve of those is 0.9 GB — which is precisely why `_COARSE_ATOM_CAP` was 12 and the
  atomistic view was far coarser than the beads.
- **Latency.** `_coarseFrame` fetched ONE frame per request, and the MD analysis rebuilds
  its context (PSF parse + model) **per request**: measured 34.5 s for 1 frame vs 45.6 s
  for 5 in one call ⇒ ~32 s fixed + **~2.8 s marginal**. So every first visit to a grid
  cell paid the full 32 s again.
**Fix = the oxDNA shape.** New `md_atomistic_model()` + `GET /md/jobs/{id}/atomistic-model`
returns the STATIC atom set once (identity + `n_serials` + `bonds_available:false`);
`md_frames_atomistic(..., positions_only=True)` returns serial-indexed flat coords.
`md_viz_adapter` maps `getOxdnaAtomisticModel`, so `_ensureJobAtomistic` →
`applyPositionLerp` — the **validated oxDNA path, reused unchanged**. `_pushMdAtoms` (added
hours earlier) was deleted: with a topology it is redundant, and it also removed the
per-frame `ar.update()` mesh rebuild. Measured: **8.5 MB/frame wire (6.3x), 5.4 MB/frame
as Float32Array (13x)**; 5 frames in one call 44 s vs ~172 s as five calls.
- **The budget is measured against THIS machine, not a constant.** Two independent limits,
  lower wins (`prebuildMemoryPlan`, pure + exported):
  1. **`heap`** — `BROWSER_HEAP_CEILING_BYTES = 1536 MB`. A 64-bit tab will not hand out an
     unbounded JS heap however much RAM the box has, and hitting the ceiling **kills the
     tab**, it does not merely slow down. Also the fallback when free RAM is unreadable —
     an unknown machine is never assumed to be a big one.
  2. **`ram`** — `FREE_RAM_SAFE_FRACTION = 0.5` of the host's **MemAvailable**, read from
     the EXISTING `GET /system/resources` (the System-monitor endpoint; backend runs on
     localhost, so its reading is the browser's machine). `build_resource_sample` gained
     `ram_available_mb` — MemAvailable, not total-minus-used, because it counts reclaimable
     cache and is the number a "will this allocate?" question actually needs. `None` on a
     failed probe, never 0 (0 would refuse everything on a healthy machine).
  Browser APIs were NOT used: `navigator.deviceMemory` is Chrome-only (absent in the
  Firefox this is developed in), reports TOTAL not free, and rounds to a power of two.
  `performance.memory` is Chrome-only too.
- Priced BEFORE the ~30 s topology fetch via `SERIALS_PER_NUCLEOTIDE_EST = 32` (measured
  469 350 / 14 774 = 31.8) against `n_nucleotides`, which the trajectory payload always
  carries; the exact serial span takes over once known. So the first load is priced, not
  attempted blind.
- If the plan is capped **by RAM specifically**, the panel confirms first, quoting need vs
  free ("needs about 5.2 GB, but only 512 MB is free"), and offers the affordable count.
  A heap-bound cap is not worth interrupting for — it just reports. The status line names
  which limit bound ("free RAM" / "browser memory limit"), never a bare "memory limit".
  Live check on this box: 24.4 GB free of 31.2 → RAM allows 12.2 GB but heap binds at
  1536 MB → **285 VoltronCore frames**.
- `affordableAtomFrames(nSerials, nFrames, budget)` sizes the grid; the panel injects the
  budget via `prebuildHeavy(cb, {budgetBytes})`, so the RAM *policy* lives in the panel
  (which does the talking) and the controller just obeys a ceiling.
- **Batching is a declared CAPABILITY, not a blanket change.** `mdVizApiAdapter` sets
  `heavyBatch: true`; `prebuildHeavy` then chunks 8 indices/request and SKIPS the
  warm-one-cell-first step (that step helps oxDNA's server-side alignment cache; here it
  is just an extra 32 s context build). oxDNA keeps its pinned one-frame-at-a-time
  behaviour — `oxdna_display.test.js` has explicit invariants for it, deliberately: an
  oxDNA frame is an independent multi-second rebuild, so a big upfront bake is wrong there.
- `_narrowFrame` converts flat coord arrays to Float32Array (halves cache RAM; meshes pass
  through). `bonds_available === false` is an explicit declaration — NOT an empty list —
  because oxDNA's VDW fetch is also bondless and there the bond warm-ahead re-fetch is right
  (learned by breaking that test).
- Trigger: `_prebuildTrajHeavy` runs after every trajectory load AND on
  `nadoc:representation-change` while scrubbing, with `preparing atoms N/M…` progress.
  No-op for CG.

**PER-FRAME EXTRACTION VECTORIZED — 2.25 s → 0.18 s (12.5x), byte-identical (2026-07-29).**
Profiled `_extract_md_atoms_frame` on the real 302 197-atom job: the cost was almost
entirely per-atom Python, not numerics — 728 k `AtomGroup.__getitem__`, 382 k `.residue`
property builds, and **906 k scalar `np.round` calls** (3 per atom for the min-image
correction). The insight: **which P anchors which heavy atom is a TOPOLOGY question**
(residue ix / segid / resid), identical for every frame, and it was being re-resolved
per frame. New `_build_heavy_anchor_rows(heavy_ag, dna_p)` builds it ONCE per ctx
(memoized in `ctx["_heavy_anchor_rows"]`, so no change to the ctx builder or the bead
path), then the correction is one array op. Ties resolve LAST-wins to match the dict
comprehension it replaced. Verified `max|new − old| = 0.000e+00 nm` on frames 0/2/4 of
the real job against a transcribed copy of the old loop.

**Where the remaining time is — and why true streaming needs an architecture change.**
Measured split on VoltronCore (423 MB PSF): **context build 30.5 s** (PSF parse + model)
+ **0.18 s/frame**. The context is paid **per REQUEST**, because `md_analysis_runner`
spawns a fresh killable `Process` per call and kills it after — that killability is
deliberate (it is how a client disconnect aborts a runaway MDAnalysis read), so an
in-process ctx cache cannot survive. Consequences:
- Chunk size is a direct trade: every extra chunk is another whole 30 s context build.
  `CHUNK = 32` (was 8 — which cost 7 rebuilds on a 55-frame prebuild).
- The prebuild queue is **sorted by distance from `_frameIdx` and re-sorted between
  chunks**, so a seek mid-build redirects the remaining work and the frames around the
  playhead arrive first. That is as close to "buffer from here" as this backend allows.
- **Real streaming (seek anywhere, frames in ~0.2 s) needs a persistent per-job worker**
  holding the built ctx, with frames served on demand — i.e. replacing the
  spawn-and-kill model with a warm worker plus an explicit cancel channel. Not done:
  it changes the cancellation semantics that exist on purpose. That is the next big win
  and would make the 30 s cost a once-ever, not once-per-request.
- Pins: `affordableAtomFrames` (5), `md_viz_adapter.test.js` (topology-once, positions-only,
  stride repeat, ONE batched request, cache-hit on scrub), backend signature-pair test.

- Verified read-only on real job `76759a458653`: composite 2 @stride 2 == composite 4 @no-stride
  (both raw frame 4) and differs from composite 2 @no-stride — the translation proven end to end;
  302197 atoms/frame carrying `strand_id`/`helix_id`/`bp_index`/`direction` so `color_resolver`
  colours them; surface 257k verts. Pins: `tests/test_md_composite_indices.py` (31),
  `md_viz_adapter.test.js` (+4, **proven to fail against the pre-fix adapter**),
  `oxdna_display.test.js` (5th positional arg). **NOT click-verified in the browser.**

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

**PBC: the design-reference snap was tearing the backbone — fixed 2026-07-28.** The MD display
showed "a few bases missing wrapping" — small clusters floating a box off the structure.
`reassemble_to_posed_reference` step 5 nearest-image-snapped **per atom** to the posed design
reference. That reference is an IDEAL structure, so wherever the simulated one has drifted past
half a box from it (routine at a flexible crossover or a bundle end) that atom rounds to a
different periodic image than its own chain neighbours and jumps a full box ALONE. Measured on the
2hb_1xT 4 fs production: exactly 2 broken O3'-P bonds in EVERY frame, 3.7-4.4 nm long (= box_x),
all inside strand D002 near residues 31-35. Note `snap_mask` was NOT the culprit — all 93 P atoms
were snapped; the free-ssDNA exclusion is a separate, working concern.
**Fix:** snap **per strand run** (`_strand_runs`, same backbone-gap criterion as
`_unwrap_min_image`), taking the MEDIAN of the run's per-atom shifts so a few mis-referenced atoms
are outvoted. The sequential unwrap already makes each strand internally contiguous and the snap's
only real job is choosing WHICH image a strand sits in, so one lattice shift per run preserves
contiguity by construction — a lattice translation cannot change an intra-run distance. After:
0 broken bonds across all frames, longest bond 0.169 nm. Shared by all four callers (ws.py live,
bead, and all-atom trajectory), so one fix covers every view. **Oracle worth reusing: audit BOND
LENGTHS against the PSF topology.** Distance-from-centroid does not work — this bundle is
legitimately 4.5 nm from its centroid in a 9.94 nm box, so it flags real structure; a broken
covalent bond is unambiguous. Pins: `test_atomistic_to_nadoc.py` (+4, the torn-backbone case
proven to fail against the pre-change per-atom snap at 3.91 nm).
**⚠️ The fix did not land the first time.** `ws.py`'s ballstick (all-atom LIVE display) branch
carried its OWN inlined copy of the older translation-only per-atom snap and never called the
shared function — so fixing `reassemble_to_posed_reference` changed nothing on screen. It now
delegates, and a guard test fails if any file under `backend/` outside `atomistic_to_nadoc.py`
re-implements the snap (matches `eq_box=`/`ref_box=`/`round(dc[`). Verified to flag the pre-fix
`ws.py`. Lesson, third time this session: **fix the path in use, not the leaf** — a shared
helper is only shared if every caller actually calls it.

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
- **NAMD's read-side 200 is now a user-set FRAME INTERVAL — 2026-07-29.** The NAMD half of (2)
  above stayed hardcoded when oxDNA got `scope`; a 991-frame 18hb run always came back as 198
  frames with no control. Both `/md/jobs/{id}/trajectory` and `/trajectory-meta` now take an
  OPTIONAL `?stride=N` = "keep every Nth frame **of each written segment**" (VMD's DCD stride,
  applied per file — so every non-empty segment keeps at least its own frame 0 and the boundary
  markers stay meaningful). **Omitting it is load-bearing**: no param → the byte-identical legacy
  ≤200 proportional budget, which is what `animation_panel`/`animation_player` trajectory
  keyframes (`main.js:1583/1589`) and `blade_runner.py:648` still ride. Only the Visualizations
  card sends an interval. `_composite_indices(seg_counts, max_frames, stride)` in md_trajectory.py
  is now the ONE place the selection is decided — `md_composite_meta` and `md_composite_trajectory`
  used to carry separate copies, and drift between them desyncs the slider from its frames.
  `md_composite_meta` also returns `total_raw` + per-stage `n_raw` so the panel can price a
  different interval with zero network. UI: `#md-jobs-traj-interval` (default 20, from the HTML
  `value=` attr via `form_defaults`) + `#md-jobs-traj-frames-hint` ("→ 15 frames of 300 written",
  amber at `TRAJ_FRAME_CONFIRM = 500` → `window.confirm` before the load; warn, never cap).
  Typing re-prices on `input`; committing on `change` re-loads. Route timeout goes 180 s → 900 s
  when an interval is given. `loadTrajectory(jobId, align, scope, stride)` — stride APPENDED last
  (inserting before an existing param is the align/signal hazard below); `md_viz_adapter` forwards
  `stride` (not `align`, not `scope`); `getMdTrajectory(id, signal, { stride })` takes a third
  positional OBJECT so it can't be mistaken for the signal. **Interval 20 gives FEWER frames than
  the old cap on a short run** (100 written → 5) — that is VMD-faithful and the readout makes it
  visible; lower the interval for density. Pins: `tests/test_md_composite_indices.py` (27, incl.
  the randomised legacy-equivalence compat pin + the positional-order guard for the analysis
  subprocess's arg tuple), `md_jobs_panel.test.js` (`stridedFrameCount` + 8 jsdom wiring tests),
  `md_viz_adapter.test.js`, `client_viz_opts.test.js` (URL query). Verified read-only against real
  jobs: 18hb `e29d1e5d5ace` 991 raw → 198 legacy / 55 @20 / 199 @5 / 991 @1, meta == ceil-per-
  segment every time; VoltronCore `76759a458653` full heavy build 5 frames legacy vs 3 @stride=2.
  Still open: `md_frames_atomistic`/`md_frames_surface` index the RAW universe while their only
  caller passes COMPOSITE indices — pre-existing, unchanged, only correct when raw ≤ the kept count.
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

**BALL-AND-STICK GOT ITS STICKS (2026-07-31).** MD Display in ball-and-stick drew bare
spheres for every NAMD job — live or finished — because `/ws/md-run` never sent bond
topology and `md_panel.js` substituted `bonds: msg.bonds ?? []`, which was *always* `[]`
(a frame carries coordinates only; verified on the live job — no `bonds` key). Not a
renderer fault: `md_solvent_overlay.js` was happily drawing O–H sticks for explicit water
in the same scene, which is the tell that the material/cylinder path was healthy and only
the DNA bond list was empty.

- **Connectivity is STATIC, so it rides `ready`, not the frame** — the same reasoning
  `atom_ident` already used. `ws.py::_heavy_bond_pairs(u, dna_heavy.indices)` filters the
  PSF's bonds to the drawn heavy subset and emits FLAT serial pairs in the `atom_meta`
  serial space (universe-global `Atom.index`); the frontend caches it once
  (`toBondPairs` → `Int32Array`) and re-hands it to every frame.
- **Flat, not `[[i,j],…]`** — ~325 k pairs on a 3 kbp origami, and the renderer's
  `_bondEnds` already accepts a typed array. Real live job (2hb_2xT, 62 730 atoms
  solvated): 2 003 heavy atoms → **2 248 bonds, 0.03 MB** in `ready`. Bond parsing is
  free — `_try_unwrap` already touches `u.bonds` on the same load.
- **No box-spanning sticks, by construction.** A covalent bond never crosses a strand run,
  and `reassemble_to_posed_reference` snaps per strand run to one periodic image (this is
  the D12 machinery). Measured on the live frame: median 0.144 nm, max 0.303 nm, **zero**
  over the renderer's 1.0 nm `_MAX_BOND_NM` hide threshold.
- **Still unbonded: the trajectory-scrub REST path** (`md_trajectory.py::md_atomistic_model`
  / `md_frames_atomistic`, `bonds_available=False`). Its comment used to justify `[]` as
  "the established NAMD contract, ws.py does it too" — that justification is now dead and
  the comment says so. Porting is the same three lines against `ctx["universe"]`.
- oxDNA never had the symptom: its atomistic bundle derives bonds from the DESIGN topology
  (`atomistic.py`), not from the simulation's own, so they exist regardless of job state.
- Pins: `tests/test_md_ws_bond_topology.py` (6, backend) + a `toBondPairs` block in
  `frontend/src/ui/md_display_state.test.js` (5).

**REPRESENTATION-SWITCH AUDIT (2026-08-01).** An end-to-end audit of "change representation while
an oxDNA/NAMD visualization option is on". The switch path is
`representation_switcher._setRepresentation` → six `nadoc:representation-change` listeners
(md_panel live WS · md_solvent_controls · md_jobs_panel heavy prebuild · oxdnaDisplay ·
mdViz · the slab-options auto-expand). Five real defects, all fixed:

- **The "native flash" suppression was oxDNA-only, so NAMD paid the design build twice.**
  `getSimOverlayWillDriveHeavy` read `oxdnaDisplay.drivesHeavy()` and nothing else, so scrubbing a
  NAMD trajectory and pressing F7 hid the CG, fetched + built the DESIGN's all-atom model (seconds,
  and the *wrong structure* on screen), and only then let mdViz rebuild from the job. It is now
  **kind-aware** — `getSimOverlayWillDriveHeavy('atomistic' | 'surface')` — and asks all three
  controllers that can drive a heavy rep: `oxdnaDisplay` (both kinds), `mdViz` (whatever
  md_viz_adapter maps), `mdDisplayController` (**atomistic only** — the live stream carries beads
  or atoms, never a surface).
- **The kind argument is not decoration.** A single boolean cannot express this: a NAMD flexibility
  map can deliver NEITHER kind, and deferring the design build to an overlay that never delivers
  leaves a blank surface / empty atoms up forever. `drivesHeavy(kind)` answers from the injected
  `api` (`_HEAVY_ROUTE` × `typeof api[route] === 'function'`), **not** from an engine name — so a
  route added to md_viz_adapter later starts working with no change in the controller.
- **mdViz needed `onHeavyApplied`.** Now that it triggers the defer path, the CG is deliberately
  left up and only that callback takes it down when the simulated atoms land. Without it a NAMD
  trajectory in vdw/ballstick draws CG beads through the atoms. (`main.js`, mdViz init.)
- **The NAMD flex map in a heavy rep now says so.** `getOxdnaRmsfAtomistic|Surface` are unmapped by
  the adapter (deliberate — see its header); `_applyHeavy` called the undefined method, threw, and
  the blanket `catch {}` swallowed it, leaving the design's equilibrium structure on screen looking
  like a result. It now emits `{unsupported: true}` on the heavy-status event and
  `atom_surface_display` turns that into a toast pointing at F2–F4.
- **Relaxed + RMSF heavy payloads are memoised** (`_memoHeavy`, keyed `align|mode|kind`, dropped on
  job change / `refresh()` / stop). Trajectory frames were already grid-cached; these were not, so
  an F6↔F7 flip — which changes the renderer's GEOMETRY and not one coordinate — re-downloaded the
  whole multi-megabyte all-atom payload every press.
- **Solvent no longer refetches on a rep change that doesn't flip the wire format.**
  `solventRepMode` collapses seven scene reps onto three modes, so `full`↔`beads` (both `sphere`)
  and `cylinders`↔`hull-prism`↔`surface` (all `off`) were wiping the cache and re-downloading every
  buffered frame for nothing. `vdw`↔`ballstick` is the third case: same payload, different overlay
  bond geometry → **redraw, no fetch**. The comparison is seeded in `setEnabled()`, never at wiring
  time — `getCurrentRepr` closes over a `main.js` `let` declared further down and reading it during
  construction is a TDZ throw that kills app boot.
- **Re-picking the active representation is now a no-op** — see `project_mixed_representation.md`
  for the master-reset exemption.

**LEGACY REMOVED — md_panel's own representation vocabulary.** `#md-panel` is `display:none` in
`index.html` and nothing un-hides it (`main.js`'s `_DESIGN_PANEL_IDS` only saves and restores that
same `'none'`), so its `#md-repr` select — NADOC Full / **Beads Only** / Ball & Stick — was
unreachable UI *and the only writer that could set `_repr = 'beads'`*. That made `_applyFrame`'s
beads branch dead, and with it the `md_overlay` bead cloud in md_panel, `_beadSize`, `_opacity` and
their sliders; the whole `initMdOverlay` instance in `main.js` went with them (mrDNA keeps its own —
there the bead cloud is a real standalone rep). `_repr` is now documented for what it is: the
**socket wire mode**, always `targetStreamMode(_sceneRepr)`, stored rather than derived only so
`decideReload` can compare "mode the socket was opened with" against "mode the scene now wants".
A per-frame `console.log` in `_applyFrame` went too.

**STILL OPEN.** (a) The rest of the hidden `#md-panel` chrome — config browse / Load / scrubber /
play / loop / live / output log / metrics — is still live code writing to invisible DOM; making
md_panel headless is a separate carve, not a representation change. (b) mrDNA / CanDo / SNUPI /
LAMMPS register no `nadoc:representation-change` listener and only write `applyFemPositions`, so
choosing a heavy rep silently discards their displayed result — same class as the first item above,
untouched here. (c) The flexibility-map heavy routes are still unmapped; the failure is now loud
rather than fixed.

Pins: `oxdna_display.test.js` → `relaxed / RMSF payload memo` (4) + `drivesHeavy(kind) capability`
(5); `md_solvent_controls.test.js` → `representation change → cache invalidation` (4);
`representation_switcher.test.js` → `no-op re-pick` (4) + 2 assembly-mode. All RED-verified against
the pre-change code (the memo, capability, unsupported, solvent and no-op pins each fail without
their fix).

**VERIFIED IN THE APP (2026-08-01) — `frontend/e2e/repr_switch_with_md_viz.spec.js`.** Three
tests against a real finished NAMD job (2hb_1xT, `29c5b267380f`, 200 composite frames), driving
the real UI: library → Simulations → NAMD → job → View trajectory / Display MD, then F4/F6/F7.
They assert on WHICH ROUTES ARE FETCHED (`page.route` recorder) and WHAT IS DRAWN (visible
instance counts, `.visible` walked up the parent chain — `count` alone reports beads as present
while they are hidden under the atoms), plus screenshots in `e2e/screenshots/repr-*.png`.

- **RED-verified:** reverting `getSimOverlayWillDriveHeavy` to the old oxDNA-only predicate makes
  both the trajectory and the live-display tests fail with `design heavy build leaked in:
  /api/design/atomistic` — the native flash, reproduced on demand.
- The ball-and-stick view of a trajectory frame shows the SAME conformation as the CG frame it
  replaced (screenshots 1 vs 2), which is the point: they are the simulated coordinates, not the
  design's equilibrium pose.
- **It needs the USER'S dev servers** (`frontend/playwright.livedev.config.js`, added for this).
  The default `playwright.config.js` boots a throwaway backend, and a cold single worker has to
  redo the archived job's MDAnalysis work — it blocks its own event loop doing so and the app just
  shows "reconnecting…". That config documents the read-only/pinned-`?doc` rules for using it.
  Session docs it creates under `workspace/.session/` are NOT auto-cleaned; remove them (and their
  `registry.json` entries) after a run.

**Two things the app run corrected in this session's own work:**
- A first draft of the R7 assertion read the prebuild's ordinary *first fill* (sequential chunks
  32-63, 64-95, …) as a refetch. It is not. The steady-state claim only means anything AFTER the
  prebuild reports ready — the test now waits for that. A conclusion drawn mid-prebuild is noise.
- Stalling the per-frame route to force a slow switch is the WRONG way to test the indicator: it
  supersedes the in-flight heavy build, which then correctly falls back to leaving the CG up.
  Throttle the one-shot `atomistic-model` topology fetch instead — that is the real slow step.

**Progress indicator, all four paths** (the toast owner is `atom_surface_display`'s heavy-status
listener — one owner, so the three sim controllers can't fight over the global persistent toast):
| Path | Signal |
|---|---|
| oxDNA / mdViz heavy rebuild | `_setHeavyBusy` → `{building, kind}` → "Loading atomistic model…" / "Computing surface…" |
| live MD rep-switch reload (NEW) | `md_panel._setSwitchBusy` → `kind:'atomistic'\|'cg'` → …/"Loading MD frame…" |
| no viz active | `_applyAtomisticMode`'s own persistent toast |
| overlay can't deliver the kind | `{unsupported:true}` → a warn toast naming F2-F4 |

`_setSwitchBusy` tracks the KIND, not just a boolean: switching again mid-wait (F7 then F4 before
the first reload lands) changes which text is correct, and a plain `building === _busy` guard
swallowed that and left "Loading atomistic model…" up over a CG reload.

**Also hardened (no observed failure, but the reasoning was wrong):** `prebuildHeavy` compared RAW
BYTE budgets derived from MemAvailable, so any wobble in free RAM discarded the whole grid bake and
every already-fetched frame with it. It now quantises the budget (`_BUDGET_QUANTUM` = 128 MB) and
re-grids only when the affordable frame COUNT actually changes.

**TWO BUGS FROM THE 2026-08-01 SWITCH AUDIT, both found by driving the real app.**

**1. "Weld pair turns itself on when I switch to atomistic."** It never did — the control was
persisted. `md_weld_controls` stored the checkbox in `localStorage['nadoc:md:weldPair']`, so a
stored `true` re-checked the box at boot and `setJob()` silently re-applied it to the next job
selected. The markers are drawn from inside the atomistic renderer's `applyPositionLerp`, so
nothing appeared while the scene was coarse-grained; they materialised at the moment the user
pressed F6/F7. Measured with the key set: at "trajectory on" `overlayVisible=true` with **0** drawn
meshes, and after F7 **3**, without the control ever being touched. With the key cleared, nothing
turns on at any step. **Fix: the layer is opt-in per session** — persistence removed, checkbox
keeps the HTML default. A stale key already in a browser is inert (nothing reads it). Within a
session it still follows a job change, which is correct: the user ticked it. The old
`remembers the checkbox state across a rebuild` test was REVERSED, not deleted, so nobody restores
the key thinking it was an oversight.

**2. "Play shows an hourglass and doesn't play" — two causes, one real bug.**
- **The real bug: the client raced itself into a 500.** `md_analysis_runner.run_analysis` starts
  by KILLING any in-flight analysis for the same `(job_id, kind)` — supersede, not queue — so the
  victim returns `RuntimeError("… worker died without a result")` → HTTP 500. `prebuildHeavy`'s
  chunk loop and `_applyHeavy`'s single-frame fetch legitimately want frames at the same moment,
  so the client was murdering its own prebuild mid-play. Reproduced with two curls: overlapping
  POSTs to `/md/jobs/{id}/frames-atomistic` → the earlier one 500s in **0.25 s**, while either
  alone succeeds in ~2.3 s (32-index batch and 1-index are both fine solo — it is not batch size).
  **Fix: `_coarseFrames` now serialises through one promise chain** (`_queueFrameFetch`), re-reading
  the bake and re-filtering the wanted cells INSIDE the queue — the bake object can be replaced by
  a re-grid while a fetch waits, and results written into the captured one would vanish.
  Superseding stays the backend's job for a genuinely new intent; it must not fire on self-racing.
- **The rest was honest work, reported badly.** `onBeforePlay` passed `() => {}` as the progress
  callback and threw the prebuild's progress away, so a 200-frame atomistic prebuild sat on a bare
  ⏳ with nothing moving. It now writes the same `preparing atoms N/M…` line the toggle's prebuild
  uses. With atoms already prepared, play starts in **<500 ms** and frames advance normally
  (measured 3→10→17→…). Scrubbing always worked because it fetches one cell, never racing itself.

Both verified against job `29c5b267380f`; no 500s or console errors remain in the play path.

**PLAY BUTTON NOW REPORTS THE PREPARE (2026-08-01).** Follow-up to the bug above, from the
right question: *"if I can scrub the whole trajectory in atomistic, what is play working on?"*

**Answer, measured:** scrubbing was not filling the cache — the BACKGROUND PREBUILD was, at the
same time, which is why the work looked already done. On a 200-frame job: 32 of 200 cells fetched
3 s after F7; +168 during ~25 s of scrubbing (the prebuild finishing concurrently); then play
fetched **0** and started in 1.16 s. Control: wait for the prebuild first, then scrub → scrubbing
fetches **0** cells. The asymmetry is real and not a bug — scrubbing needs only the one cell you
stop on (fetched on demand in ~2.3 s, and the prebuild fills nearest-the-playhead first, so you
rarely hit a gap), while playback at 8 fps needs every cell in hand or it stutters.

**What was wrong was the affordance, not the wait.** The button showed a ready ▶ throughout, so
the user pressed it expecting instant playback. Now `oxdna_trajectory_player` has
`setPreparing({done,total}|null)`: during a background prepare the button shows a `.nadoc-spinner`
loading circle, is `disabled`, and its tooltip reads *"Preparing all-atom frames (N/200 frames) —
playback needs the whole trajectory in memory"*. All four button states (playing / preparing-by-
click / preparing-in-background / idle) now render from ONE `_renderPlayBtn()`; the scattered
`playBtn.textContent = …` assignments are what let it advertise ▶ while its frames were still
downloading. `md_jobs_panel._prebuildTrajHeavy` wraps the whole prepare (memory plan + confirm
included) in `setPreparing(...)` / `finally setPreparing(null)`, and skips it entirely when
`repKind(getCurrentRepr()) === 'cg'` so a CG trajectory never flashes a spinner over a button that
is genuinely ready.

**oxDNA is deliberately untouched.** That panel has no background prebuild — it prepares only on
click (`onBeforePlay`), so ▶ is honest there and `setPreparing` is simply never called. It picks up
the same loading circle in place of the old ⏳ character, which is cosmetic.

Verified in the app: CG `{spinner:false}` → F7 `{spinner:true, disabled:true, title:"…(0/200
frames)…"}` → prepare done `{text:"▶", disabled:false}` → play starts in 1.56 s. Screenshots
`e2e/screenshots/playbtn-{preparing,ready}.png`. Pins: 7 tests in
`oxdna_trajectory_player.test.js` (`background prepare is visible on the play button`); the old
`⏳`-character assertion was updated to look for the spinner element.

**Not done (offered, not chosen):** starting playback once a RUNWAY ahead of the playhead is ready
instead of the whole trajectory. That would cut the wait rather than just report it, at the cost
of a stall-and-resume path for when playback outruns the fill.
