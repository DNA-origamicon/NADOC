# Presenter perspectives checkpoint — 2026-09-20

The original public-sharing implementation was committed and pushed as
`302d50f6`. This subsequent phase adds camera-only presenter control on the same
immutable prepared packages. The original phased plan now reflects temporary
public HTTPS hosting through Tailscale Funnel, with no guest installation.

## Behavior implemented

- Host-only presenter invitation; guest links cannot obtain presenter authority.
  Copy invitation excludes the presenter secret. Same meeting password is required.
- Independent guest navigation by default; one-shot Jump and explicit Follow.
  Drag, wheel, reset and navigation-mode changes exit Follow before handling input.
- Latest ordered state for late joiners, bound to the package-byte SHA-256.
  Camera messages validate vectors, clipping planes, field of view and navigation
  mode. Presenter sends only changed poses, at most one in flight and ten per second;
  host permits at most twenty updates per second. Slow event consumers disconnect
  instead of accumulating an unbounded camera history.
- Presenter pause/disconnect and guest network loss release camera ownership.
  Browser offline explicitly closes the stream; online establishes a new stream.
  Reconnection never re-enables Follow automatically. Transient status-request
  failure keeps retrying; confirmed revocation ends the channel.
- Four participants across the host, including presenters. Closed-browser leases
  can be reclaimed after two minutes without a heartbeat. Revocation/shutdown ends
  state streams. Existing public session is left running on its original build;
  presenter controls are available after the next normal hosting stop/start.

## Validation

Production Chromium uses an isolated HTTPS proxy with a test-only certificate.
Four independent browser contexts exercise presenter motion, unchanged guest
canvas pixels before Jump, one-shot Jump, Follow, direct-input escape, late join,
guest write rejection, offline/reconnect and presenter disconnect. Both HTTPS
browser tests pass. The earlier generic orbit check failed once before a connection
readiness wait was added; subsequent complete runs passed. The added offline test
caught a real idle-stream lifecycle defect, fixed by browser offline/online handling.

[Guest Follow screenshot](guest-follow.png) was inspected. The synthetic box is
intentional: these are camera/lifecycle checks, not scientific visual or GPU
performance acceptance. The previously verified public Voltron invitation was not
revoked to deploy a test build.

- Full frontend suite: **479 files / 6,700 tests passed**.
- Host/provider/control tests: **9 passed**, including cross-snapshot participant
  capacity, disconnected lease reclamation, presenter authority and late state.
- Production HTTPS browser tests: **2 passed** (four contexts in the room check).
- Actual Help menu copy/share/presenter-link/revoke flow: **1 passed**.
- Standard application/assembly teardown smoke: **23 passed**.
- Production build, repository lint and `git diff --check`: passed. Build retains
  the existing large-chunk warning.

The TLS fixture owns temporary certificates under `/tmp/nadoc-internet-e2e-*`
and removes them in `afterEach`. Smoke/menu tests create only `__e2e__` parts and
project stores, removed by global teardown; session caching is disabled. The menu
fixture owns only its isolated port-5174 control credential and removes it in
`afterAll`; global teardown removes the isolated viewer-test bridge credential.
Post-run inventory matched the original workspace, `.projects`, `.session` and
`playwright_tests` directory listings exactly. No TLS fixtures or isolated control
credentials remained. The retained screenshot is outside the workspace.

Execution logs are `/tmp/nadoc-perspectives-{frontend-final,host,browser,menu,smoke,build,lint}.log`.
The backend gate result is recorded below separately; no Python source or test
changes belong to this phase.

## Remaining gates

No new large-design FPS claim. The earlier RTX 2080 SUPER A/B certified decoder
extraction only. Real-device Voltron package versus editor A/B, Follow timing,
public-network motion/transfer, all three navigation modes, browser/OS coverage,
Full assembly/physical-overlay parity and recorded cube_pore playback remain open.
The current performance capture exits Follow and pauses broadcast to preserve
repeatable camera ownership; it does not measure Follow interpolation FPS.

Scientific base/domain/cluster highlighting is not implemented in this phase.
It needs a stable selection/assembly-instance package contract and a matching
editor snapshot before coupling presenter selection to guests.

main.js LOC delta for this phase: **0**. No native scientific geometry changes,
simulation launches or user workspace mutations.

## Backend gate and slow-test triage

`just test-smart` selected **FAST**: **8,789 passed, 7 skipped, 7 failed**,
89.14 seconds in pytest. All failures are the same existing
`tests/test_photoproduct_review.py` cases recorded at the previous checkpoint.
They require missing external photoproduct evidence under
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/`; they do not exercise
presenter hosting. The unrelated photoproduct test edits remain outside this commit.

The aggregate guard reported **93 seconds / 90 seconds**, with **zero** individual
violators. Local triage followed `.claude/skills/triage-slow-tests/SKILL.md`: the
slowest unmarked test was existing streptavidin adsorption packing at **4.13 s**,
then biotin tether packing at **4.04 s**. No new Python fixture, host probe or sleep
was introduced. This is an aggregate overrun; there is no identified heavy test to
relegate. No budgets, markers or guards changed; no repeat of the unchanged full
fast suite was used to chase a passing wall-clock result. Log:
`/tmp/nadoc-perspectives-backend.log`.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
