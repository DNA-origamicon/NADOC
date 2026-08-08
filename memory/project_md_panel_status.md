---
name: MD panel — implementation status and algorithm details
description: What works, what the PBC pipeline does, known limits, and how to extend the trajectory for late frames
type: project
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
## RunPod display pulls its own snapshots (2026-08-08)

The MD Display used to tell a RunPod user to do the work themselves — *"This run's
trajectory is on the pod, not on this computer. Fetch a live frame…"* — for a fetch the
panel was never wired to make: `shouldFetchLiveFrame` required `clusterState ===
'connected'` **and** Alpine-only `mdIsRemoteRunning`, and `POST /md/jobs/{id}/fetch-live-frame`
409'd anything without a Duo cluster session. So the instruction named a button that did
not exist for that target.

Now: **RunPod snapshots arrive on a timer, unprompted.**

* **`runpod_executor.open_pod_connection(job, client=…)`** — a read-only SSH channel to a
  job's live pod. ⚠️ Deliberately **not** `client.pod()` / `client.adopt()`: both DESTROY
  the pod in their `finally`, so either would kill the paid run it was peeking at. Uses
  `get_pod` (a plain read); the caller owns the connection and must close it. A 404 is
  reworded as "that pod no longer exists" — it is the ordinary end of every run.
* **The route branches on target.** Alpine keeps its Duo-gated manager; RunPod opens a
  per-errand connection. Same `remote_live_frame.fetch_live_frame` underneath — it takes
  any object with `sftp_get`, which is the conn duck-type paying off again.
* **Cadence: `LIVE_FRAME_REFRESH_MS = 120_000`**, matched to what the pod actually
  produces (NAMD rewrites `restart.coor` every `restartfreq`, minutes apart). The backend
  keeps its own 60 s floor (`remote_live_frame.MIN_REFETCH_INTERVAL_S`). A 5 s tick moves
  the countdown label; only `liveFrameCountdown` decides when to spend a fetch.
* **`_liveFrameAt` is stamped on FAILURE too.** A pod with no checkpoint yet answers
  "not ok" every time; without the stamp the countdown sits at due and re-pulls ~32 MB
  every tick.
* **`_liveFrameTried` is Alpine-only now.** That one-shot set exists because Duo means one
  chance per session; a pod is key-based, so it must retry.
* **The ⟳ button** (`#md-jobs-live-frame-refresh`) shows only for `mdIsPodRunning` + display
  on, and passes `force: true` to bypass the 60 s floor — the user asked explicitly.
* **`runpodConnected(preflight)`** (new, `runpod_status.js`) is narrower than
  `runpodCanLaunch`: reaching an existing pod needs only the API session, not the volume /
  SSH-key / stock / sizing gates that renting a NEW GPU needs.

**VERIFIED against the live 2hb_1xT run** (job `7d5937e569c6`, pod `cw4i37gthl10dw`,
2026-08-08): frame on screen 6.1 s after toggling Display MD, ⟳ re-fetched in ~5 s, the
2-minute auto-refresh fired, zero console errors. `frontend/e2e/md_runpod_live_frame.spec.js`
+ `e2e/logs/md_runpod_live_frame.png`. Getting there took two real bugs:

### Bug 1 — `job.json` has two writers, and the loser was `live_frame`

The fetch route loaded its own `MdJob`, set `live_frame`, saved. `runpod_executor
._supervise_run` holds a SEPARATE in-memory job and re-saves the whole record every 30 s
poll, reverting the field. The next fetch then saw a DCD it no longer recognised as a
stand-in and refused to touch it — `{"ok": true, "skipped": "real trajectory already
local"}` **forever**, while reporting success. The display froze on its first snapshot.

Fix: the marker moved to a **sidecar** `output/<seg>.dcd.live.json` — one writer, and it
describes the FILE rather than living in a record someone else owns.
`remote_live_frame.{marker_path,read_marker}`; `is_live_stand_in`/`clear_live_frame` take an
optional `package_dir` and prefer the sidecar. `job.live_frame` is still written (display
payload) but is no longer the authority.

⚠️ **Generalise this.** Any field a ROUTE writes on a job that a supervisor is also running
will be reverted within a poll. Check for this before adding another.

### Bug 2 — the snapshot had no unit cell, so the display refused it

A NAMD `.coor` (NAMDBIN) is coordinates only, so the one-frame DCD carried a **zeroed
box**. `ws._try_unwrap` registers MDAnalysis' `unwrap` for anything under
`_UNWRAP_MAX_ATOMS` (200k); it raises *"No box information available"* on the first frame
access, which happens inside `_load_sync` — so the load aborted, `universe` stayed `None`,
and every poll answered *"No trajectory loaded."* This affected **Alpine too**, for every
system under 200k atoms, for as long as the live-frame feature has existed.

