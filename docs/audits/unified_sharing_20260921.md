# One invitation for static views and trajectories — 2026-09-21

The static/trajectory split was an incremental implementation detail, not a guest
access requirement. Help → Share link now has one publish action and an optional
**Include recorded trajectory** setting. Select the existing presentation and use
**Update shared view** to switch content; **New invitation** remains an explicit
choice when a separate presentation is wanted. Existing presentations are selected
by default, so a normal update does not quietly create another invitation.

Host content replacement checks the prepared-package header, trajectory container
and host capacity before changing the room; full scene decoding stays in the viewer.
It preserves the room ID, invitation/password, presenter token,
guest sessions, and expiry. An invalid replacement keeps the old scene and clip.
A revision event sends the new scene to joined browsers; their camera is preserved.
Playback controllers and pending frame downloads are disposed/recreated for the
new content. Embedded PNG textures decode in batches of at most 16: the first
real-cube browser exercise exposed serial image loading taking longer than its
45-second update allowance while rendering the previous scene on software graphics.
Returning to a static snapshot releases the old clip. Guests never
acquire presenter authority from a content update.

Presenter viewers recognize authorized host replacements as shared revisions,
not private file opens; their private-file Leave/Return behavior remains in place.
Camera sharing pauses when content changes, and old camera commands cannot target
a new revision. Editor broadcasting must be turned off before explicitly replacing
a shared view. To resume editor visualization broadcasting after a clip, update
that same invitation with a static view, then enable Broadcast to presentation.

Guests still use the same browser entry and optional password prompt. The host's
Open presenter action retains separate authority; it is not a second guest
invitation. This change does not implement automatic live publishing from the
native MD play button or remove prepared-clip size/performance limits.

An older running host needs one explicit restart after its meeting to load the
`share-content-v1` protocol. No active host or tunnel is restarted by development
checks. The restart ends old invitations; create one new invitation afterward.
After that upgrade, content changes do not require new links or sign-ins.
main.js LOC delta: 0.

Validation:

- Host/transport/trajectory Node group: 12 passed. The commit-preparation rerun
  also included room state, internet configuration and detached-launch tests:
  **17 passed**. Documentation links and diff whitespace checks passed.
- Final full frontend suite: **486 files, 6,734 passed** (92.16 s), including the
  revision race guard and batched image decoding. Earlier focused sharing checks
  passed 26 tests.
- Final decoder/presentation/viewer focused checks: 20 passed, including bounded
  concurrent image decoding. Production build and Ruff lint passed; existing
  bundle-size advisory remains.
- `just test-smart`: **FAST**, 8,789 passed, 7 skipped, 7 failed. All failures are
  in `tests/test_photoproduct_review.py`, requiring the unavailable archive
  `tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`.
  No photoproduct files were changed by this task.
- The guard reported 103 s total (96.93 s pytest), above its 90 s aggregate
  backstop. Following `.claude/skills/triage-slow-tests/SKILL.md`, the timing report
  has **zero per-test violators** (slowest 4.19 s). Costs are spread across the
  existing suite; the previously documented aggregate overrun remains. No Python
  tests or fixtures were added here, and no arbitrary tests were moved or budgets
  raised to suppress the notice.

The backend selector deferred the gated suite verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

Actual app validation used isolated backend/Vite ports 8001/5174 and local,
throwaway sharing hosts. The part-specific sharing/editor-broadcast browser test
passed (1.4 min). The updated real-cube test passed after the texture-loading fix
(2.8 min test / 3.0 min run): one joined guest moved static → recorded trajectory
→ static with identical URL and session cookie and no additional join requests.
First/last canvases differed; a previously uncached seek also completed with
1 Mbps / 200 ms network emulation. No page errors were recorded. The fixture reads
existing job `796c568b5690` frames 0,100,…700 into an isolated synthetic eight-frame
API response; no simulation ran and the source job was unchanged.

The local software-rendered browser run verifies transitions and frame delivery,
not representative render FPS or WAN performance. It issued three frame requests
and logged zero transfer errors; the uncached throttled seek took about 16.2 s,
including software-rendering contention. Existing clip-size/data-rate limitations
remain; this change makes no new playback FPS guarantee.

Retained review evidence (all invitation credentials were disposable and revoked):

- [Updated controls, scrolled dialog excerpt](unified_sharing_20260921/unified-share-controls.png)
- [First sample](unified_sharing_20260921/trajectory-first.png)
- [Last sample](unified_sharing_20260921/trajectory-last.png)
- [Trajectory metrics](unified_sharing_20260921/trajectory-metrics.json)

Workspace, project-history, session and Playwright scratch inventories matched the
preflight after each run; isolated sharing/browser credentials were absent. The final
`just smoke` run passed all **23 tests** (2.4 min), including assembly exit and
close-session teardown. It removed six temporary designs and one project-history
store. [Final cleanup proof](unified_sharing_20260921/cleanup.json) confirms no
inventory differences, no isolated credentials, and removal of disposable browser
outputs. Only the compact evidence listed here is retained.
