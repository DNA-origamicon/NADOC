# 2026-09-17 — Loop 10: user authorized live-server testing; found and fixed the real bottleneck — supporting detail

[Topic head](../../project_voltroncorearm_visualization_remediation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### 2026-09-17 — Loop 10: user authorized live-server testing; found and fixed the real bottleneck

- User authorized driving the live server directly ("taking over the concurrent sessions
  work") after manual testing still showed >30 s. Ran real end-to-end reproductions
  (Playwright via Windows Chrome, `?doc=b3c48e612869489dbc6f06f1cfa374d7` — VoltronCoreArmV2's
  live doc — using only GET/blocked-mutation scripts, and separately a fresh isolated
  per-tab doc for the actual `openPartFromServer` click-through flow) — confirmed the report:
  ~36.7 s for the realistic open. Cleaned up the disposable per-tab doc's session +
  `.nadoc-projects` snapshot data (864 MB) afterward.
- Root cause A: `apply_measured_positioning` (`backend/core/measured_positioning.py`) placed
  every backbone/base bead in a Python loop calling `np.cross`/`np.dot`/`np.linalg.norm` on
  individual 3-vectors (38,408 calls on VoltronCoreArmV2). Vectorized into batched array ops.
  Verified **bit-identical** (max diff 0.0) against the original across all 15,214 real base
  pairs in both VoltronCoreArm and V2, plus the unused `groove_rad` branch (never called in
  production, but its own real-molecular-geometry-formula must still hold — checked
  separately). `measured_positioning.py` is not in `molecular-geometry-authorization.md`'s
  gated path list. 7.5 s → 1.9 s.
- Root cause B (deeper): `backend/core/geometry.py` IS in that gated list (hard stop —
  isolated candidate + A/B artifact before any production placement change). User explicitly
  authorized proceeding with the same bit-identical-proof rigor instead of the full Molecular
  Placement Audit workflow (that tooling is built for crossover-insert candidates, not a
  whole-helix vectorization). Found: `nucleotide_positions_arrays()` already had a fast
  vectorized path, but it fell back entirely to the scalar `nucleotide_positions()` loop for
  ANY helix with `loop_skips` — and 52/71 of VoltronCoreArmV2's helices have loop_skips (only
  ~3 entries each, but on 155-179 bp helices), so the "rare" fallback was actually the
  dominant path. Wrote `_nuc_arrays_loop_skip_fast()`: vectorizes the skip/loop index-and-
  offset bookkeeping but deliberately keeps `math.cos`/`math.sin` (not `np.cos`/`np.sin`) for
  every trig evaluation — `_strand_beads`' own docstring and LESSONS H15/H19 record that the
  two trig implementations can differ at the last ULP and the backbone-bridge solve can
  amplify that into 0.1-1.3 Å at a junction, and `test_the_scalar_and_array_bead_paths_agree`
  already documents this as an accepted, deliberate separation. Verified bit-identical (exact
  `np.array_equal`, not `allclose`) against 62 synthetic edge cases (skip/loop at start/
  middle/end, cancelling skip+loop, adjacent skips, out-of-range entries, all-but-one-skipped,
  both directions, both `compact_skips` settings, offset `bp_start` + tilted axis) and all 208
  real (helix × compact_skips) combinations across both production designs. New pinned test:
  `test_the_scalar_and_loop_skip_fast_paths_agree` in `test_geometry.py`. 1.9 s → 1.15 s
  (remaining cost is now dominated by deformation/cluster-transform resolution, not placement).
- Root cause C (payload size): `_design_response(..., full_feature_log=True)` — used
  unconditionally on every cold load (`GET /design`, `POST /design/load`, `POST
  /design/import`) — shipped every feature-log snapshot/diff body up front. Measured on
  VoltronCoreArmV2 (109-entry log): **42 MB vs 2.4 MB slim**. Per the user's direction ("make
  loadout snapshot load in background after geometry... speed up time to first usable
  assets"): those three routes now ship the slim response; a new read-only
  `GET /design/feature-log/full` backfills the real bodies. `client.js` triggers the backfill
  from both `_syncFromDesignResponse` (after its `getGeometry()` call) and `getDesign()`
  (restart recovery, cross-tab open — which had no merge/backfill path at all before this),
  gated on "no previous design in this tab" and delayed by the existing `whenOperationIdle()`
  (best-effort — its 2 s cap means a very slow geometry build can still see the tail of the
  backfill overlap it). Seek/undo/history replay were already confirmed server-authoritative
  (`routes_feature_log.py`'s `_seek_feature_log` never reads client-sent bodies), so the gap
  before backfill completes is never a correctness issue, only a slower first history-panel
  interaction. Updated two pinned `full_feature_log=True` cold-load tests in
  `test_feature_log_snapshot.py` to the new contract + added full-backfill assertions; fixed
  a third test (`test_bundle_continuation_validate.py`, 3 cases) whose before/after `GET
  /design` comparison broke on the now-stripped bodies (topology was never affected).
- Combined live-reproduction result (same Playwright harness, doc `b3c48e...`): **43 s → ~12
  s** (`/api/design` 2-4s→~170ms from the payload cut; geometry request itself down from 33s
  of mostly-queueing to ~5-6s of mostly-real-work). Run-to-run variance is real (~10-16s
  observed) — remaining cost is GIL contention between the geometry threadpool task and
  concurrent job-list polls (a fundamental CPython limitation: threadpooling doesn't
  parallelize CPU-bound work), plus `_emit_arrs`/`_segments_for_helix` (deformation/cluster-
  transform resolution) now being the largest remaining single costs. Both are outside this
  loop's scope — `_emit_arrs` is in `design_geometry.py`, also gated by
  `molecular-geometry-authorization.md`, and deformation.py is a separate subsystem.
- Verification: 62 synthetic + 208 real bit-identical loop-skip comparisons (see above); full
  `test_geometry.py`, `test_loop_skip.py`, `test_helical_site.py`, `test_measured_positioning.py`,
  `test_junction_balance.py`, `test_oxdna_relaxation.py`, `test_oxdna_live_session.py` (400
  tests) pass; `test_feature_log_snapshot.py`/`test_feature_log_clusters.py`/
  `test_feature_log_edit_core.py`/`test_assembly_feature_log_actions.py` (104 tests) pass;
  full frontend suite 446 files/6506 tests pass; `just test-smart` failure set byte-identical
  to the pre-loop baseline (all pre-existing local toolchain gaps, unrelated). Cleaned up all
  test-created session/project artifacts.
