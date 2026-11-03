# S19 — Twist end-menu creation parity, October 17, 2026

Parent FH-20, supporting FH-27. Read current instructions/handoff, project memory
and ledger; HEAD still `96ab701e`, S17/S18 and other dirty changes preserved.
Previous goal turn made verified S17/S18 progress; no blocker/wait inherited.
Acceptance target before edits: two Twist real ring/menu cases with exact end
placement, explicit strand scope, Cancel state/saved-byte preservation, one owned
publication, undo/reopen, strict console/disposal and no legacy mutation calls.
Maximum two diagnostic invocations, unchanged 60-second budgets.

Parameterized only the existing end-menu cases in `bend_release.spec.js` over
Bend/Twist. Existing Bend assertions retained; Twist adds operation-kind and
exact total_degrees=20/degrees_per_nm=null persistence checks. Uses native Twist
fixture, existing read-only ring coordinates, actual mouse/menu gestures and
canonical selection-controller setup. No injected callbacks or fake responses;
no production, fixture, gate, geometry, constants, golden or timing changes.

## Actual checks

- Guarded focused Vitest: `src/ui/blunt_end_menus.test.js`,
  `src/app/deformation_creation_editor.test.js`,
  `src/ui/deformation_creation_launcher.test.js`: **52 passed**, 3 files, 2.65 s.
- `NADOC_HISTORY_E2E_GREP='end-menu' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`:
  **4 passed, 48.0 s**, one invocation. Bend sidebar 10.9 s/context 10.1 s;
  Twist sidebar 10.7 s/context 11.1 s. All exact placement/scope/Cancel/Apply/
  undo/redo/save/load/reopen, strict empty-console and zero-root assertions pass.
  One Apply request, one operation/feature/history/revision increment, no legacy
  deformation mutation calls. Test duration is not interactive-latency proof.
- Browser launcher storage preflight: `/tmp`, 661 GiB free; installed browser,
  free dedicated ports, no download. JavaScript syntax/diff checks pass.

No production behavior changed, so no new broad/backend/smoke/scientific run.
S17's full frontend and S18's smoke results are historical evidence, not reruns.
Tiny single-helix explicit-strand end-menu parity is accepted; toolbar Twist,
units/handedness controls, other targets, polymer, routing/Sweep chains,
failure/recovery and representative resources remain open. No full matrix row
or milestone closes. `main.js` delta 0. No commit/push.

## Artifact inventory and cleanup

Before invocation inventoried launcher root R: workspace `__e2e__history-*`
saves/project/session/playback metadata; tmp profiles/downloads; Playwright
output, Vite/UV/XDG/Playwright caches, share-control.json and .owner-start.
Existing page/document finally plus outer marked-process/root finally clean on
failure/success. No captures/video/traces retained. Ordinary small test/guard
caches remain per policy. No user workspace output.

Root `/tmp/__e2e__history-p8_yyo9o` removed by launcher and independently absent;
no accessible marked process, no workspace fixture, no port listener; 8004/5177
accept server-style binds. Protected environments unreadable are reported in
closeout; no claim to inspect them. Removed bytes not measured before automatic
cleanup; no raw artifacts retained.

**21/38 complete; 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged.**
S20 Twist controls/toolbar acceptance is the sole successor in the handoff,
unstarted. FH-20/FH-27/ISSUE-100/MV-48 remain open; ISSUE-145 stays fixed.

Final checks: memory lint 0 errors/0 warnings; diff and JS syntax checks pass; 283 current file links resolve (anchors not exhaustive). Ledger 38 unique /21 Done/9 Parked/8 open core, sole successor S20. 31 protected process environments were unreadable during cleanup.
