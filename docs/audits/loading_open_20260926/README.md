# Active visualization opportunities 6 and 7 — 2026-09-26

This batch implements trajectory scrub scheduling/compact-frame display and first-open atomistic construction from the [active-feature ranking](../active_visualization_20260925/README.md), plus GPU transfer optimizations.

## Implementation

- **Trajectory loading and scrubbing:** the renderer reads decoded compact Float64 MD coordinates directly, using a serial-to-instance offset table. It avoids clearing and populating a sparse serial-span coordinate array before each displayed frame. New pages with the same immutable serial ordering share offsets after a content check; only one mapping is retained. Topology rebuilds invalidate it. Matching topology-row order avoids building a serial map at first display. Reordered/sparse serials and weld-overlay lookups remain supported; incomplete topology coverage uses the existing expansion fallback.
- **Interactive requests:** queued scrubs superseded by a newer scrub resolve false before issuing a read. The active read may complete and populate the cache; existing display tokens prevent stale painting. Explicit preparation/playback consumers remain protected, even when sharing a scrub's page. Returning to a cached frame cancels obsolete queued scrubs. Existing exact-frame selection, page sizes, parallel startup reads, background fill and memory budgets remain in place.
- **First-open construction:** spheres write directly to their instance buffers. Bonds use one packed Float32 workspace with the same Three.js quaternion/composition arithmetic, avoiding one retained Matrix4 object per bond. Element ordering, sparse serial lookup, degenerate-bond filtering, materials, tessellation and picking proxies remain unchanged.
- **GPU transfers:** repaint compares the final Float32 colour/alpha values before marking each mesh dirty. Unchanged channels need no WebGL upload, including alpha during colour-only changes. Matrices and colour attributes use `DynamicDrawUsage` from creation. This is a driver hint, not a demonstrated GPU-compute speedup; [Three.js documents buffer usage and its first-upload restriction](https://threejs.org/docs/pages/BufferAttribute.html). Existing impostor shaders, physical/photo rendering and coordinate precision are unchanged.

## Paired CPU measurements

The inert `baseline_*.js.txt` fixtures preserve the pre-batch, already-optimized renderer and queue. Their hashes are in `baseline.sha256`; using Git HEAD alone would incorrectly include gains from earlier uncommitted optimization batches. Fixtures are read only, never imported by the production app. Shared helper dependencies retain the same matrix math.

Construction: 3 warmups, 11 alternating pairs, fresh renderer per sample. Frame updates: 10 warmups, 21 alternating pairs. Exact matrix/colour/alpha checks run outside timing. Fixtures have eight serial slots per recorded atom, representing sparse serial numbering; this ratio affects the compact-frame benefit.

| Operation | Scale / input | Before | After | Speedup |
|---|---|---:|---:|---:|
| First-open CPU construction | 150,000 atoms / object | 126.95 ms | 80.38 ms | 1.58× |
| First-open CPU construction | 150,000 atoms / columnar | 112.41 ms | 80.29 ms | 1.40× |
| Cached compact frame | 150,000 atoms / 1,200,000 serial slots | 15.96 ms | 10.05 ms | 1.59× |

The large compact fixture removes a **28.8 MB sparse coordinate scratch array**; the offset table still occupies memory. These timings exclude network/disk reads, shader compilation and GPU rendering, and are not end-to-end load time or FPS claims. Full results, including 30,000 atoms, are in [benchmark.json](benchmark.json).

A deterministic replay with one active read and six successive scrub destinations issues **7 page reads before, 2 after** (active page 0 and final page 48). Explicit non-scrub requests are separately tested and never cancelled.

## Reproduction

Large benchmarks require a user-opened test session:

```sh
NADOC_TEST_CONFIRM=1 scripts/test_guard.sh loading-open-benchmark 1 1 -- node frontend/scripts/benchmark-loading-open.mjs
just test-frontend
cd frontend && npx playwright test --config playwright.smoke.config.js loading_open_performance.spec.js
```

## Verification

- Final `just test-frontend`: **7,072 passed, 1 skipped, 543 files**, 82.69 s.
- Focused checks cover direct compact-frame routing and fallback, sparse/reordered
  serials, topology invalidation, consecutive page ordering, weld lookup parity,
  unchanged/changed GPU channels, queued cancellation, and protection of explicit
  frame consumers. The full suite initially hit a pre-existing 10 ms assumption
  in a shared-trajectory test awaiting asynchronous SHA-256; the test now waits
  for its observable next request. Production shared-trajectory behavior is unchanged.
- Isolated running-app Playwright: **1 passed, 41.6 s**. Real 6-helix, 21-bp model,
  **5,040 atoms**; the fixture remaps serials sparsely and orders the recorded frame
  differently to exercise direct mapping. Initial construction, moved compact
  frame, cluster colour/fade and repeated repaint all match original pixels and
  picking, in both tessellated-sphere and impostor modes: **8 paired states**.
- WebGL instrumentation counts actual uploads for the displayed atom/bond colour
  and alpha buffers. An unchanged repaint used **10 calls / 169,152 bytes before,
  0 calls / 0 bytes after**, for each sphere mode. Matrix attributes also retain
  their dynamic usage setting. This measures eliminated transfers, not GPU FPS.
- The browser reproduces the queued-read change **[0,8,16,24,32,40,48] → [0,48]**;
  final requested page 48 is applied. Frame-source timing is synthetic; no live
  simulation job or production trajectory disk benchmark was launched.
- No browser/shader errors. `git diff --check` passed. This batch changes frontend
  behavior only; backend suites were not repeated.

[Browser evidence](browser_verification.json) and [cleanup inventory](cleanup.json)
are retained. The exact `__e2e__loading-open` document/session/project paths use
failure-safe `afterEach` cleanup; the existing global teardown removes isolated
port credentials and the artifact reporter removes Playwright output. All paths
were absent after the run. Disposable `/tmp` sources/logs were removed; baseline
sources and concise results remain here so the measurements are reproducible.
