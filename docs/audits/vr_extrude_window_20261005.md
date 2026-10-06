# VR extrusion painter and length controls — October 5, 2026

The painter has separate header, grid, legend and action rows inside its grip
rails, with the same cached frosted surface as other native menus. Gray double
rings show occupied cells; filled gold crosses preserve selection visibility
when the texture is reduced to the displayed tablet size.

Two identical wheels sit beside the pinned length readout in the main Extrude
panel. Coarse steps 7 bp for honeycomb and 8 bp for square; fine steps 1 bp.
Both follow the main panel and remain usable while the painter is closed or its
window is moved/resized. Wheel acquisition respects nearer panels and trackpad
focus. Semantic/radial tool activation now opens the same panel as Tools → Extrude.

Read-only `L` scene records carry occupied addresses and the selected lattice's
origin/basis in source scene nanometers. The model preview uses the commit source
coordinates, including imported origins, rigid cluster pivot/rotation/translation
and desktop launch-camera rotation. Painter movement, centering and zoom change
only the slice view. Occupancy refreshes with successful model refreshes.
Ambiguous independent frames sharing one plane retain the existing preflight
restriction; their cells are not silently merged.

Review artifacts are under
[`vr-extrude-window`](../../.development-artifacts/vr-extrude-window/):

- [Submitted-eye painter with the existing 1×8 square platform](../../.development-artifacts/vr-extrude-window/slice-view.png).
- [Committed model with six adjacent helices](../../.development-artifacts/vr-extrude-window/committed-model.png).
- [Production OpenGL panel rendering](../../.development-artifacts/vr-extrude-window/render-05/extrude-panels.png).

The new reusable workflow is **Debug → VR Tours & Tests → Tools · Authoring →
Extrude beside an existing 1x8 platform**. It checks occupied cells, painting one
and two rows away, both length wheels, preview coordinates, committed 2.25 nm
spacing and refreshed occupancy. Its normal full route also checks local volumes
and persistence; this task's focused `CONFIRM_ONLY` runs stop after the commit and
rendered-model assertions.

## Executed software checks

- The final-binary 1×8 source workflow passes with `steady_fast` and
  `steady_deliberate`, including actual native/browser commit, six adjacent cells,
  both wheel signs, source-relative 2.25 nm spacing and 14 refreshed occupied cells.
  `variable_fast` and `variable_deliberate` fail stable-cell acquisition before
  wheel/commit execution: the correctly refused clicks did not meet the unchanged
  stable-hover gate after three approaches. The fitted cell hit radius was 14.02 mm
  against 12 mm synthetic position jitter plus 2° orientation variation at 30 cm.
  Maximum pacing lag was 9/6 ms. See `source-matrix-summary.json`; these are
  sensitivity failures, not a four-profile source-workflow pass.
- A fresh `steady_fast` control probe passes before the final four-profile matrix
  in the same viewer session. Both steady profiles pass every check. All four
  wheel directions also pass with `variable_fast`; its paint/erase gestures hit
  additional cells. `variable_deliberate` similarly paints extra cells and
  overshoots upward wheel travel (coarse +42 vs +21 bp; fine +5 vs +3 bp), while
  both downward wheel movements match. Wheel acquisition/release, isolation from
  painting, submitted-eye path visibility and mirror agreement pass throughout.
  See `live-final/matrix/report.json` and its HTML report for the complete failures.
- Actual desktop visibility passes: 24,192 feature pixels, matching fraction 1.0.
  The retained image is the viewer client only (`live-final/desktop/desktop-client.png`),
  checked against the submitted-eye mirror rather than a separate scene render.
- Separate `variable_fast --paint-grid-zoom 1.35` observation: the real two-grip
  gesture realized 1.22042× zoom (14.02 → 17.112 mm cell hit radius) while preserving
  cells, window and model pose. Stable acquisition of cell `[1,1]` still failed
  after three approaches. This is not a replacement pass for the original condition.
  Its first attempt stopped before zoom because delivery was 330 ms late against
  the unchanged 150 ms deadline; one bounded retry produced the measured result.
- Seven native checks pass: sidebar grips, sidebar unit, interaction, Extrude panel,
  menu spacing, lattice context and production Extrude viewer rendering/input.
- Native viewer test verifies both wheel signs for both lattices, closed-painter
  availability, scrolling, occlusion/focus ownership, occupied-cell rejection,
  per-cell selected pixels, backdrop blur and an offscreen negative control.
- 118 focused backend tests pass. The coordinate matrix covers both lattices,
  all three planes, signed lengths, imported origins and explicit rotated placement.
- 64 focused workflow/probe tests pass through guarded `test-focused` runs.
  Cleanup is verified in `cleanup-and-tests.json`: no owned viewers, temporary
  workspaces, task socket/credential files or test-created user-workspace parts remain.
- `just lint` passes. `frontend/src/main.js` LOC delta: 0.
- `just test-smart`: `decision: FAST (fast suite only)`. Result: 9635 passed,
  93 skipped, one failure in the unchanged geometry test
  `tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`
  (exact floating-point array equality). Log retained in `backend/test-smart.log`.

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

## Retained failures and observation conditions

The old-binary baseline had a stale Move/Rotate panel overlapping the painter
after semantic tool switching. Native lifecycle cleanup now covers that route.
The first browser attempt spent its launch timeout compiling; compilation now
runs as preparation outside the unchanged browser launch gate. A subsequent
source test committed successfully but its review helper wrongly expected two
clusters; adjacent same-frame helices belong to one cluster, and the oracle was
corrected accordingly.

The initial contact-path visual check exposed depth occlusion behind the frosted
painter and between diagnostic trace layers. Only opt-in contact overlays disable
depth testing/writes. Production controller/UI depth behavior is retained.
Offscreen render attempts exposed cached selected-line minification, confirmed
with per-cell pixel checks and corrected with filled crosses of the same extent.
Failed attempts remain beside the passing evidence; thresholds, motion presets,
hit areas and molecular geometry were not relaxed to obtain a pass.

The submitted-eye and desktop evidence use the production renderer with simulated
controller input. They do not establish physical through-lens legibility or human
comfort; these remain recorded under MV-38.
