# Job sharing — 2026-09-23

One guest invitation is reused across oxDNA/NAMD job publications, private job
inspection, visualization changes, and return to native coordinates. Header
controls and row indicators are owned by `viewer/job_sharing.js`; `main.js` adds
one net line of composition wiring.

The stream sends exact absolute render-buffer patches, targeting at most eight
samples/s with one upload and one guest download in flight. Scene replacements
are reserved for incompatible layouts/materials. GPU material version counters
do not count as visualization changes. A slow guest receives the latest frame
available when its request reaches the host, avoiding obsolete-sequence starvation.
This is bounded live delivery, not a whole-trajectory download or a new scientific
coordinate codec. Existing prepared-view shader/layout/size guards remain.

The host validates compressed frames and revision identity; guests validate lengths,
hashes and decoded indices. Guest frame reads require the existing meeting cookie.
Only the local editor lease can publish. WSL streaming uses a persistent Windows
Node pipe instead of spawning a process and writing a temporary file per frame.

## Evidence

- `job_sharing.spec.js`: real editor headers/list and standalone guest, oxDNA →
  private NAMD selection → explicit NAMD publication → native model; unchanged
  invitation and cookie, no new join. Green/red colors and exact tooltip verified.
- `guest-before.png`, `guest-stream.png`: intentionally isolated test-model render
  change used to verify frame transport visually; not a simulation or geometry
  validation. These screenshots were inspected. `sharing-control.png` shows the
  actual red Stop sharing button.
- Frontend suite: 492 files / 6,763 tests passed. Production build and Ruff passed.
- Host/transport/clip suite: 13 tests passed, including the persistent transport,
  authenticated reads, stale revision rejection and reset-to-base frame.

Disposable models use `__e2e__` names and the global test teardown. The local
sharing credential is created exclusively and removed in `afterAll`; no active
user host/tunnel is restarted. Screenshots in this directory are deliberate review
evidence; other Playwright screenshots/traces are disposable. Test jobs are HTTP
fixtures or read-only extraction from an existing recording; no simulation runs.

Public-network FPS/throughput and every large atomistic/solvent visualization have
not been certified. The new host requires `job-stream-v1`; an old running host
needs a user-timed restart after its meeting, ending those old invitations once.

Additional validation:
- `share_link.spec.js`: same-invitation update passed.
- `trajectory_share.spec.js`: passed with eight read-only extracted frames from the
  existing cube-pore NAMD recording. `namd-stream.png` and `namd-native.png` were
  inspected; the guest stays signed in when native coordinates replace the trajectory.
  The disposable design drops external project-history references; source files are unchanged.
- `just test-smart`: decision `FAST`, 8,855 passed, 7 skipped, 7 failed. All failures
  are in `test_photoproduct_review.py`, requiring the unavailable archive
  `tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`.
  The guard flagged the adsorption packing test at 5.52 s during concurrent browser
  rendering. Slow-test triage found atom-cloud packing and pairwise clearance checks;
  after the browser finished, the unchanged test passed in 3.99 s. No timing budget
  or test registry was changed; the aggregate fast run was 132 s.

The selector's deferred notice (verbatim):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

- `just smoke`: all 23 checks passed, including real-design rendering and teardown.
- Final cleanup: no `__e2e__` workspace files, task-specific project histories,
  :5174 test sharing credential, or disposable Playwright output remains. Inventoried
  workspace/session paths have no additions. Retained screenshots are listed above.

## Integrated editor presentation controls

The separate **Open presenter** entry has been removed. `presentation_controls.js`
mounts **Presenting**, an icon-only glasses toggle, and **End** at the top center
of the editor's canvas area. Glasses have an accessible label, pressed state and
explanatory tooltip. Camera sharing starts off; native camera authority and job
camera authority transfer without opening tabs or replacing the guest invitation.
**End** and **Stop hosting all links** invoke the same handler. A failed stop request
keeps the controls visible and reports the error. The old Broadcast dialog entry is
hidden in the integrated editor. No additional `main.js` wiring was needed.

The browser exercise verifies the indicator's actual canvas-relative position,
native camera sharing on/off and guest Follow availability, authority transfer into
job sharing, private-selection pause, return to native camera sharing, and real
host shutdown through End. The number of open browser pages does not increase.
`presenting-controls.png` and `presenting-in-editor.png` were inspected and retained
as visual evidence. The full frontend suite passes: 493 files / 6,768 tests;
production build and Ruff also pass.

The native-view regression uncovered and fixed a multi-view camera capture issue:
embedded camera sharing now uses the active pane when the main renderer is hidden,
and explicit snapshot updates export that pane. Inline error text does not intercept
model interaction. The 18 targeted sharing tests pass after this correction.
The updated native-view browser regression passes, retaining its color, section-cap,
and active multi-view snapshot checks through explicit **Update shared view**, plus
inline camera sharing, unchanged guest sessions, and invitation revocation.
Final integrated-controls smoke gate: all 23 checks passed. The final production
build passed. Inventory comparison confirms no new workspace/session files, project
stores, named test artifacts, test sharing credential, or disposable Playwright
output remains after cleanup. User simulation data and the active user host were
not changed.
