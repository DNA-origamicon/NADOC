# Full-only VR startup and on-demand representations — 2026-09-29

Normal launch forces Full and exports only its natural and Expanded Quick View
blocks. Atomistic, surface and preview construction are skipped. Only Full is
uploaded at startup. Expanded Quick View is the existing display-only pose.

Selecting an unavailable representation exports only the requested source from
a frozen document. Native parsing runs asynchronously with Full's normalization.
Completed export and parser record counts drive substage progress, displayed to
one decimal place inside the button. Parsing occupies 75–95%, preparation 96%,
application 99%; 100% means the style has actually been applied. The previous
geometry remains visible. Request sequences and document revisions reject stale
results. Failures leave a retry label. Loaded CPU blocks remain until scene refresh.

## Measured evidence

The same 24HB startup that took 88.4 seconds in the earlier all-representation
run took 4.265 seconds and 4.141 seconds in two Full-only runs. The initial popup
appeared at 2.312 and 2.466 seconds. The first Full export was 205,129 records /
4,302,264 compressed bytes in 2.741 seconds, versus about 11.8 million records /
258 MB previously. These are fresh companion processes on the running workstation,
not an operating-system reboot benchmark.

| Preset | First requested style | Time to displayed style | Distinct measured percentages |
| --- | --- | ---: | ---: |
| steady_fast | Surface | 54.78 s | 778 |
| steady_deliberate | Ball & Stick | 31.08 s | 298 |
| variable_fast | mrDNA fine | 6.08 s | 15 |
| variable_deliberate | oxDNA | 8.37 s | 47 |

All four passed. Both eyes contained the loading bar in the projected lower
region of the actual pressed button; a blank-image negative control failed as
expected. Percentages were monotonic, frames advanced, and the previous style
remained active before application. Completed scenes contained identifiable
pixels in both eyes. The final desktop delivery check passed.

Observation adjustments: model placed in the tracked view, mirror enlarged,
right visualization menu opened with ordinary controller input. The tour uses
a private desktop-style acknowledgement responder, as the existing representation
tour does; it does not exercise a real browser's acknowledgement handler.
Stereo evidence does not establish through-lens text legibility or comfort.

Retained evidence: `.development-artifacts/vr-lazy/first-01/` and
`.development-artifacts/vr-lazy/matrix-01/`.

Reusable entry: **Debug → VR Tours & Tests → Controls & layout → Full startup
and on-demand representation progress** (`representation-loading`). Both tours
stopped their viewers; owned session files, sockets, and representation files
were checked absent afterward.

## Software verification

- Native viewer rebuild passed; sidebar and menu-layout checks: 2 passed.
- Selective export/IPC: 13 passed, including exact natural/expanded primitive
  parity against complete exports for nine source styles, native scene validation,
  skipped construction, superseded requests, and document-change rejection.
- Startup: 5 passed, including forcing Full from a VDW launch request.
- Ruff and whitespace checks passed.

- Frontend: 577 files passed; 7,273 tests passed, 1 skipped.
- Backend selection: **FAST (fast suite only)**; 9,442 passed, 93 skipped.
  The pre-existing `tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`
  failed again. Two unrelated cases exceeded the five-second budget in the
  parallel run (worker reattachment and mrDNA surface preparation).

Selector deferral, verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

Slow-test triage: both flagged cases passed individually with 0.04-second call
times (1.16 and 1.21 seconds including setup/session). Worker transfer uses a
mock and event synchronization; the surface case stubs job execution and tests
preparation only. The parallel-run timings did not reproduce in isolation; no
budget or test classification was changed.

## Live Cylinders acknowledgement correction

The user's open session exposed a missed case: export status was ready (17,729
records), native requested Cylinders at style sequence 4, and the desktop feed
contained `NADOCVR_VISUALIZATION 3 2 none cylinders strand 0`. The viewer had been
launched with ScryWrite off, so direct live observation could not attach.
Read-only session/event/feed evidence is retained under
`.development-artifacts/vr-lazy/cylinder-live/`.

The newly added initial-Full acknowledgement guard rejected this valid cylinder
revision because the browser had not published a redundant Full revision first.
Removed that guard: startup itself establishes Full; the first newer desktop
acknowledgement must be accepted regardless of style. The reusable loading tour
now deliberately omits the redundant Full acknowledgement and starts with
Cylinders. A production Viewer/GL regression exercises this exact feed and
requires Cylinders plus completed 100% progress. The earlier private responder
always sent Full, masking this defect.

Correction verification: native viewer and live-test builds passed; the real-GL
ScryWrite regression passed, including direct Cylinders acknowledgement without
Full and completion at 100%. The existing identity/occlusion GL checks also passed.
The currently open process still runs the old binary until restarted.
