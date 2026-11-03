# S20 — Twist controls and toolbar parity, October 17, 2026

Parent FH-20, supporting FH-27. Current handoff/memory/ledger reread after S19
closeout; baseline remains `96ab701e`, other changes preserved. Acceptance target
recorded before editing: two new Twist browser cases for units/handedness/reversed
planes with exact persisted input and toolbar explicit-selection Change/Clear/
Cancel/Apply/undo/reopen. Maximum two diagnostic invocations, strict console,
60-second case budget, no geometry or input-semantics change.

Parameterized existing toolbar case over Bend/Twist, retaining Bend assertions
and strengthening both with exact browser preservation on Cancel, numeric input
reopen and root disposal. Twist creation asserts exact total-angle params. Added
Twist history control case: total +24 → LH -24 → degrees/nm -24 → -3.5, reversed
planes normalize to 6/30, final per-nm operation persists unchanged after one
Apply, save/undo/redo/load and popup reopen. Checks actual radio controls and
persisted sign/units only; no new molecular handedness judgment or golden.

## Actual validation

- Guarded Vitest: `src/ui/bend_twist_popup.test.js`,
  `src/ui/deformation_tool_launcher.test.js`,
  `src/app/deformation_history_editor.test.js`: **33 passed**, 3 files, 2.32 s.
- `NADOC_HISTORY_E2E_GREP='toolbar creation|twist history units' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`:
  **3 passed in 42.8 s**, one invocation. Bend toolbar 13.1 s, Twist toolbar
  12.4 s, Twist history controls 12.1 s. Exact state/saved-byte preservation,
  one publication/history/revision, operation/feature identity rules, undo/reopen,
  strict empty console, no legacy mutations and zero disposed roots pass.
- Launcher preflight `/tmp`, 661 GiB free; installed browser and free ports.
  JS syntax and diff checks pass. No production or fixture source changed;
  no new broad/backend/smoke/scientific run. Historical full-run debt unchanged.

## Cleanup and limits

Before launch inventoried same root-only contract as S19: workspace fixture/
project/session/playback metadata, tmp profiles/downloads, Playwright output,
Vite/UV/XDG/Playwright caches, share-control.json and .owner-start. Fixtures use
`__e2e__`; page/document finally and launcher process/root finally cover failure
and success. No captures/video/traces retained; no user-workspace output.
Root `/tmp/__e2e__history-3p0umaq7` independently absent; no accessible marked
process or workspace fixture, no listeners, both 8004/5177 reusable. 32 protected
process environments unreadable, not claimed inspected. Removed bytes were not
measured before automatic cleanup. Ordinary small guard/test caches preserved.

Tiny-fixture control/toolbar parity now has browser evidence for both tools.
Other target kinds, eligible polymer, routing/Sweep chains, failed/lost/expiry/
disconnect cases, larger-host integration, full resources and paired rollout/
legacy pruning remain. Test elapsed times do not qualify interaction latency.
`main.js` delta 0; no production, gate, geometry, golden, commit or push changes.

**21/38 complete; 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged.**
S21 lost-Apply-reply recovery is the sole successor, unstarted. No full fixed
milestone exit is satisfied; active goal remains incomplete.

Final checks: memory lint 0 errors/0 warnings; diff and JS syntax checks pass; 284 current file links resolve (anchors not exhaustive). Ledger 38 unique /21 Done/9 Parked/8 open core; exactly one successor S21.
