# Standard editor broadcasting — 2026-09-20

The user confirmed presenter perspective sharing and requested presenting directly
from the editor. Accepted multi-view behavior: share the active pane, not the full
layout. Help → Broadcast to presentation defaults off and independently selects
camera and visualization publication to an existing meeting.

Implementation boundaries:

- Local management credential authorizes a 15-second editor lease. It takes over
  the presenter seat, counts toward the four-participant cap, expires on loss of
  heartbeat, and rejects writes after Stop. Public guest routes cannot acquire it.
- Camera updates are coalesced with one update operation in flight, at most 4 Hz.
  Scene fingerprints observe versions/settings, not vertex-buffer hashes. Scene
  checks run at 1 Hz, wait for gestures/settings to settle, and export no more
  frequently than every 3 seconds. Export/upload duration and bytes are logged.
- Snapshots replace the room's scene and SHA-256 while preserving invite, password,
  cookies, expiry, and the guest's independent camera. Stale downloads are discarded;
  hashes are checked before replacing an existing scene. Jump/Follow stay opt-in.
- Different documents/reset events stop broadcasting before a private export can
  commit. Starting camera-only mode checks the native document hash against the
  package. No scientific topology, geometry generator, simulation, or workspace
  data is modified by broadcasting.
- Trusted section shaders/planes/caps round-trip. Gizmos are excluded. Sectioned
  packages require schema 2; legacy schema 1 remains readable. Multi-view uses the
  selected pane's actual scene, camera, and coloring. Unsupported shader pipelines
  fail explicitly. Semantic highlights and trajectory playback are still pending.
- Old active host processes are not restarted. Capability negotiation tells the
  user to end that meeting and start a new host/link when ready for the new protocol.

Validation already completed:

- Full frontend unit suite: 482 files / 6,711 tests passed. Final focused rerun
  after UI/section-version refinements: 14 files / 53 tests passed, including
  non-pickable stencil caps and stopping revision downloads when a guest privately
  opens a different file.
- Actual Help-menu browser flow passed (1.3m): existing links, guest join, editor
  takeover, Base coloring, section caps, active Full multi-view pane, unchanged
  guest URL and cookies with zero rejoin requests, Stop freezing further updates,
  and independent revocation. The final test explicitly reloads a revoked link.
- Five section WebGL browser tests passed, including exact pixel equality in the
  tested cap region after a prepared-scene round-trip, hatch/plane edits, and
  intersecting planes. This is rendering evidence for the tested fixtures, not
  real-GPU/WAN performance evidence.
- Node host, room, middleware, and editor-lease regressions: 11 passed.
- Isolated native Windows host: actual WSL transport successfully started an editor
  lease, replaced scene bytes/revision, and paused. Random loopback port, no Funnel
  changes; temporary host stopped and files removed in `finally`.
- Production build and lint passed; `main.js` LOC delta is 0.
- Final `just smoke`: 23 passed (1.9m), including app console-error and teardown gates.
- Backend selector chose FAST: 8,789 passed, 7 skipped, 7 existing failures due to
  the unavailable external photoproduct review archive. Pytest: 99.89s; guard: 114s.
  Aggregate backstop exceeded with zero per-test violators. Local triage under
  triage-slow-tests found no new heavy test from these JavaScript changes; largest
  individual test was 4.62s. No tests were relegated and no guard was weakened.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

Cleanup inventory: isolated Playwright ports 8001/5174, `__e2e__` designs and project
histories removed by global teardown, session autosave disabled, isolated control
file removed by `afterAll`, bridge key by global teardown. Section render fixtures
create no workspace artifacts. Native helper uses `/tmp/nadoc-editor-native-*`
with `finally` cleanup. Logs stay under `/tmp/nadoc-editor-*.log` for review.
Final inventory matched preflight exactly: workspace 147 entries, `.projects` 0,
`.session` 11, `playwright_tests` 57; isolated share/bridge credentials and native
helper scratch paths are absent. The existing public host remains running with
its older capability set; no live meeting was restarted for verification.

Outstanding acceptance: real GPU/WAN A/B and transient visualization-update stalls
on VoltronCoreArmV2 and cube_pore. Functional and software-rendered pixel tests do
not certify large-design FPS parity. Full-scene snapshots remain a temporary
transport; incremental updates are the next performance refinement.
