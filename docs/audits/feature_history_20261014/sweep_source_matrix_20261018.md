# S53 — Sweep source-mode desktop matrix

October 18, 2026; HEAD `96ab701e` plus preserved accumulated worktree changes.
Parent FH-27/MV-51; completed FH-22 implementation credit is unchanged.
21/38 Done,17 remaining (8 core,9 parked), delta0; U1–U60 unchanged.

## Delivered scope

The exact native fixture now admits independent, attached-start and attached-end
sources; the detached case starts attached-end and moves its origin in the editor.
All retain a later authored Extrude. Poisoned/evicted recovery cannot supply replay.
The real worker independently reconstructs each edited recipe and compares complete
native authoring and geometry, later inputs/identities, Cancel, undo/redo and JSON proof.

Three actual app cases complement the existing attached-end case. They verify the
five prefix source options (new bundle plus two ends of each earlier helix), selected
source and plane availability; toggle ligation and restore it; edit endpoint length
and explicit orientation; preserve exact canonical design/history/redo on Cancel;
publish once; preserve every other saved input and the later Extrude; compare every
native nucleotide placement field and exact value; save/undo/redo/reopen/cold-proof.
Attached origins refuse orientation control. Moving an attached origin to X=1 then
back to X=0 retains explicit detach state and original source identity, including
on reopening. Strict normal-console assertions remain empty.

Source selection inventory is checked, not source switching. Original cells are
preserved, not changed by a canvas gesture. Other planes/strand filters, native
picking/transforms, warning/failure/race variants, large recipes and latency remain
unqualified. Numerical replay is not independent scientific validation. No production
behavior, geometry algorithm, constants, golden, deadline or rollout gate changed.

## Validation actually run

Heavy checks ran serially under repository guards; `/tmp` preflight reported661GiB.

| Command / selection | Result |
|---|---|
| `just test-focused tests/test_sweep_history_desktop_fixture.py` | Final4 passed,3.96s. Two observed earlier attempts each3 passed/1 failed: test incorrectly read DTO `params` instead of `sweep_preview.source_detached`; corrected test only. |
| `just test-focused tests/test_part_sweep_preview.py` |40 passed,3.45s; native source, detachment and fixed-origin rules. |
| `just test-focused tests/test_deformation_history_app.py` |22 passed,3 existing ORJSON deprecation warnings,5.57s. |
| Guarded installed Vitest: `src/test-helpers/deformation_history_launch.test.js src/app/sweep_history_editor.test.js src/ui/sweep_history_panel.test.js` |23 passed across3 files,1.57s. |
| `NADOC_HISTORY_E2E_GREP='Sweep' just validate-safe uv run python scripts/run_deformation_history_e2e.py` | Four related regressions passed: Bend→Sweep18.9s, Twist→Sweep18.8s, Bundle→Bend→Sweep20.3s, attached-end Sweep24.5s. New independent/start cases timed out; detached case interrupted after diagnosis. Exit130, not a suite pass. |
| Same launcher, grep `Sweep source matrix`, corrected ligation toggle order | Independent20.6s/start23.7s passed; detached failed at8.2s because the test captured the preceding Next evaluation (`detach_source=false`) instead of the origin move.2 passed/1 failed,58.9s. |
| Same three-case selection, final synchronized navigation and coordinate matching |3 passed,1.3min: independent20.6s, attached-start25.7s, detached25.3s. Clean consoles. |

The first browser attempt unchecks an already unchecked ligation box and waits for
an event that need not occur. Reversing the toggle sequence restores the original
input. The final tests also wait for Previous/Next evaluation and match origin
coordinates before asserting detachment. Every final saved parameter matches the
independent native oracle's input. The geometry helper aggregates missing-field
checks into one assertion while retaining all fields and exact values (the S52
approach); the original attached-end regression passes with this helper. No timing
limit was increased. Test durations are not interactive-latency measurements.

No new full frontend, backend selector or production smoke was required/run for
these test-only changes. Existing FULL debt and S47 sealed-startup403 debt remain.
All six relevant source rollout flags remain false. `main.js` delta is zero.

## Artifact inventory and cleanup

Each browser run owns its fresh workspace/project files, browser profiles/downloads,
Vite/Playwright/UV caches and reports under one launcher root. Captures are off;
fixture files are `__e2e__` prefixed. Fixture teardown deletes its document; launcher
finally stops marked children and removes the root even on failure/interruption.
The first attempt was explicitly stopped only after identifying its test defect;
terminal status and cleanup were observed before restarting.

Launcher reported all roots absent:
`/tmp/__e2e__history-6e8jnae8`, `/tmp/__e2e__history-_wn7tnwt`,
`/tmp/__e2e__history-nfng3h9r`. Independent final cleanup and static checks follow.

## Sole successor

S54 — Sweep downstream-nick success/refusal desktop workflow, FH-27/MV-51,
unstarted. The [handoff](session_handoff.md#next-bounded-task) defines the exact
two-case deliverables, files, checks, exclusions and stop condition. No successor
implementation began. Four-tool completion remains ahead of other areas.

## Final verification

Independent inspection confirms all three browser roots absent and no accessible
process cwd/open-file/maps/environment references to them or the retained owned
pytest roots.31 protected/exited processes were unreadable; no claim is made about
those environments. Ports8004/5177 accept server-style binds. Inspected pytest-4/5/6
contained only module-workspace/workspace entries,0 file bytes; removed them and
their current symlink. Pytest retention had already removed earlier roots from
this task. Old pytest-0 and shared caches remain untouched.

`just lint`, `node --check frontend/e2e/sweep_history.spec.js`, `git diff --check`
and `just lint-memory` pass (memory0 errors/0 warnings). Eight current handoff/report
links resolve; seven current status records and both tool plans selectS54. The
ledger still has21 Done rows. All six source gates are false; `main.js` is unchanged.
No commit/push. Unrelated accumulated changes remain intact.
