# Shared design edit updates

Previous representation/view-volume work was committed and pushed as `371918a7`
on `feature/standalone-viewer-presentations`. This follow-up remains uncommitted.

Native sharing watches immutable design, assembly, geometry and axis identities
in addition to display changes. Edits wait for stable identities and scene
structure across polling ticks. Structural checks omit transient GPU upload
counters: requiring those counters to settle stalled real overhang updates.
Exports superseded by another edit are discarded; expected export races retry
without presenting an error. Existing room/document/job isolation remains intact.

Multi-overlay now observes design changes, coalesces them, and serializes layer
rebuilds. It blocks exports while stale layers are pending, refreshes all layers,
recomputes separation, and preserves the presenter camera. Guests use the existing
revision-download path, which preserves their camera and validates package hashes.

Validation:
- Focused sharing/overlay/export tests: 27 passed, including superseded exports,
  independent camera state, and ongoing GPU upload-counter churn.
- Real browser test passes for overhang extrusion, free-end resize, and bundle
  extrusion on the same invitation. Checks final design source hash, increased
  rendered instance count, a changed package, and unchanged guest camera. Repeats
  extrusion in multi-overlay and verifies two refreshed guest layers.
- Full frontend run: 6,880 passed, 1 skipped; the known quantum-dot PNG import
  failure remains. Later counter-handling change has focused regression coverage.
- Production build and lint pass. `main.js` LOC delta: 0.
- Combined browser regression: all 4 passed (design edits, representation sharing,
  volume controls, and hull-aperture pixel/round-trip check).
- Final smoke run: 23 passed. Verified removal of test-owned workspace files and
  history, browser artifacts, and isolated bridge credentials.

Updates are complete prepared snapshots, not topology deltas or per-pointer-frame
streaming. Typical latency includes the one-second polling/settling interval plus
export, transfer and guest reconstruction. Large-design throughput and remote-device
appearance remain manual validation items; no public host was created during tests.
