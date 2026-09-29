# Browser-owned VR checks and worker lifetime — 2026-09-29

The previous check launched the companion directly, leaving the browser's event
receiver inactive. Asking the user to click View in VR was a workflow error.
The new `browser-representations` tour opens a private copy through the real
browser file-opening flow, waits for geometry and a dismissed Welcome screen,
then invokes the production View in VR handler. ScryWrite drives native input;
the real browser alone publishes style acknowledgements. There is no substitute
acknowledgement responder.

The browser launch opts into transactions and the existing tracked-head scene
framing for diagnostic visibility. Normal startup defaults are unchanged. The
private document and workspace file use unique `__e2e__` names; the wrapper
closes/removes the document, source file and cache even after failed checks.
Browser profile, native process and socket directory are owned and cleaned up.
The source document was compared before and after and remained unchanged.

## Accepted evidence

`.development-artifacts/vr-lazy/browser-matrix-04/` passed all four motion
presets, comprising the initial cylinder load and three Full/Cylinders round
trips. Every cylinder result reached 100%; the actual desktop menu selected
Cylinders. Desktop and stereo images show the part. Each eye contained over
84,000 visible model pixels with nonzero primitive IDs (axes cannot satisfy this
oracle). Sixteen real browser visualization publications were recorded, with no
browser exceptions. Through-lens readability and comfort were not assessed.

`.development-artifacts/vr-lazy/backend-shutdown-02/` launched a separate real
FastAPI worker and native viewer. Terminating only that worker's process group
caused its separately grouped viewer to exit and removed all recorded sidecars.
This verifies graceful backend shutdown/reload, not SIGKILL or machine failure.

`vr_lifecycle` tracks Popen objects owned by each worker, terminates them during
FastAPI teardown, and joins their existing cleanup threads. Cleanup now removes
stale session state after the child has exited, without relying on a liveness
check that necessarily fails at that point. SteamVR itself is left running.

Both checks are registered under **Debug → VR Tours & Tests → Controls & layout**.

## Retained attempts and stronger assertions

- `browser-01` established real acknowledgements but did not establish visible
  geometry: the browser was still on Welcome.
- `browser-matrix-01` failed its visible-pixel assertion.
- `browser-matrix-02` exposed an inadequate class-only assertion: origin axes
  counted as model pixels. It is not accepted visual evidence.
- `browser-matrix-03` failed to enable ScryWrite after the Open action consumed
  URL parameters. Diagnostic launch flags are now set explicitly by the runner.
- `backend-shutdown-01` rejected a lowercase lattice enum; the retry used the
  standard default. Its isolated backend/workspace were cleaned up.

## Regression results

Lifecycle ownership tests: 2 passed. Backend selection: **FAST (fast suite only)**;
9,444 passed, 93 skipped, with the previously known failure
`tests/test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`.
Runtime was 25 seconds, within the fast-suite budget. Ruff, JavaScript syntax and
whitespace checks passed. No production browser UI implementation changed.

Selector deferral, verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

The final steady-fast run (`browser-final-05`) also passed after cleanup hardening.
Its recorded PID, socket directory and all recorded sidecars were absent afterward;
a recursive workspace check found no private source files or session caches.
