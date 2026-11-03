
# Plan-Audit Ledger — completed reconciliation index

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

> **Loop complete 2026-08-08.** Every queued plan has a terminal verdict. There is no unaudited
> plan queue. The only unresolved entries are the three owner decisions under HOLD; ongoing loop
> drivers remain intentionally out of scope. The detailed result table below is retained as audit
> evidence, not as a current work queue.

Driver for the `/audit-plan` loop. **One plan per iteration.** Each iteration takes one
`memory/project_*.md` (or root plan file), probes the codebase for the concrete things it
names, decides whether it is still real, and then **either deletes it or keeps it with a
priority rank.** This is the head; move closed rows to `plan_audit_ledger_archive.md` when it
passes ~200 lines.

## Why this loop exists

The survey of 2026-07-24 found ~40 plan/topic files in three states — abandoned, unfinished,
done — but "abandoned per the file's own words" is not proof: a plan can *say* it's stalled
while the code it describes is live (e.g. `bundle_stiffness_params` 0T data, `periodic_md`
backend), or *say* it's a plan while a newer, undocumented module already shipped it. Only a
**codebase probe** settles it. This loop makes that probe systematic and drives each plan to a
terminal state: deleted, or kept with a rank and a refreshed open-items list.

## Verdict taxonomy (pick exactly one per plan)

| Verdict | Test | Action |
|---|---|---|
| **DERELICT** | Feature dropped/disabled; the code path it describes is gone, dead, or explicitly switched off with no intent to resume, AND nothing live depends on the doc. | **Delete** the file + scrub its `MEMORY.md` pointer. Record row. |
| **SUPERSEDED-DOCUMENTED** | The work was replaced, and the replacement is already covered by another topic file / REFERENCE. | **Delete** + cite the successor slug in the row + scrub pointer. |
| **SUPERSEDED-UNDOCUMENTED** | Replaced by shipped code, but that code is *not* well documented anywhere. | **Migrate** the load-bearing facts (paths, symbols, invariants) into the right topic/REFERENCE file *first*, then delete + scrub. The migration is the point. |
| **LIVE-REFERENCE** | The plan's "abandoned" framing is misleading — it documents code that is **live and in use**. | **Keep.** Trim the dead-plan narrative to a lean reference; drop the "unfinished" framing. **No rank.** |
| **UNFINISHED-ACTIVE** | Genuinely incomplete, and the remaining work is still wanted and still applies to the current codebase. | **Keep.** Assign a **priority rank** (below) + refresh the head's open-items list to match reality. |
| **DORMANT-REVIVABLE** | Shipped then intentionally shelved; code kept dormant for a one-line revive. | **Keep** with an `ARCHIVED (date)` banner + the revive path. **No rank.** |

Guard rail (the `bundle_stiffness` trap): **never delete a plan whose named files/symbols are
still live and wired** without first migrating what the doc uniquely explains. Grep before you
delete.

<a id="priority-rubric-unfinished-active-only"></a>
- [Priority rubric (UNFINISHED-ACTIVE only)](details/plan_audit_ledger/01-priority-rubric-unfinished-active-only.md#priority-rubric-unfinished-active-only)

<a id="how-one-iteration-runs"></a>
- [How one iteration runs](details/plan_audit_ledger/01-priority-rubric-unfinished-active-only.md#how-one-iteration-runs)

<a id="results-audited"></a>
- [Results (audited)](details/plan_audit_ledger/01-priority-rubric-unfinished-active-only.md#results-audited)

## HOLD — flagged to user, decision pending

- **`frontend/src/input/drag_scrub.js` — a user-approved UX feature vanished with no record.**
  `project_ux_overhaul` lists item 7 as SHIPPED and wired into 7 panels (polymerize, animation,
  extrude, camera, photo, bend/twist, main.js Move/Rotate). The module **does not exist** and
  `dragScrub`/`drag_scrub` has **zero hits in `frontend/src`** — none of the 7 panels reference
  it. No memory doc records a removal. Either it was deliberately dropped (then say so and the
  entry gets struck) or it was lost in the `main.js` carve-up (then it's a regression). **Only
  the user knows which.** Recorded in the plan's correction table 07-31.

- **project_bundle_stiffness_params** — user said "delete", but the 0T track is a **completed,
  live parameter DB** (`backend/data/parameters/bundle_stiffness.json`) and this file is the
  only prose for its schema/units/provenance. Provisional verdict **LIVE-REFERENCE** (trim to a
  0T reference, drop the abandoned-1T narrative), NOT delete. Awaiting user OK.
- **project_periodic_md** — user said "archive pending revival", but the **backend workflow
  (`periodic_cell.py`, `namd_solvate.py`) is live**; only the frontend previewer was removed
  (already noted in-file, 2026-07-08). Provisional verdict **LIVE-REFERENCE**, NOT archive.
  Awaiting user OK.

<a id="audit-queue--empty"></a>
- [Audit queue — empty](details/plan_audit_ledger/02-audit-queue--empty.md#audit-queue--empty)

<a id="path-scoped-rule-sweep--frontmatter-triage-done-2026-07-30-reuse-it"></a>
- [Path-scoped rule sweep — frontmatter triage (done 2026-07-30, reuse it)](details/plan_audit_ledger/02-audit-queue--empty.md#path-scoped-rule-sweep--frontmatter-triage-done-2026-07-30-reuse-it)

## Final handoff

Do not run another routine `/audit-plan` pass from this file. Resolve the three HOLD decisions with
the owner, or add a newly discovered plan explicitly before restarting the loop. The material below
this note is the final 2026-07-31 handoff retained for provenance and is **superseded**.

<a id="superseded-final-session-notes"></a>
- [Superseded final-session notes](details/plan_audit_ledger/03-superseded-final-session-notes_archive.md#superseded-final-session-notes)

- [Superseded final-session notes — continued detail](details/plan_audit_ledger/03-superseded-final-session-notes_archive.md)

- [Superseded final-session notes — continued detail](details/plan_audit_ledger/04-superseded-final-session-notes_archive.md)

- [Superseded final-session notes — continued detail](details/plan_audit_ledger/05-superseded-final-session-notes.md)

<a id="standing-lessons-carry-forward--compressed-from-earlier-passes"></a>
- [Standing lessons (carry forward — compressed from earlier passes)](details/plan_audit_ledger/05-superseded-final-session-notes.md#standing-lessons-carry-forward--compressed-from-earlier-passes)

- [Standing lessons (carry forward — compressed from earlier passes) — continued detail](details/plan_audit_ledger/06-standing-lessons-carry-forward--compressed-from-earlier-passes.md)
