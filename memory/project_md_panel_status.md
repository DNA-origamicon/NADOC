---
name: MD panel — implementation status and algorithm details
description: What works, what the PBC pipeline does, known limits, and how to extend the trajectory for late frames
type: project
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
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
