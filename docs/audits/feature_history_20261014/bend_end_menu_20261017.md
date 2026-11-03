# S16 — Bend end-menu acceptance, October 17, 2026

**Stopped at demonstrated defects; acceptance incomplete.** Parent FH-20,
supporting FH-27. HEAD remains `96ab701e`; pre-existing dirty/untracked changes
were preserved. No production code, geometry, constants, goldens, guards or gates
changed. No commit/push. S17 is the sole successor, defined in the current handoff.

Acceptance target recorded before implementation: two actual ring/menu browser
cases, exact end-plane placement and explicit strand scope, unchanged canonical,
browser and saved state on Cancel, one Apply operation/history/revision, undo and
saved reopen, no legacy mutation, empty console, disposed preview roots and
60-second budgets. Stop at two invocations or a demonstrated production defect.

Delivered two cases in `frontend/e2e/bend_release.spec.js`, using the existing
read-only `getDomainEndScreenPositions` probe and actual mouse/menu gestures.
Explicit strand setup uses the existing selection controller, as in toolbar
acceptance; this is not a qualification of strand-picking gestures. No callback
injection or fabricated response. The isolated Playwright config now accepts an
optional `NADOC_HISTORY_E2E_GREP` regex; unset preserves its complete test selection.
The two new cases intentionally remain red until the defects are repaired.

## Actual results and stale-claim reconciliation

One guarded browser invocation, two failures, no retries:

- Sidebar, **10.4 s**: real ring left-click followed by the required sidebar Bend
  locator fails because `#blunt-bend-btn` is absent. Repository search confirms
  `blunt-panel-actions`, `blunt-panel-info`, `blunt-panel-empty`, and sidebar Bend
  exist only in menu source/tests, not the real HTML. `main.js` calls `showPanel`
  on left-click, but optional DOM access silently does nothing. Unit tests create
  the missing elements. No sidebar Prepare/Cancel/Apply was reached.
- Context menu, **6.0 s**: real ring right-click and Bend click prepare successfully.
  Plane A matches the fixture arm start and B matches the clicked end bp; angle
  edit evaluates. Canonical checkpoint (including saved-file digests) and browser
  design/geometry/revision stay exact; Cancel leaves the checkpoint unchanged,
  removes private preview roots, and the console is empty. The next assertion
  fails: request `targets` is **null**, expected
  `[{"kind":"strand","id":"scaf_XY_0_0"}]`.
  `blunt_end_menus.js:beginDeformation` unconditionally passes null, unlike the
  toolbar's explicit selector resolution. Existing unit tests pin that null and
  do not cover a selected strand.

These are ISSUE-145. The historical claim that all four end-menu actions are
wired does not establish a real sidebar surface or preservation of explicit
selection. No topology interpretation or molecular authorization is needed to
report these UI defects. S16 stops here under its agreed condition; no repair was
started. Apply/undo/reopen, post-Apply legacy-call and final-console assertions
remain **unexecuted** in these new cases. Neither surface is accepted. Tiny-fixture
context Cancel evidence is partial, not milestone or release credit.

## Commands actually run

- `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --check-storage`: passed; `/tmp`, 661 GiB free.
- `NADOC_HISTORY_E2E_GREP='bend end-menu' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`: **2 failed**, as above; one invocation of maximum two, stopped on defect.
- `just validate-safe npm --prefix frontend run test -- src/ui/blunt_end_menus.test.js src/features/deformation_history_controller.test.js src/app/deformation_history_editor.test.js`: **104 passed**, 3 files, 1.97 s. Existing tests do not disprove the browser failures.
- `node --check` on the modified browser spec and isolated config: passed.
- Memory lint, diff/link/count checks: recorded in final closeout below.

No backend behavior changed, no backend suite rerun. No full frontend/backend,
scientific, native build or resource campaign. Historical broad regression debt
and fixed 16-helix/1,024-site admission bounds remain unchanged. Test duration is
not interaction-latency qualification. Server ORJSON deprecation and Node color
environment warnings occurred; these are separate from the empty browser console.

## Artifact inventory and cleanup

Before launch, inventoried existing isolated contract: root `R` contains
`workspace/__e2e__history-*` fixture saves/metadata, `workspace/playback`, optional
session state, `tmp` browser profiles/downloads, Playwright output, Vite/UV/XDG/
Playwright caches, `.owner-start`, and `share-control.json`. No capture/video/
trace, installation, download or user-workspace write. Per-fixture finally closes
page/deletes document; outer launcher finally stops owned services/descendants,
then removes the root even on assertion failure. Guard lock and small normal
software caches remain under existing policy.

Actual root `/tmp/__e2e__history-cunjtf0r` was removed by the launcher and
independently verified absent. No accessible process environment carries that
marker; 32 protected process environments were unreadable and are not claimed
inspected. No `workspace/**/__e2e__history*` files remain. Both ports have no
listeners and accept server-style SO_REUSEADDR binds. Initial plain bind failed
due to observed TIME-WAIT sockets, not a surviving listener. Deleted byte count
was not measured before automatic removal; do not invent it. No raw browser
artifacts retained; only source and compact evidence plus ordinary guard/caches.

**21/38 complete, 17 remaining (8 core, 9 parked), delta +0 completed/+0 total;
U1–U54 unchanged.** FH-20/FH-27, ISSUE-100 and MV-48 remain open. S17 repairs the
two observed end-menu blockers and reruns these same acceptance cases; unstarted.

Final closeout: memory lint **0 errors/0 warnings**; `git diff --check` and both
JavaScript syntax checks pass. Ledger verified **38 unique rows, 21 Done, 9 Parked,
8 open core**; handoff has exactly one task definition, S17. Current plan/handoff/
evidence file targets resolve. Wider 362-link file-target audit found 19 missing
historical artifact-link occurrences in `issues_ledger.md`, all already present
in HEAD (Benchy/VR raw evidence); preserved and not repaired within S16. Anchor
validation was not exhaustive. Production default-false preview gates and their
source files are unchanged. No further browser invocation or successor work.
