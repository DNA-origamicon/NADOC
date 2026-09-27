# Temporary continuous-field surface comparison

The completed adjustable-probe and focused-test-policy changes were committed and
pushed first, as requested: `87426b29` on `feature/standalone-viewer-presentations`.
The continuous-field experiment is a subsequent, separate working-tree change.

The separate **Continuous field (temporary)** checkbox selects `detail=continuous`.
It is mutually exclusive with Figure quality and shares the atomic preset's probe
radius (initially 0.14 nm). Selecting Figure quality restores its unchanged algorithm;
turning the experimental option off selects standard. Native and simulated surfaces
both support it. `main.js` LOC delta: 0.

The renderer already computes smooth shared-vertex normals, including before
splitting crisp color zones. This experiment targets the binary voxel boundary:
`surface_field.py` filters the closed occupancy using a separable float32 Gaussian
(sigma 0.85 voxels, truncate 3), then extracts its 0.5 isosurface. It retains the
existing radii, probe closing, adaptive grid, strand grouping, and four Taubin
iterations. At the target 0.05 nm spacing, sigma is 0.0425 nm. This is filtered
occupancy, not an analytical SES or Gaussian atom-density envelope. The smallest
features may soften; no claim is made that every visible crease has the same cause.

On a unit sphere sampled at 0.05 nm, radial RMSE falls from 0.0102108 to 0.0053663 nm
with 14,984 versus 14,936 triangles. This isolates sampling error reduction from
polygon-count increases. Native mesh identity/ownership and simulation parameter
routing are covered by three focused backend checks, all passing.

Review images are retained outside the user workspace in
`.development-artifacts/surface-continuous-comparison/`: `chimerax.png` and
`continuous.png`, same 6-helix/12-bp design, camera, lighting, and probe. Disposable
browser documents, session/project data, reports, and credentials are cleaned.

Frontend regression: 543 files, 7,077 passed, one skipped. Initial backend FAST
selection: 9,263 passed, 15 skipped, eight known baseline failures (seven
photoproduct review, one CPD snapshot). Full-suite debt remains deferred separately.
The initial overlapping frontend/backend/browser runs saturated the machine
(load average 38), inflated ten existing tests above the timing threshold, and
caused a browser timeout. That browser run was stopped and its artifacts cleaned;
verification was then serialized. No tests were reclassified on those timings.

Isolated browser/app validation: **24 passed in 3.1 minutes**, with no page or
shader errors. The native comparison returns 6,352,622 bytes in Figure quality and
6,332,318 bytes in continuous mode; switching back restores identical mesh bytes
and rendered pixel hash (`3296609982`). The continuous rendered hash is
`2754846697`. Both screenshots were inspected. All disposable document, project,
session, report, and credential paths were confirmed absent after teardown.

Final isolated FAST rerun: **9,263 passed, 15 skipped, the same eight baseline
failures, 99.02 seconds; zero per-test timing violators**. All ten inflated
per-test flags disappeared without changing tests or budgets. The aggregate
101-second guard time still exceeds its 90-second backstop, consistent with the
existing suite size; no tests were relegated for cumulative runtime. Lint and
`git diff --check` passed.
