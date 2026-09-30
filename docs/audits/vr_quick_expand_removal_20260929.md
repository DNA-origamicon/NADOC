# Remove Quick Expand from VR — 2026-09-29

The previous visibility fix was committed and pushed first as `36f02778`.
VR now exports and retains only natural geometry. Removed the expanded export,
parity digests, duplicate scene/ownership storage, animation/interpolation,
View Tools control and expansion-dependent editing restrictions. End and plane
feedback, ligation catalogs and resize handles no longer compute expanded poses.
Legacy wire readers/zero-filled reserved offsets remain compatible; they cannot
enable expansion. Desktop Quick View remains separate; an expanded desktop scene
cannot override the native natural model.

View Tools now exposes ten controls. Its binary schema is version 4 so old
control indices cannot silently trigger different tools. Retained flags keep
their existing bit positions (bit 7 is retired). Model scaling and movement are
unchanged.

## Startup measurement

Same workstation, physical SteamVR path and `workspace/24hb_0xT.nadoc`, using
three fresh viewer/exporter processes before and after. These are warm operating
system runs, not reboot/cold-disk timings. No test compilation or broad suite ran
during the measured trials. Existing startup tour captures loading and ready
stereo frames and verifies model pixels; its polling/captures add observation
overhead.

| Metric | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Launch request → ready model, median | 4.176 s | 2.881 s | 31.0% |
| Snapshot export/compression, median | 2.718 s | 1.282 s | 52.8% |
| Snapshot records | 205,129 | 102,566 | 50.0% |
| Compressed snapshot bytes | 4,302,264 | 2,151,243 | 50.0% |

Before ready times: 4.404, 4.176, 4.145 s. After: 3.288, 2.877, 2.881 s.
Retained raw reports: `.development-artifacts/vr-no-expand/before-{1,2,3}/`,
`final-{1,2,3}/`, and `startup-comparison.json`.

## On-demand representation loads

The same 24HB four-profile tour was run before removal (the retained
`vr-loading-visible/matrix-02`) and after (`vr-no-expand/loading-framed`). These
are single request-to-ready samples, including controller input and captures,
not repeat-run medians or a universal speed guarantee. The sidebar was moved
aside in the after run to prevent the retained model obscuring its progress bar.

| Requested representation | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Cylinders | 5.56 s | 3.24 s | 42% |
| Surface | 60.93 s | 36.87 s | 39% |
| Stick (from Surface) | 22.57 s | 10.96 s | 51% |
| VDW | 29.24 s | 14.47 s | 50% |

The earlier after-run Surface sample was 31.76 s; timing variation is retained.
All four profiles in the completed run passed stereo model/progress checks,
point-fallback captures when activated, 100% application, and desktop delivery.
All owned benchmark viewers, sockets and scene/representation files were removed.

## Diagnostic attempts

The first after-change trial (`after-1`) exposed a fixed eleven-entry loop in
inspector observation after the control list became ten entries. Corrected it to
use the actual key count, stopped/cleaned the owned trial, and excluded it from
timing results. The first on-demand trial (`loading-matrix`) captured the retained
Surface obscuring Stick's progress bar in the left eye. Kept the failed evidence;
the follow-up moves the real sidebar 0.35 m sideways through its grip control
before measured requests. Pixel thresholds and loading behavior are unchanged.

## Software checks

- Focused backend export/feedback/representation/ligation/view-tool tests: 78 passed;
  updated natural-scene extrusion metadata tests: 3 passed.
- Native interaction, ligation, resize, Bend, Twist, object IDs and staged loading:
  7 passed. Natural-scene format/ownership validators: 13 passed.
- Frontend full suite: 577 files passed, 7,283 tests passed, 1 skipped.
- Initial `just test-smart`: FAST; 9,446 passed, 93 skipped, 2 failed. One was the
  obsolete expanded-bundle test (updated and passed); the other is the previously
  observed scalar/loop-skip geometry exact-equality failure, unrelated to VR.
- Slow-test triage: mocked `/api/simulate/jobs` responsiveness took 7.45 s in the
  broad parallel run, then 0.34 s in isolation (1.45 s including setup). It uses
  event-released mocked I/O; no physical solver is launched. No budget/marker was
  relaxed or unrelated scientific code changed.

Selector deferral, verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

## Crash recovery and remaining panel check

The browser check exposed a duplicate natural-frame import in the editor; fixed
it and verified the production frontend build. VS Code then crashed during the
concurrent software reruns. Their incomplete logs are retained and are not
counted as completed checks. Resumed with serial validation and two backend
workers to reduce resource pressure. No test/viewer processes survived the crash.

The post-crash browser check loaded the app and a natural VR model, and observed
exactly ten native View Tools entries with no Expanded entry. The quiver motion
could not arm: OpenXR view flags were 3 (valid poses, neither pose tracked). The
existing quiver gate correctly requires tracked position and orientation. No
tracking gate or gesture threshold was weakened. Asked for headset tracking to
be restored before repeating that check. Failed trace: `view-tools-final/`.
Temporary workspaces, native scene/socket, and test designs were removed; verified
the two stopped test ports and removed only their stale bridge credential files.

Resumed `just test-smart` selected FAST with two workers: **9,447 passed,
93 skipped, one failed** in 92.52 s. The sole failure remains
`tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`; all
VR tests passed. The same `/api/simulate/jobs` responsiveness case exceeded the
per-test budget (6.0 s), so its isolated timing is checked separately.

The final frontend rerun passed **577 files / 7,283 tests, one skipped**
in 97.05 s using four-core CPU affinity (three test workers), with no concurrent
backend or browser test. The production build also passed. Hardware quiver
validation remains limited by missing headset tracking; the previously completed
four-profile representation-loading and three-pair startup benchmarks are retained.

The isolated responsiveness recheck passed in 0.35 s (1.50 s including setup).
The slow condition did not reproduce outside the broad suite; the endpoint also
aggregates other engine catalogs, so this is not evidence of a heavy solver.
No test markers or budgets were changed. Ruff and `git diff --check` pass. Final
cleanup found no new test bridge files, temporary workspaces or owned viewers.
