# Guest visualization feedback — 2026-09-23

Retained screenshots document the real editor → isolated local sharing host →
production guest viewer flow. `frontend/e2e/guest_visualizations.spec.js` uses
synthetic nanopore trajectory HTTP responses; it launches no simulation.

- `loading.png`: the guest receives the presenter's measured 7% progress.
- `ion-paths.png`: thick species-colored nanopore paths; the test also changes width.
- `vector-field.png`: vector arrows replace the paths through normal editor controls.
- `ended.png`: End clears the guest viewer and displays Presentation ended.

The browser test passed with no console errors after the expected first-visit
authentication probe. It verifies exported line settings and vector nodes, visible
render changes, loading dismissal, disabled ended-view controls, and SSE teardown.
The initial test fixture omitted the job-detail response; that fixture was corrected.

Validation: 6,773 frontend tests across 496 files passed; targeted host/bridge
protocol tests passed, including progress validation and the terminal SSE event.
Production build and lint passed. Unit tests additionally compare path coordinates,
colors, visibility counts, and vector instance transforms/colors after round-trip.
All 23 isolated smoke tests passed, including assembly exit and session teardown.

`just test-smart` selected FAST: 8,855 passed, 7 skipped, 7 failed. All seven
failures are in `tests/test_photoproduct_review.py`, which requires the absent
external file `/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`.

The runtime guard reported 106 seconds total, with no test above its 5-second
budget. Slow-test triage found no per-test violator (slowest: deterministic
streptavidin adsorption packing, 4.43 seconds). The largest aggregate file runs
45 mock-engine/build tests in 30.9 seconds; it does not run native simulations.
The timing report spans 8,869 tests across unrelated subsystems. No shared stall
was established, no tests were relegated solely for aggregate time, and no budget
was changed.

Selector deferral, verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

After each browser run, test designs, project histories, isolated host credentials,
and temporary Playwright output were checked for cleanup. These four screenshots
are intentionally retained evidence. No user model or live host was changed.

This checks functional rendering locally, not WAN throughput or large-data performance.
