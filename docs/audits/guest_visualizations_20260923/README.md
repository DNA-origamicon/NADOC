# Guest visualization feedback — 2026-09-23

Retained screenshots document the real editor → isolated local sharing host →
production guest viewer flow. `frontend/e2e/guest_visualizations.spec.js` uses
synthetic nanopore trajectory HTTP responses; it launches no simulation.

- `loading.png`: the guest receives the presenter's measured 7% progress.
- `ion-paths.png`: thick species-colored nanopore paths; the test also changes width.
- `vector-field.png`: vector arrows replace the paths through normal editor controls.
- `ended.png`: End clears the guest viewer and displays Presentation ended.
- `presence.png`: another guest's rounded name chip in the upper-right 3D area.
- `shared-view.png`: guest Share view button and persistent glasses action beside a named chip.

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
and temporary Playwright output were checked for cleanup. These six screenshots
are intentionally retained evidence. No user model or live host was changed.

This checks functional rendering locally, not WAN throughput or large-data performance.

## Guest presence follow-up

The two-guest browser exercise verifies self-exclusion, matching colors in the
presenter's compact initials, reload persistence, and removal on disconnect.
Presence follows active SSE connections, including multiple tabs using the same
guest session. The public roster contains only display ID, name, and color.
The follow-up frontend suite passed 6,775 tests in 497 files; all 13 selected
host/protocol tests passed. Build and lint passed. At this checkpoint, camera sharing
by guests was assessed only; the implementation checkpoint below supersedes that.
All 23 smoke tests passed again. Final cleanup found no new workspace/session
files, project-history directories, or test host credentials.
The follow-up backend run again selected FAST: 8,855 passed, 7 skipped, and the
same seven missing-external-packet failures above. Total guarded time was 107
seconds, with no per-test budget violator; the same FULL deferral applies.

## One-time guest views

Guests now publish one camera pose with Share view. Other participants receive a
ping, a 15-second chip glow and a persistent glasses button. Re-sharing replaces
the pose and restarts the notification. Saved views remain after disconnect until
the presentation ends. Recipients choose whether to move; the transition takes
about 0.9 seconds and manual canvas navigation cancels it.

The two-guest/editor browser test passed. It records intermediate editor camera
positions inside requestAnimationFrame, compares the final editor and guest poses
to the uploaded pose, waits for glow expiry, checks replacement/re-ping and verifies
the saved view after disconnect. Web Audio oscillator creation is observed through
the real browser implementation; this verifies the chime path, not speaker output.
The initial fixed-delay camera assertion sampled after the animation had completed
under browser load; animation-loop sampling removed that test timing assumption.

The frontend suite passed 6,779 tests in 499 files; the final focused run passed
21 tests including the additional explicit-click upload test. Thirteen host tests
passed, covering origin/session restrictions, revision validation, pose bounds,
replacement, retention and continued denial of guest live-camera authority.
Production build, lint, and whitespace checks passed. Main.js gains only controls
and canvas arguments on the existing prepared-export initialization line.
All 23 smoke tests passed. Post-run checks found no new workspace/session files,
project stores, test designs, or isolated sharing credentials.
The final backend FAST run again had 8,855 passed, 7 skipped and the same seven
missing external photoproduct-packet failures. Guarded runtime was 102 seconds;
the timing report contains no individual budget violators, so no tests or budgets
were changed. The FULL-suite deferral quoted above remains applicable.

## Guest UI cleanup and experience warnings

The guest roster is upper-left, vertical, longest displayed name first, including
Me and Presenter. Glasses stay immediately to the right of a remote guest's chip.
Performance is keyboard-only (Ctrl/Cmd+P); Jump is removed. Follow presenter starts
with the saved-view easing and can cancel an in-progress saved-view transition.

Local existing-transfer timings and foreground frame samples drive red wifi and
circuit icons. No extra probe downloads or hardware identifiers are collected.
The host accepts only two boolean flags from an authenticated same-origin guest,
limits update frequency, and expires stale reports after 30 seconds. Self status
appears locally; other rosters receive server status. Sampling exclusions, recovery,
body-read timing, cleanup, field restrictions and expiry have unit coverage.

The full frontend suite passed 6,786 tests in 503 files; a subsequent focused run
passed four tests including the additional measured-fetch lifecycle test. Thirteen
host/protocol tests passed, including health authentication and origin restrictions.
Production build and lint passed. Memory lint has zero errors (existing warnings).

The updated two-guest/editor browser scenario passed. It checks Ctrl+P, absent
buttons, roster order/position, stable colors, saved-view glasses/glow, Follow's
final pose, guest and editor health flags, nanopore visuals, progress and ending.
Sampling is tested deterministically in units; the browser exercises the real
status transport with injected warning flags. Retained presence/shared-view images
also show naturally detected local/remote circuit warnings. One initial test run
used the viewer pathname instead of the room ID for its injected health request;
correcting that test URL resolved its 405. Post-run inventory found no added
workspace files or isolated sharing credentials. Screenshots here remain deliberate
review evidence; simulations were HTTP fixtures only.

All 23 smoke tests passed. Final browser cleanup again found no new workspace or
session files, project stores, or isolated credentials. Existing production sharing
hosts must restart between meetings to load the changed server and guest assets.

The final backend selector chose FAST: 8,855 passed, 7 skipped, seven failures from
that same absent external photoproduct review packet. The selector's FULL deferral
quoted above remains unchanged. Guarded runtime was 106 seconds; triage found zero
per-test budget violators (slowest: streptavidin adsorption packing, 4.98 seconds).
As directed by the triage skill for aggregate-only growth, no arbitrary tests were
reclassified and no budgets were changed. Browser and backend runs were sequential.