Fix: fetch `output/<seg>.restart.xsc` alongside the `.coor` and set `universe.dimensions`
from it (`parse_xsc_dimensions`, pure + tested incl. triclinic). The `.xsc` is rewritten
with the `.coor`, so it is the box AT THAT STEP — which matters under NPT. Measured on
2hb_1xT: 59.18 × 81.31 × 127.50 Å, 90/90/90.

### The troubleshooting tool

`frontend/e2e/helpers/md_display_log.js` — `attachMdDisplayLog(page)` records the status
line (+ spinner), the readiness dot, the ⟳ state, `nadoc:md-display-state` events and the
console on ONE timeline, change-triggered, to `.jsonl` + a readable `.txt`. Attach before
`page.goto` (the event hook is an init script). **`state: 'frame'` is the only definitive
"something reached the scene"** — the status line merely echoes it, and both bugs above
presented as a confident-looking status line above an empty viewport. Logs are gitignored.

Still unmeasured: whether a ~32 MB SFTP every 2 min competes with a much larger run
(2hb_1xT is only 62,677 atoms), and whether `active_segment_name` resolves during the
relax ladder rather than production.

## The readiness dot described the PREVIOUS job (fixed 2026-08-08)

User report: "if I last launched a RunPod, then click on an Alpine job, the MD Display will
have a RunPod related message until it errors out." Three independent causes, all in the
same handful of lines, and each sufficient on its own:

1. **`mdReadinessIndicator` hardcoded `'on the pod'` for EVERY remote target.** The backend
   has always worded its own `not_ready_reason` per target (`md_display_status`: "the pod"
   vs "the cluster") — the dot, which is what you read first, did not. It now takes
   `executionTarget` and reads `on the pod` / `on the cluster` / `not local`. That last
   fallback is deliberate: naming a target we are not sure of is how this bug read.
2. **`_selectJob` cleared `_displayMeta` but never reset the dot.** The state, the tooltip
   AND the label all survived the selection change, so the previous job's answer stayed on
   screen for the whole round trip. New `_resetDisplayIndicator()`. It clears the LABEL as
   well as visibility+tooltip: `_setDisplayIndicator` only writes the label inside
   `if (spec.show)`, so hiding alone leaves the old words in the DOM — invisible, but one
   `display:''` away from being the wrong caption. The live spec caught exactly that as a
   residual leak at t=0 after the first two fixes were in.
3. **Both display fetches `await`ed without re-checking the selection.**
   `_refreshMdPrewarm` captured `job` before its await and `_fetchDisplayMeta` wrote
   `_displayMeta` (and re-rendered the production controls) unconditionally after its own —
   so a slow answer for the job you just left painted over the one you just picked. Both now
   go through `_stillSelected(jobId)`. `_fetchDisplayMeta` still RETURNS the value, so a
   caller that asked about a specific job explicitly gets its answer; only the shared state
   is guarded.

`_setDisplayIndicator` gained a third `jobId` arg (defaulting to the selection) purely so the
wording is resolved from the job the state is ABOUT — the state and the noun can never come
from different runs.

**Verified in-app** (`frontend/e2e/md_display_source_switch.spec.js`, read-only). The live
server could not produce the failing state — every NAMD job on the fixture design is
currently `ready` — so the spec STUBS the two display answers: the RunPod job answers
`remote` instantly, the Alpine one answers after 3.5 s. It asserts `podStateReached` first,
so a green run cannot mean "the leaky state never happened", then samples the dot every
500 ms for 7 s and requires that no sample mentions the pod. Result: pod → `on the pod`,
Alpine → `on the cluster`, 0 leaked samples, 0 console errors.

Not investigated: whether the trailing "until it errors out" is fully explained by cause 3
(the late RunPod answer resolving to `error` over the new selection) or whether the 30 s
`_MD_WARMING_TIMEOUT_MS` also fires on large systems. Measured load for a 1.03 M-atom system
is ~9 s (below), so the timeout is probably not implicated — but it was not measured for the
1.32 M-atom `24hb_0xT` run this was reported against.

## What is built and working

