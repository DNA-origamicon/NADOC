# P5 loading performance audit (2026-09-15) — supporting detail

[Topic head](../../project_md_viz_tools.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### P5 loading performance audit (2026-09-15)

Real GPU browser, P5 stride 20: about 3.17 s from selecting trajectory loading to actual
ball-and-stick frame advance, with advisory cold archive pages and empty derived topology cache.
250 selected frames preserve every extracted atom/base value; cold read + alignment (~10.7 s)
matches raw HDD reads (~10.9 s). See `docs/audits/24hb_p5_trajectory_performance_20260915.md`
and `scripts/benchmark_md_playback.py` for scope, research, reproduction, and buffering limits.

Full-buffer follow-up: P5 stride 20 reaches first playback in 3.13 s and buffers all 302
selected frames in 32.09 s on the advisory-cold HDD. Six distant cached scrubs take 115–135 ms
including browser rendering, with zero coordinate requests. See the audit follow-up section.

**Permanent Figure quality (2026-09-26):** `detail=chimerax` now includes
continuous-field extraction AND bounded local remeshing. `remeshed` is a compatible
alias; `continuous` remains an internal non-remeshed comparison. The temporary UI
checkbox was removed. Defaults: probe **0.06 nm**, surface opacity **1.0**.
Sampling remains world-aligned 0.05 nm, Gaussian sigma 0.0425 nm, halo tiles, four
Taubin iterations, then conforming refinement around >=60° turns with at most
0.01 nm local displacement. Native shells are per-strand; simulation shells retain
their existing fused grouping. Molecular coordinates/topology are unchanged.

**Surface progress:** `surface_progress_request.js` owns a token-scoped popup and
polls `/api/surface-progress/{request_id}` using frozen document headers. The pure
ASGI `SurfaceProgressMiddleware` binds a core ContextVar reporter copied into sync
worker threads. Tile and smoothing counters report actual completed work in the
CURRENT stage (not elapsed-time estimates); preparation, joining, remeshing, and
packing are explicitly indeterminate when no denominator is available. Labels
include the current strand/total. Requests and documents cannot overwrite one
another's progress; completion/failure cleans up frontend polling. The bounded
registry expires completed records after ten minutes and does not expire active
long computations. It stores no molecular data and no files.

**Lossless optimizations:** tiled vertex welding uses stable numeric lexicographic
ordering; remesh adjacency reuses one sorted edge ordering; native binary packing
retains typed arrays and uses vectorized palette lookup / compact ID indexing.
Matched-setting byte equality is tested and benchmarked. These do not reduce grid
resolution, smoothing quality, or triangle count. See
`docs/audits/surface_final_figure_20260926.md` for final measurements and validation.

**Historical surface quality/probe audits:** `surface_quality.py` and
`scripts.audit_surface_quality` provide opt-in adjacent-face turn metrics and
hotspot coordinates. The historical audit script originally compared Figure quality with remeshed;
older saved reports retain their original mode meanings. See
`docs/audits/surface_consistent_sampling_20260926.md` for the previous sampling
investigation: uniform sampling reduced mini_rect >60° edges 162→19 at .14 nm,
but increased them 58→158 at .24 nm. Closing-induced near-contacts, extraction,
and Taubin movement all contribute. More smoothing/polygons alone are not a
reliable fix. The old binary Figure baseline is no longer the UI preset.
