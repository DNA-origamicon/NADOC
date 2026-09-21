# First prepared trajectory sharing slice — 2026-09-21

Implements short, prepared NAMD Full clips using the existing temporary HTTPS host.
This is a first functional slice, not 30 FPS or WAN performance acceptance.
No scientific coordinate algorithm or source simulation file is changed.

## Delivered behavior

- Help → Share link: explicit frame interval, sampling interval and 4/8/15/30
  samples/s presets; progress and cancellation; source frame restored afterward.
- Shared recording controls in the editor dialog and standalone presenter page.
  Guest orbit remains independent. Host controls read current authoritative state
  before pause/play, including after closing and reopening the dialog.
- One baseline prepared scene plus gzip absolute sparse numeric patches. Patches
  preserve exported values and can be applied in any order, updating existing
  attributes/matrices. No dependency chain or per-frame scene reconstruction.
- Authenticated, clip-hash-bound frame fetches; SHA-256 per compressed frame;
  validated scalar bounds; presenter-only timeline writes; local host credentials
  remain off the guest browser. Revoke and expiry stop further requests.
- Shared clock with sequence protection and periodic half-RTT correction. Each
  guest has one frame download in flight and predicts ahead from observed transfer
  time. Older samples are skipped, not queued. Hidden tabs cancel transfers;
  pause/seek cancel obsolete work. Paused transfers allow 120 seconds, playback
  transfers 30 seconds, so ordinary slow connections are not trapped by an
  unrealistically short request timeout.
- Optional Buffer clip before playback. Cache bounded to 32 MiB raw frame patches;
  host clips bounded to 128 MiB compressed in aggregate, 16 MiB/frame and 120 samples.
  Baseline scene memory/transfer and renderer resources are additional.
- Copyable NADOC_TRAJECTORY_PERF records explicitly measure sample application,
  not render FPS. Counts include completed payload bytes, skipped/applied samples,
  sampled waiting time, cache bytes, transfer duration, maximum apply duration,
  source-frame lag and approximate clock RTT. Elapsed rates include paused time.

## Scope and practical limits

Only main-view NAMD Full parts have the temporal source adapter in this slice.
Assembly and active multi-view playback need their own source/companion identity
and frame-readiness adapters; static active-pane broadcasting still works.
Atomistic/surface/water are rejected. Visible graphene/ions use existing companion
settling, but the actual browser fixture below exercises DNA only. Spatial detail
adaptation, interpolation, compact per-nucleotide/segment encoding and atomic
refinement on pause remain later work. Existing native MD Play is private; use
Play shared clip to control this prepared recording.

The chosen exact scene patch is larger than the compact molecular format proposed
in the feasibility assessment. One measured cube_pore patch was 1,113,284 compressed
bytes: approximately 71 Mbps at 8 uncached samples/s **per guest**, before overhead.
This first format is suitable for prebuffered short clips and reduced temporal
sampling, not a promise of smooth uncached full-rate playback over normal links.
For the first laptop trial, prepare 8–16 samples and buffer before playing. A clip
that exceeds the guest cache cannot be entirely prebuffered. Funnel still requires
separate host upload per guest; no cloud relay or third-party storage was added.
The 50–100 Mbps reported host upload does not by itself certify guest experience.

Clips live in bounded host memory for this initial implementation. Disk-backed
long recordings, guest-ready indicators, adaptive spatial detail, hardware A/B and
four-participant WAN acceptance remain planned. Older running hosts require an
explicit Stop hosting all links/new link after the current meeting; development
validation never restarts the user's live host or tunnel.

## Validation

- Full frontend suite at implementation checkpoint: 485 files, 6,722 tests passed.
- Final changed-module tests: 5 files, 19 tests passed (codec, capture cancellation,
  source isolation/no water, receiver skipping/cancellation/sequence, host UI).
- Node host/middleware suite: 11 passed, including guest/presenter authority,
  clip validation, revoke, and host request CLI's timeline route.
- Production build passed; existing large-chunk warning. Ruff lint and diff whitespace
  checks passed. main.js LOC delta: 0; only thin existing-init wiring changed.
- Backend fast check: 8,789 passed, 7 skipped, 7 failed. All seven failures reference
  the absent archived `tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`,
  outside this trajectory work. Fast-suite wall time 99 seconds exceeded the 90-second
  aggregate backstop; slow-test triage found zero per-test violations (largest 4.23 s),
  no new Python tests/fixtures, and existing mock-engine tests rather than an unstubbed
  production engine. No tests were arbitrarily reclassified or budgets raised.
  Full/slow suite is deferred by the existing user-opened test-session gate and
  tracked by `.nadoc-slow-pending`.

The isolated smoke gate passed: 23 tests. Source-frame restoration also has final
unit coverage for progressive-cache reload and private document changes during
that reload. The final build and changed-module tests passed after this guard was added.

### Actual browser exercise

`npx playwright test --config playwright.smoke.config.js trajectory_share.spec.js`
passed (one test, 2.2 minutes including startup/read-only fixture extraction).
The test extracts eight real cube_pore frames (DCD indices 0,100,…,700) from job
`796c568b5690` into a temporary cache, imports an in-memory test-named design in
an isolated backend, and drives the real Help dialog to prepare/publish the clip.
No simulation is launched. Synthetic API responses carry the extracted DNA data;
companion overlay loading is not exercised by this fixture.

The guest opens the emitted link, joins, renders the first and last samples, then
plays/pauses and seeks an uncached intermediate frame under CDP's **1 Mbps** each-way
limit and **200 ms** latency. The guest cookie is unchanged; only three frame
requests occur; no page errors. The uncached throttled frame completes in 13.79 s
(includes software-renderer/browser contention), with zero transfer errors and zero
sample lag after the paused frame applies. This verifies eventual exact inspection,
not smooth playback at 1 Mbps. Playback in this short test reaches an already cached
endpoint; bounded forward skipping during a slow in-flight download is independently
covered by the receiver unit test.

[First sample](trajectory_sharing_20260921/trajectory-first.png),
[last sample](trajectory_sharing_20260921/trajectory-last.png), and
[raw browser metrics](trajectory_sharing_20260921/browser-proof.json) are retained.
Both canvas images were inspected: the design is visible and its conformation changes.
Chromium used headless software graphics; **no hardware FPS inference** is justified.

The test first exposed a genuine slow-transfer timeout: an eight-second limit could
never finish a ~1.1 MB frame at 1 Mbps. The revised paused-transfer limit fixes this;
seek/pause still abort obsolete requests immediately. An earlier run also exceeded
its guest visibility timeout under software rendering. The final run isolates the
source renderer after loading to avoid rendering both large scenes concurrently.

All test-created design/assembly filenames use `__e2e__`; global teardown removes
parts and revision stores. The fixture cache uses TemporaryDirectory; host and :5174
control credentials have afterAll cleanup. Workspace, .projects, .session and
playwright_tests directory inventories matched the pre-run inventory after the
trajectory run. Only compact screenshots/JSON are retained; failed traces and
transient test-results outputs are disposable and removed at final cleanup.


Final cleanup: [inventory comparison](trajectory_sharing_20260921/cleanup.json)
shows no additions/removals in the recorded workspace directories; the trajectory's
`.nadoc-projects` store and all test-prefixed workspace parts are absent. Both isolated
:5174 control credentials are absent. Disposable Playwright outputs were removed.
The final `main.js` is 7,128 lines, unchanged in count for this slice.
