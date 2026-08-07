---
name: md-live-model-cache
description: Live-MD WebSocket rebuilt the full atomistic model per load with no cache/single-flight → ~20 GB worker blow-up; fixed with a single-flight bounded model cache + frontend debounce
metadata:
  type: project
---

The FastAPI worker was observed at **~20 GB RSS on a 30 GB box (swapping)** while a
NAMD relaxation ran. Root cause was NOT the MD engine and NOT a slow leak.

**Diagnosis method (reusable):** `py-spy dump --pid <worker>` (needs sudo — ptrace
is restricted) showed **~20 threads simultaneously inside
`build_atomistic_model`**, every one launched from `_load_sync` in
[backend/api/ws.py](backend/api/ws.py) via `asyncio.to_thread`. RSS was flat (a
stuck backlog, not growing), all **anonymous/private-dirty** (live Python objects,
not mmap). Earlier `nvidia-smi`/`pgrep` "transient python" sightings were false —
they were our own monitor's `awk` matching the words python/gmx (`pgrep -f` self-match;
also caused `pkill -f gw.sh` to kill its own shell → exit 144).

**Root cause:** the live-MD viewer's `/ws/md-run` handler rebuilds the ENTIRE
~1 M-atom all-atom model (`build_atomistic_model` → scipy L-BFGS-B
`_minimize_backbone_bridge`, multi-second, multi-GB) on **every `load` message**.
No result cache, no concurrency guard, default 32-thread executor. Rapid re-opens
(`_openWebSocket` fires on repr changes / reconnects; the client closes the old
socket but `asyncio.to_thread` is NOT cancelled on disconnect, so the server build
keeps running) pile up ~20 concurrent builds → ~20 × ~1 GB. Also the source of the
worker's ~100 % CPU. (The `nxnode`/gnome-shell/firefox/VSCode GPU graphics clients
are a *separate* ~10-15 % ns/day dip on NAMD's GPU-resident kernel — unrelated.)

**Fix (shipped 2026-07-01):**
1. New [backend/core/atomistic_cache.py](backend/core/atomistic_cache.py) —
   `build_atomistic_model_cached(design)`: content-fingerprint (`sha256` of full
   `model_dump`, superset → never serves stale) keyed `OrderedDict` LRU
   (`_CACHE_MAX=2`) + **per-fingerprint single-flight lock** so N concurrent loads
   of the same design collapse to ONE build; the rest block and take the cached
   result. Build runs OUTSIDE the registry lock. `clear_atomistic_cache()`,
   `cache_size()` test hooks.
2. [ws.py](backend/api/ws.py) `_load_sync` swapped `build_atomistic_model` →
   `build_atomistic_model_cached` (one line). This is the real safety net —
   memory now bounded to `_CACHE_MAX` models regardless of client behaviour.
3. [frontend/src/ui/md_panel.js](frontend/src/ui/md_panel.js) `_openWebSocket`
   now **debounced 120 ms** (`_reopenTimer`) + skips redundant reopen when already
   connecting/open for the same `config|mode` (`_wsSig`); both teardown paths
   (`stopPrewarm`/`stopAndRestore`) cancel the pending timer. Reduces trigger rate.

**Tests:** [tests/test_atomistic_cache.py](tests/test_atomistic_cache.py) — 5 pass,
stubs `build_atomistic_model` with a counting/sleeping fake to assert repeat-load
builds-once, **concurrent single-flight (8 threads → 1 build)**, distinct designs
each build, bounded cache, fingerprint stable+sensitive. Frontend 1763 vitest pass.

**NOT verified in a live MD session** (needs a running trajectory + design in the
app); frontend debounce is logic-reviewed only. If re-touching: the highest-value
guard is the server single-flight — the frontend debounce is secondary.

Aksimentiev relax protocol itself is fine: default is fast mode (4 fs HMR +
GPUresident, ~16 ns/day for 1 M atoms), NOT 1 fs. 1 fs only for the first
strain-relief segment and for declash (extra_bases) designs. See
[[md-job-system]], [[md-panel-status]]. Stage length 4 × 4.8 ns is the real cost.

