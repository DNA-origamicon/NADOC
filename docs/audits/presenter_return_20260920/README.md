# Presenter leave / return — 2026-09-20

The room outlives presenter attendance. Leaving, opening another private file,
returning, and reopening the presenter tab preserve the guest invitation, cookie,
loaded snapshot and local navigation. The meeting's original expiry is unchanged.
Stopping a share, stopping hosting or host shutdown still ends availability.

## Implementation

- Presenter **Leave presentation / Return to presentation** controls are separate
  from Stop sharing. Leaving pauses broadcast, detaches the presenter stream and
  exposes the prepared-file picker for private inspection. Loading a different
  prepared view directly also leaves automatically. Return restores the original
  room snapshot; guest content is never replaced by the private file.
- An existing cookie plus the matching invitation/role resumes the browser sign-in
  without collecting a name/password again. First use still requires normal entry.
  Guest credentials cannot resume as presenter.
- Once joined, presenter credentials and the occupied slot survive absence until
  meeting end. Guest inactivity reclamation cannot evict the presenter. A separate
  browser with presenter credentials can reclaim an absent presenter's place,
  invalidating the old presenter credential but leaving all guest sessions intact.
- The host denies camera writes while the presenter is away, including a write
  whose request body completes after leaving and returning. Leave ends only presenter streams;
  guest streams, cookies and package delivery remain available.
- Return uses the existing loaded view when possible. Weak identity tracking
  avoids retaining an already-disposed large scene while another file is open.
- No main.js edits (LOC delta **0**), scientific geometry changes or simulations.

## Evidence

Production HTTPS Chromium exercises four participants and the new leave/private
file/return/reopen sequence. The guest keeps its exact cookie and URL, makes **zero
new join requests and zero scene-download requests** while the presenter steps
away and returns, and retains unchanged canvas pixels while a different red
sphere is displayed privately by the presenter. The presenter tab reopens with
no name/password input. A subsequent guest reload also resumes without input.
Guest Follow is never silently re-enabled.

Host tests advance a fake clock beyond the two-minute inactivity window, exercise
return to a full room, check role/cookie isolation, reject guest Leave and away
camera writes, and verify a separately authenticated presenter can reclaim an
absent seat without affecting guest package access.

The existing public helper was deliberately not restarted or its invite revoked
for verification. Updated controls require a newly started host once to load this
software; ordinary subsequent leave/return does not restart hosting.

## Artifact ownership

Production-browser certificates exist only in mkdtemp TLS fixtures, removed in
`afterEach`. Private prepared files are supplied in memory through the browser
file-input API. No native design or scientific workspace file is changed.
Smoke/menu fixtures use __e2e__ names, global cleanup, disabled session caching
and isolated ports. Control credentials are removed in fixture/global teardown.
Logs are `/tmp/nadoc-attendance-*.log`; final gate totals are recorded below.

Real-laptop acceptance remains in MV-PRESENTER-RETURN. These are lifecycle and
privacy checks, not new claims about large-design GPU/WAN performance.

## Completed checks

- Full frontend suite: **480 files / 6,703 tests passed**. Final weak-reference
  lifecycle refinement also passed the focused join/attendance suite (**9 tests**).
- Node host/provider/control tests: **9 passed**, including a delayed camera body
  that arrives after Leave and Return and is still rejected.
- Production HTTPS browser tests: **3 passed** on the final frontend build.
- Standard app/assembly teardown smoke: **23 passed**.
- Help menu / part-specific link / resume / revoke browser check: **1 passed**.
- Production build, lint and diff whitespace checks passed.

After browser teardown, workspace, `.projects`, `.session` and `playwright_tests`
listings matched the preflight inventory. TLS fixture directories were absent.
A read-only query confirmed the original public Voltron share remained available
on the unchanged live helper. No existing invitation was rotated for testing.

## Backend gate

`just test-smart` selected **FAST**: **8,789 passed, 7 skipped, 7 failed**,
80.98 seconds in pytest. The seven failures are the same pre-existing
`test_photoproduct_review.py` missing-external-evidence cases from prior
checkpoints. The time guard reported 90 seconds and no backstop action required.
No Python code, unrelated photoproduct tests or test guards were changed.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
