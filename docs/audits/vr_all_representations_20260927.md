# Complete native VR representation catalog — 2026-09-27

Previous VR loading/tour changes were committed and pushed as `0b3524ac` before
this implementation, as requested. The implementation below is subsequent work.

## Behavior

The right Visualization sidebar and desktop/native event paths now support all
11 desktop representation IDs: Hull Prism, Cylinders, Beads, Full, Surface,
VDW / Space-fill, Ball & Stick, Stick, mrDNA Coarse, mrDNA Fine, and oxDNA.
Color buttons unavailable for a representation are gray, using the desktop
color-support table (including fixed-color Hull/mrDNA).
The existing Debug → VR Tours & Tests → Right sidebar → Visualization entries
cover the complete catalog. The tour visits every directed pair in a continuous
Euler circuit, avoiding redundant source resets without reducing coverage.

Beads shares Full source geometry, excluding slabs/connectors. VDW shares
Ball & Stick source geometry with canonical element radii and hidden bonds.
Hull uses the desktop hull builder; Surface uses the default desktop coarse
surface builder, including smooth vertex normals. mrDNA/oxDNA reuse the desktop
input-preview builders. These are design representations, not a claim of parity
with every engine's simulation-playback overlay or every desktop surface option.
The headless preview adapter requires Node and installed frontend dependencies.

Native triangle and ellipsoid meshes use the existing lighting, shadow and
object-ID passes. oxDNA backbone connectors retain their taper. Picking respects
VDW radii, hidden primitives and triangle/ellipsoid ray intersections. Legacy
snapshots remain readable; missing representations are disabled. Scene v15 adds
V/U/N primitive annotations without changing existing W tool-ownership records.
Geometry/topology constants and saved designs are unchanged. `main.js` LOC Δ: −1.

## Validation

- Frontend: 547 files, 7,104 passed, one skipped.
- Browser: all 11 desktop selections reached native launch requests unchanged;
  Debug nested Visualization launch also passed. Native endpoints were intercepted
  for this browser contract test; live rendering is checked separately below.
- Smoke: all 23 cases passed using the default isolated test configuration. The
  standard `just smoke` attempt found port 5174 occupied; that process was left
  untouched and the same cases ran on ports 8002/5175. Global teardown removed six
  test artifacts and one project-history store; subsequent scan found none left.
- Native: 41 CTests passed, including real OpenGL object IDs, occlusion, triangle
  and ellipsoid shapes, ray selection, and the highest representation cache slot.
- Focused backend: 57 VR route tests, 13 scene-contract tests and two new geometry
  tests passed. The small geometry fixture covers natural/expanded identity
  parity, valid faces/normals, VDW radii, oxDNA taper and native snapshot loading.
- `just test-smart`: FAST, 9,298 passed, 92 skipped, one pre-existing failure:
  `tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`.
  80 seconds overall; zero per-test budget violators. No guard was changed.
- Additional focused tour/catalog/cache checks: 5 + 9 + 5 passed.
- `just lint` finds one unrelated F401 in `tests/test_cpd_shape_revision_v2.py`
  (unused Path import). VR files pass Ruff; unrelated concurrent work was left alone.

Repository deferral, verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

## Live observation and performance

Evidence root: `.development-artifacts/vr-all-representations/`.
Source: the retained current-document 24hb_0xT snapshot at
`.development-artifacts/vr-debug-tours/20260927-195016-046979dc/open-design.nadoc`,
SHA256 `c58e0031de49c6f02890867a2e6bb70af8b7eafb8ae2b847eca1391fcefc727f`.

The first `steady/` attempt was intentionally interrupted after visual inspection:
triangle bounds made the design too small and surfaces lacked desktop two-sided
normal handling. That evidence remains separate. Corrected `validated/` uses the
same geometry bytes, physical OpenXR submitted eyes, unchanged human-controller
profiles, left menu closed and right menu moved using its real grip frame.
Initial corrected coverage is 232,989/237,657 design pixels with 54/30 px gaps
from the menu. No headset pose or acceptance threshold was changed.

Final matrix: **440/440 passed**, all 110 directed pairs on each of the four
unchanged controller profiles. Desktop correspondence: **1.0** (required 0.95).
The minimum observed design coverage was 155,449 pixels per eye; no capture was
clipped or overlapped the menu. Per-representation CPU style-application medians
were 0.016–0.041 ms; maximum 23.691 ms (Surface). These are enqueue/application
measurements, not a claim of matching end-to-end GPU frame times. See
`matrix-summary.json` and `validated/result.json`.

First full-catalog export: 1,618,958,774 bytes, 111.58 s cold; native readiness
22.16 s. This includes substantially more geometry than the previous four-style
baseline (697 MB; native readiness approximately 10.6 s). Surface face-frame
construction and repeated owner/color lookups were then vectorized/cached:
**80.48 s cold export** (27.9% less), **23.63 s native readiness**, **104.29 s
cold end-to-end readiness**. The snapshots are byte-identical, SHA256
`2374556be35e8a541a2e00b30a1fd84b0ac5a3aded9ebbefefe0076fcaeef8a1`.

Cache reuse passed twice: the first checksum verification took **16.21 s** after
the long tour; the repeat with warm filesystem data took **0.70 s**. Artifacts
reside on the Archive drive via the repository's existing symlink. A component
probe measured fingerprinting at 0.06 s and warm full-file hashing at 0.65 s.
Do not equate a warm filesystem hit with the cold Archive-drive case. Native
loading is additional; the larger catalog is more expensive than the four-style
baseline. Export code/dependency edits intentionally invalidate the cache.

The final build's `final-colors/` cycle passed all 11 representations, 22 rendered
color-menu page checks and desktop correspondence 1.0. Both Visualization and
Representation colors are registered under Debug → VR Tours & Tests → Right
sidebar, and both snapshot the current document including unsaved edits.
[The review gallery](../../.development-artifacts/vr-all-representations/review.html)
provides final submitted-eye captures. All owned test
viewers exited; no temporary diagnostic override remains.

See `export-parity.json`, `export-warm-repeat.json`, `final-colors/export.json` and
`final-colors/loading.json`. Static style
metrics measure CPU preparation/submission, not end-to-end GPU latency.

Submitted-eye evidence does not prove physical headset panel scanout or subjective
comfort. Broad regression debt above and live simulation-playback combinations
remain separate from static representation switching coverage.
