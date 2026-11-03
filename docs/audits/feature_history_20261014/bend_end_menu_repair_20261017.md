# S17 — Bend end-menu repair, October 17, 2026

Parent FH-20, supporting FH-27. Acceptance target recorded before edits: repair
missing sidebar markup and explicit selection scope using existing owners; both
S16 real-gesture cases must pass unchanged-strength placement, scope, Cancel,
publication, undo/reopen, console and disposal checks. Maximum two diagnostic
browser invocations; stop on a further defect. No gate/limit/scientific changes.

HEAD reconciles to `96ab701e`; initial unrelated dirty work preserved. The active
user goal now authorizes successive bounded handoff iterations until the next
fixed milestone closes, superseding the earlier one-task-per-session restriction.
The previous goal turn only created that goal; this iteration makes code progress.

Repair adds the existing action panel's missing HTML, registers it in Properties
and reuses the sidebar's contextual reveal observer. Owned menu creation reuses
`deformationTargets`, preserves explicit targets, refuses invalid/stale explicit
selection, and retains null/default placement scope only for empty selection.
No new lifecycle owner; `main.js` delta 0. Shared Bend/Twist handler changes are
covered by existing unit tests; browser acceptance here remains Bend-only.

## Validation and acceptance

- Focused guarded Vitest: `src/ui/blunt_end_menus.test.js`,
  `src/ui/right_sidebar_tabs.test.js`, `src/scene/deformation_targets.test.js`:
  **38 passed**, 3 files, 2.43 s. Added real-HTML mount, both explicit-strand
  paths and stale-selection refusal coverage. A fifth new test subsequently
  exercises Properties reveal from a collapsed sidebar in the full frontend run.
- `NADOC_HISTORY_E2E_GREP='bend end-menu' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`:
  first invocation **2 failed** (17.5/16.6 s), both after successful publication,
  save/undo/redo/reload at the previously unexecuted reopen angle assertion:
  expected string `20`, actual `20.00`. Existing popup `toFixed(2)` is correct;
  changed this assertion to exact numeric equality, not tolerance or omission.
  Second invocation **2 passed in 28.1 s** (sidebar 12.2 s, context 10.8 s).
  Both actual gestures now pass end-plane placement, explicit strand Prepare
  scope, private edit/Cancel exact browser/canonical/saved-byte preservation,
  one Apply/operation/history/revision, save/undo/redo/reopen, no legacy mutation
  calls, empty browser console and zero private preview roots after disposal.
  No fake response/menu callback, new probe or budget change.
- `just lint`: passed (Ruff backend/tests), zero lint debt added.
- Full frontend result and final documentation checks recorded below.

Required `just smoke` is outstanding, assigned to S18 with explicit artifact
preflight. S17's two diagnostic browser invocations are exhausted; no third run
was slipped into this bounded task. Production startup/other smoke regressions,
Twist menu parity, other target kinds, all-scale resource/latency, polymer and
routing/Sweep workflows remain unqualified. No backend or scientific suite rerun;
existing full-backend failures remain debt. ISSUE-145's repair is verified in the
isolated app; this is not complete FH-20/FH-27 release qualification.

## Cleanup

Before each browser invocation, inventoried all writers under launcher root R:
workspace fixture/project metadata, playback/session state, tmp browser profiles/
downloads, Playwright outputs, Vite/UV/XDG/Playwright caches, `.owner-start` and
`share-control.json`. Existing finally closes page/deletes document, stops marked
services/descendants and deletes R on failure/success. No traces/video/captures
retained, browser installs untouched, all fixture names `__e2e__`.

Both `/tmp/__e2e__history-s9i7b_94` and `/tmp/__e2e__history-wo5xhswh` are
independently absent after launcher cleanup. No accessible process environment
carries either marker (31 protected environments unreadable). No workspace
`__e2e__history*` fixture remains. Ports 8004/5177 have no listeners and accept
server-style reuse binds. Removed-byte counts were not measured by the launcher.
Normal guard/cache records retained; the temporary frontend text log is removed
at closeout after extracting its compact result. No user artifacts removed.

**21/38 complete; 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged.**
S18 is the sole successor in the handoff. No commit/push or unqualified gates.


Final frontend validation: `just test-frontend` **9,277 passed, 1 skipped across
770 files, 353.43 s**, exit 0. This includes all 25 menu tests and 10 sidebar tests,
including the new collapsed-sidebar reveal case. Five unit cases were added here;
counts are actual current run results, not a claimed delta against historical
worktree totals. Full backend debt is unchanged.

Final checks: memory lint **0 errors/0 warnings**, `git diff --check`, JavaScript
syntax checks and `just lint` pass. 285 current plan/evidence/memory file-link
targets resolve (anchors not exhaustively checked). Ledger verifies 38 unique
milestones, 21 Done, 9 Parked, 8 open core and exactly one successor S18. Existing
historical artifact-link gaps in ISSUE-100's ledger remain as recorded in S16.

Completed frontend text log: no active reader reported by `fuser`; removed 231,426 bytes and verified absent. Compact results retained above.


Subsequent S18 closes the smoke obligation above: **23/23** production smoke cases
pass with verified cleanup. See [S18 evidence](production_smoke_20261017.md). Current
sequencing is exclusively the handoff; full milestone exits remain open.