- **`backend/core/md_metrics.py`** — `scan_run_dir`, `parse_log_metrics`, `count_frames`
- **`POST /api/md/load`** in `crud.py` — validates topology/XTC, returns frame count + metrics
- **`/ws/md-run`** WebSocket in `ws.py` — `load`, `seek`, `get_latest` actions
- **`frontend/src/ui/md_panel.js`** — full panel: load, scrubber, play/pause/loop/live, speed, stride, repr, opacity, displacement amp slider
- **`frontend/src/scene/md_overlay.js`** — InstancedMesh beads-only overlay
- **`frontend/index.html`** — `#md-panel` section wired up
- **Frame application** (`applyFemPositions` in `helix_renderer.js`) — NADOC full mode

## PBC correction pipeline (in `_seek_sync`)

Each frame goes through four steps:

**Step 1 — Sequential nearest-image** (`_unwrap_min_image`): walks p_order, applies nearest-image between consecutive atoms. Detects strand boundaries by > 1.0 nm raw distance — does NOT correct those. Fixes all within-strand PBC splits.

**Step 2 — Hybrid PBC correction**:
- Compute `_c_box = np.median(p_box[rigid_mask])` — **median** of rigid atoms (dsDNA, bp≥0), NOT mean. Median is robust when sequential unwrap mislays a minority of atoms at late frames (a biased mean centroid caused 22 Å RMSD spikes at frame 700 until this was fixed).
- `_T_dyn = eq_centroid - _c_box` — dynamic centroid offset (not load-time T, which goes stale after tens of nm of translational drift)
- Rigid atoms (bp≥0): per-atom nearest-image to design equilibrium position in box frame
- ssDNA atoms (bp<0): keep sequential-unwrap position + T_dyn (don't snap to design eq — their large thermal fluctuations cause wrong-image snapping)

**Step 3 — Kabsch rotation**: SVD-based rigid-body alignment to design equilibrium using only rigid atoms. Stores `R_prev` and `prev_frame_idx` in `_ctx`. For sequential playback (|N-N_prev| ≤ 3), detects rotation jumps > 60° and falls back to inlier-only Kabsch.

**Step 4 — Base normals**: rotates P→C1' intra-residue vectors by R_align for slab orientation.

## Performance on 10hb nominal run

- `view_whole.xtc` (0–54.6 ns, 547 frames): RMSD_rigid = 7–9 Å throughout ✓
- `prod_best.part0003.xtc` (3.4–78.2 ns, 749 frames):
  - Frames 0–639 (0–64 ns): RMSD_rigid = 7–13 Å ✓
  - Frames 640–748 (64–78 ns): RMSD_rigid = 10–16 Å (higher due to ~90° rotational diffusion)
  - max_delta capped at ~83 Å (down from 110 Å before any fixes)

## PBC quality check at load time

`_load_sync` runs two checks and populates `load_warnings`:
1. If `view_whole.xtc` exists in the run dir but isn't the loaded XTC → warn
2. Counts atoms relocated > 3 Å by sequential unwrap at the mid-trajectory frame:
   - `view_whole.xtc`: 0 relocated (trjconv-preprocessed)
   - `prod_best.part0003.xtc`: 0–307 relocated depending on frame
   - > 5 relocated → warning with `gmx trjconv -pbc whole` command

Warnings propagate to frontend via `"warnings"` field in the `"ready"` WebSocket message, displayed as yellow log lines in the MD panel.

## How to extend view_whole.xtc for late frames (> 54.6 ns)

```bash
# Concatenate and re-process the full production trajectory
gmx trjcat -f prod_best.part0002.xtc prod_best.part0003.xtc -o prod_cat.xtc
gmx trjconv -f prod_cat.xtc -s em.tpr -pbc whole -o view_whole.xtc
```

## Live mode (updated 2026-07-01)

`get_latest` for NAMD CG modes (`nadoc`/`beads`) now uses an **O(1) `dcd_fast` byte-seek** of the last DCD record (`backend/core/dcd_fast.py`) — it does NOT rebuild the Universe or `load_new` per poll. GROMACS/XTC and `ballstick` still fall back to `Universe.load_new`. The DCD fast path is now covered end-to-end by `tests/test_ws_helpers.py::test_md_run_ws_dcd_*` (synthetic CHARMM-DCD fixture `namd_dcd_fixture`) AND was validated read-only against the real running 1.03 M-atom sim (`3x6x200_test_02…k0p1_p100.dcd`): parses, O(1) last-frame seek returns finite coords, `istart=9600` → `first_ps=38.4 ps` (continuation segments start mid-time — `dcd_fast.first_ps` now carries this; previously frame-0 time was reported as 0).

**Stale-Universe scrub fix:** the live fast path advances `_ctx["n_frames"]` past what the MDAnalysis Universe indexed at open time. A `seek` into that newer range now lazily `load_new`s (`_seek_growing_sync` in `ws.py`) instead of raising IndexError → blank scene. Frontend grows `scrubber.max` from `msg.n_frames`. Test: `test_md_run_ws_dcd_seek_discovers_frames_appended_after_load`.

**Numerical alignment pin:** `test_md_run_ws_dcd_alignment_matches_design_eq` pins the unwrap→dynamic-T→Kabsch pipeline (frame-0 = design geometry → rigid RMSD < 0.5 Å). Per-frame `[ws seek]` diagnostics are gated by `NADOC_MD_SEEK_QUIET=1` (default: emit).

**Still not exercised in a live browser session:** the frontend controller wiring (`decideReload` wait-in-flight branch, `nextLivePollAction` timeout tick) — pure logic is unit-tested (`md_display_state.test.js`, 24 tests) but the stateful DOM/WS wiring in `md_panel.js` has no live-app pass.

## Toggle latency: cost breakdown + prewarm-on-open (2026-07-01)

Measured against the real 3x6x200 sim (143 MB HMR-PSF, 77 MB PDB, 1.03 M atoms, 7229 DNA P-atoms). **The frame is cheap; the session setup is not.**
- Per-frame (nadoc/beads, warm): `dcd_fast.read_frame` last frame ≈ 10 ms + `_unwrap_min_image` ≈ 0.4 ms (was 42 ms — vectorised, see below) + trivial Kabsch ≈ **~55 ms + JSON/WS ≈ ~85 ms**. Any live interval is effectively free.
- One-time `load` (per WS `load` msg): **`mda.Universe(PSF)` parse ≈ 4.3 s (NOT cached — rebuilt every load)** + `build_atomistic_model` ≈ 5.7 s (cached, `atomistic_cache.py`, cold on first load/restart) + C1′ loop 0.44 s + PDB walk 0.16 s ⇒ **~5 s warm-model / ~11 s cold-model**.
- Ballstick per-frame is far heavier (reads all heavy atoms + Python residue-reconstruction loop) — keep nadoc/beads as the at-the-ready default.

**Toggle-off must NOT re-warm (2026-07-01).** Toggling Display MD off used to call the controller's `stopAndRestore` (which CLOSES the socket + clears the cached frame), then `_startMdPrewarm()` FORCE-reloaded → the prewarm re-parsed the 143 MB PSF → indicator stuck at "warming…" ~5-10 s even though the latest frame was in hand. Fix: new controller method `stopDisplayKeepWarm()` reverts the scene to native but KEEPS `_ws` + `_lastFrameMsg` warm (returns whether a socket was kept); `_stopMdDisplay` uses it, sets the indicator 'ready' immediately, seeds `_prewarmKey` with the just-used display key, and calls `_startMdPrewarm(false)` (non-forced) so `decideReload` returns 'reuse-open' (no reload, no 'loading' event). Also fixed a race: a stale prewarm refresh whose `_fetchDisplayMeta` await resolved AFTER a quick off→on re-toggle would clobber `_displayVisible` back to false and suppress the live stream — `_refreshMdPrewarm` now re-checks `displayToggle.checked` after the await and bails. Re-toggle reuses the warm socket (cached frame reapplies instantly; no PSF re-parse). Validated by `e2e/md_display_toggle_rewarm.spec.js` (on→off→on): indicator stays 'ready' over 10 s after off, zero 'loading' states fire, re-toggle streams a frame in ~6 s with sequence `ready→ready→frame` (no 'loading').

**Option 1 (prewarm-on-design-open), `md_jobs_panel.js`:** prewarm now warms the display socket (PSF parse + model build) in the BACKGROUND as soon as a design with a loadable MD job is open, independent of the active tab, so toggling Display MD paints instantly. Changes: `_refreshMdPrewarm` no longer gated on `_isDynamicsTabVisible()`; a `nadoc:design-changed` listener `await _fetchJobs()` then `_startMdPrewarm()`; leaving the Dynamics tab stops the DISPLAY but keeps prewarm warm (spans tabs); `_stopMdDisplay` resumes prewarm unconditionally; no-job branch releases the socket (keeps the re-check timer); panel-collapse calls `_stopMdPrewarm` (hard teardown). Self-gating: no ready job → no socket opened. **NOT exercised in a live browser session** (stateful UI wiring; full vitest 1840 green but doesn't cover md_jobs_panel event wiring). Pre-existing caveat unchanged: prewarm/display map the trajectory onto whatever design is currently open — design↔job correspondence is not checked.

## Toggle readiness indicator + the mda_unwrap load bomb (2026-07-01)

**Indicator:** a readiness dot sits next to the Display-MD toggle (`#md-jobs-display-indicator` in index.html). Driven by `mdReadinessIndicator(state)` (pure, in `md_display_state.js`, unit-tested) off the `nadoc:md-display-state` events — REGARDLESS of toggle state, so it reflects the background prewarm too: warming (amber) → ready (green) → error (red); hidden when no job. Controller re-emits `ready` on the prewarm reuse-open path (no load event fires otherwise). **NOT verified in a live browser session** (stateful DOM wiring).

**KEYSTONE FIX — `_try_unwrap` mda_unwrap hang.** Writing the readiness test exposed the REAL reason the 3x6x200 toggle "took time to load": `ws._try_unwrap` added MDAnalysis' `mda_unwrap` make-whole transformation for any PSF (has bonds), and applying it to the **1.03 M-atom solvated system walks the bond graph on every frame access → ran for MINUTES** (measured >250 s, never finished; `u.bonds` build alone 4.2 s). We only display DNA and `_seek_sync` already unwraps the displayed atoms per-frame in-house (which is exactly why the GRO path works with NO make-whole), so `_try_unwrap` now **skips the transformation above `_UNWRAP_MAX_ATOMS = 200_000`** (in ws.py). Result: **load minutes → ~9 s** (model build 4.5 s + PSF parse 4.6 s). Small validated systems keep the transformation.

**Measured real-job load (3x6x200, cold):** model build 4.5 s + PSF parse 4.6 s ≈ **9.2 s** one-time (prewarm hides it); warm `dcd_fast` last-frame read **7 ms**. Pinned by `tests/test_md_display_ready_live.py` — env-gated (skips unless the job files exist) AND xdist-gated (timing only meaningful serially; `just test` skips it, run the file directly). Registered slow in conftest.

**FIXED 2026-07-01 — psfgen segid keying (Display MD works end-to-end).** CHARMM psfgen re-segments DNA into one segid per strand (`D000, D001, …`) and collapses NADOC's multi-char chain ids (`A, AA, AB, …`) into the reference PDB's 1-char chainID field → `build_p_pdb_order`'s `(chainID, resSeq)` key collided across strands, mapping only 6758 of 7229 trajectory DNA-P atoms → `_extract_universe` errored. **Fix:** for NAMD, build `p_order` from the PSF's own **segids** via a `segid→chain_id` table read from the package's `charge_audit.json` (`load_segid_chain_map`), mapping each trajectory P atom's `(segid→chain_id, resid)` → `chain_map` in trajectory-atom order (`build_p_order_from_universe`; both in `atomistic_to_nadoc.py`). `ws._load_sync` now opens the Universe first, prefers the segid map for NAMD, and **falls back to `build_p_pdb_order`** when there's no charge_audit / the map is incomplete (keeps small-system + synthetic-fixture paths working). Validated end-to-end against the running job: **all 7229 P mapped, rigid RMSD-to-design 8.5 Å** (a scrambled mapping is >50 Å), load ~14 s, warm frame ~35 ms. Tests: `test_atomistic_to_nadoc.py::TestSegidChainMap` + `TestBuildPOrderFromUniverse` (fast/CI); `test_md_display_ready_live.py` (real-job e2e correctness+timing, env/xdist-gated). 5′-terminal P per strand is stripped by psfgen (7306 design P → 7229) — handled naturally by mapping from the trajectory's actual P atoms. **Not clicked through in a live browser** — validated at the data/geometry level; the render path (`applyFemPositions`) is the same one the 10hb system already uses.

**Option 4 (vectorised `_unwrap_min_image`), `atomistic_to_nadoc.py`:** the sequential per-atom loop is a segmented cumulative sum (the box-multiple shift cancels out of the min-image rounding, so each corrected step = min-image of the RAW consecutive diff, independent of prior corrections; segments reset at strand boundaries where the step > `_P_BACKBONE_MAX_NM`). **42 ms → 0.39 ms (~107×)** for 7229 P-atoms. Validated bit-for-bit against the retained loop oracle (`test_atomistic_to_nadoc.py::TestUnwrapMinImage`, incl. multi-boundary + PBC wraps + non-periodic axis + short arrays).

## Variable naming trap in ws.py `_seek_sync`

`_load_sync` stores eq positions in the result dict as `"eq_positions"`.  
`_seek_sync` reads it as `eq_pos = _ctx.get("eq_positions")`.  
Inside `_seek_sync`, always use `eq_pos` — NOT `eq_positions` (which doesn't exist in that scope and raises NameError). This was the bug causing WebSocket errors after the inlier Kabsch was added.
