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

**Host-RAM reclaim before NAMD spawn (2026-07-07):** `atomistic_cache.reclaim_cache_if_low(min_free_mb)`
drops the cached models (the largest discretionary host allocation, up to `_CACHE_MAX`
~1 GB models) when `md_vram.detect_host_ram_mb()` < floor. `namd_runner._free_host_ram_for_namd`
calls it (floor `_HOST_HEADROOM_FLOOR_MB=4096`) right before every NAMD segment/min spawn so
the run has headroom to pin GPU staging buffers — the fix for a host pinned-memory OOM
(`cudaHostAlloc`, [[water-shell-carve]] `FAILURE_HOST_OOM`). Roomy machine → free RAM stays
above floor → nothing dropped (no viewer thrash); only bites under real pressure. None RAM
reading → no-op (don't reclaim on a guess). Tests: `test_reclaim_cache_if_low_*`.