**Parsed-Universe cache + load progress/timeout — "Display never loads" (2026-07-16):**
The atomistic-model cache above fixed the DESIGN-model rebuild, but `_load_sync` still
re-parsed the **solvated MDAnalysis Universe** (the 100–200 MB, 1.3–1.4 M-atom PSF of a
24hb explicit-water run) on EVERY display open — ~8 s pure-Python parse, uncached. On the
archive drive (cold cache) that stretched to tens of seconds, and since the frontend spinner
clears ONLY on a `ready`/`error` WS frame with **no load timeout**, a slow parse read as an
eternal "loading" hang. Confirmed it's a SIZE problem, not the archive drive (drive stat 0.001s,
16% full) — a non-archived job this size hangs identically. Fixes in [ws.py](backend/api/ws.py):
- **Module-level Universe cache** (`_UNIVERSE_CACHE`, LRU cap 2, lock-guarded) keyed by FILE
  IDENTITY (`_file_identity` = path+mtime+size) of topology+trajectory. `_load_sync` reuses a
  cached parse → re-opens are instant. A growing DCD (live job) changes size/mtime → cache miss
  → fresh parse (live correctness kept). **Only cached when `n_atoms > _UNWRAP_MAX_ATOMS`** so a
  reused Universe never re-stacks `_try_unwrap`'s in-place transformation (small systems parse
  fast anyway). Evicted Universe's trajectory handle is closed. Single-user assumption: a cached
  Universe is shared across connections; the app never scrubs two displays at once.
- **Load timeout backstop** `asyncio.wait_for(..., _LOAD_TIMEOUT_S=240, env NADOC_MD_LOAD_TIMEOUT_S)`
  → an `error` frame (spinner clears + message) instead of an infinite spinner. The parse thread
  isn't cancellable, so it runs on and populates the cache → the user's retry is fast.
- **Progress note** `_preload_size_note` (cheap PSF `!NATOM` header read + file size) → a new
  `{type:"loading"}` WS frame BEFORE the blocking parse; md_panel.js `_handleMessage` turns it
  into `nadoc:md-display-state {state:'loading', message}` so the spinner shows "Parsing
  1,320,174-atom solvated topology (172 MB) — first open ~10–60 s, re-opens cached" instead of a
  bare spinner. Only fires for PSF > `_UNWRAP_MAX_ATOMS`.
- Tests: `tests/test_ws_helpers.py::TestUniverseCacheHelpers` (6 — file-identity mtime/size
  sensitivity, cache key, put/get/LRU-evict+close, PSF NATOM header read, size-note gating).
  Backend `just test-smart` green (5097; 3 unrelated pre-existing failures). Frontend 2864 vitest
  green. **NOT verified in a live app session** (needs a large archived MD job loaded; the
  frontend `loading` branch is logic-reviewed only).

**Host-RAM reclaim before NAMD spawn (2026-07-07):** `atomistic_cache.reclaim_cache_if_low(min_free_mb)`
drops the cached models (the largest discretionary host allocation, up to `_CACHE_MAX`
~1 GB models) when `md_vram.detect_host_ram_mb()` < floor. `namd_runner._free_host_ram_for_namd`
calls it (floor `_HOST_HEADROOM_FLOOR_MB=4096`) right before every NAMD segment/min spawn so
the run has headroom to pin GPU staging buffers — the fix for a host pinned-memory OOM
(`cudaHostAlloc`, [[water-shell-carve]] `FAILURE_HOST_OOM`). Roomy machine → free RAM stays
above floor → nothing dropped (no viewer thrash); only bites under real pressure. None RAM
reading → no-op (don't reclaim on a guess). Tests: `test_reclaim_cache_if_low_*`.

**Remote (Alpine) jobs reach this display path via a fetched snapshot, not a stream
(2026-08-07).** The `/ws/md-run` handler can only address LOCAL filesystem paths, and a running
cluster job's DCD is on the node and multi-GB (2.88 GB after 90 min on a 1.32M-atom system), so it
is never streamed. `backend/core/remote_live_frame.py` instead pulls one `.restart.coor` when the
user signs in and writes a **one-frame DCD** into `output/<seg>.dcd`; everything in this file —
the Universe cache, `_file_identity`, single-flight, the reclaim path — then applies unchanged,
because from here it is just another local DCD that changed size/mtime. See
[[project_alpine_cluster_submission]] for the traps (the marker that stops health running on a
single frame, and the `format="DCD"` / `resolve_topology` gotchas).
