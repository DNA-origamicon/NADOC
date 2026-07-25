# Plan-Audit Ledger — reconcile stale plans against live code

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

## Priority rubric (UNFINISHED-ACTIVE only)

Rank = **value × closeness × still-relevant**, mapped to one bucket:

- **P0** — high value, most of the way done, still clearly wanted → do next.
- **P1** — worth doing, non-trivial remaining work, still relevant.
- **P2** — nice-to-have, or large remaining work, or relevance softening.
- **P3** — someday/maybe; keep the doc but don't pull it forward.

Put the rank in the plan's head (`**Rank:** P1 — <one-line why>`) and in its `MEMORY.md` hook.

## How one iteration runs

See `.claude/skills/audit-plan/SKILL.md`. Short form: pick target → probe codebase (delegate
the grep sweep to a read-only, no-git subagent — it returns anchor-by-anchor alive/dead + any
superseding module) → classify → act → record row → overwrite handoff. Doc-only work; no tests
unless a migration touches code.

---

## Results (audited)

| Date | Plan | Codebase evidence | Verdict | Action |
|---|---|---|---|---|
| 07-24 | project_sequence_clear_fix | Reversal already shipped (`routes_assign_sequences.py`, pinned by `test_assign_staple_preserves_overhang_seq.py`); plan's own head says SUPERSEDED | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_advanced_staple_disabled | `optimize_staples_for_scaffold` bypassed at call site (perf); feature switched off, no resume intent | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_assembly_overhaul | "Planning — no implementation started" (2026-04-17); superseded by the shipped assembly system (`path_to_thousands`, `assembly_part_context`) | SUPERSEDED-DOCUMENTED | Deleted + pointer scrubbed (successors documented) |
| 07-24 | project_ball_joint | "Scoped only; no code yet" Phase-2 UX; `ClusterJoint.joint_type` still `Literal['revolute']` — never widened | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_blade_frontend | Already ARCHIVED 2026-07-20; modules kept dormant, one-line revive | DORMANT-REVIVABLE | Kept; banner firmed up |
| 07-25 | project_surface_strands | Probe: anchors 1–9 EXISTS+WIRED (builder→runner→route→field-exclusion→display→UI/overlay+tests). Feature shipped 2026-07-17, not deferred. Gaps: `oxdna_design_fingerprint` omits capture state; `validate_capture_build` tests-only | UNFINISHED-ACTIVE | Kept; **rank P3**; head banner + open-items rewritten; **fixed stale MEMORY.md hook** (said "DEFERRED to Phase 2" — was shipped) |

## HOLD — flagged to user, decision pending

- **project_bundle_stiffness_params** — user said "delete", but the 0T track is a **completed,
  live parameter DB** (`backend/data/parameters/bundle_stiffness.json`) and this file is the
  only prose for its schema/units/provenance. Provisional verdict **LIVE-REFERENCE** (trim to a
  0T reference, drop the abandoned-1T narrative), NOT delete. Awaiting user OK.
- **project_periodic_md** — user said "archive pending revival", but the **backend workflow
  (`periodic_cell.py`, `namd_solvate.py`) is live**; only the frontend previewer was removed
  (already noted in-file, 2026-07-08). Provisional verdict **LIVE-REFERENCE**, NOT archive.
  Awaiting user OK.

## Audit queue (unaudited — rough priority top-first)

Genuinely-unfinished-with-intent candidates (likely UNFINISHED-ACTIVE, need rank):
- project_mate_connectors — known-broken, undiagnosed (may be DERELICT if not wanted)
- project_mixed_representation — PATH A in progress, unverified in app
- project_simulate_panel_overhaul — in progress
- project_dumbbell_autoscaffold — "tests pass, visual still wrong"
- project_protein_attachment — 2 helpers pending
- project_regional_autorefine, project_deformation_cluster_scope,
  project_cadnano_overhaul, project_assembly_part_context, memory/trajectory_keyframes —
  Phase-1-shipped, later-phase-deferred (rank each)

Small-tail / verify-if-superseded:
- project_scaffold_router (TODO section), project_overhang_sequence_display (caveat),
  project_assembly_groups (Escape not wired), project_ux_overhaul (deferred flow work),
  memory/pipeline_validation_log (NOT YET VALIDATED), photo_mode_audit_plan (root),
  memory/project_overhang_duplex_foundation (bulges deferred)

Ongoing loop-drivers — **out of scope, do not audit** (they're never "done" by design):
backend_router_carveup, main_js_carveup, design_automation_backlog, issues_ledger,
manual_validation_debt, SIM_COVERAGE_PLAN, project_cando_fem, project_atomistic_propagator.

## Next-session handoff

▶ **NEXT:** `project_mate_connectors` — head says "user confirmed unspecified issues remain,
suspected structural problems, not yet diagnosed." Probe: does `mate_connectors` code exist and
is it wired into any live path (grep `mate_connector` in `backend/`, `frontend/src/`)? Decide
DERELICT (broken + abandoned, no live callers) vs UNFINISHED-ACTIVE (wired but buggy → rank +
record the known breakage as the open item). This one likely needs a user call on whether the
feature is still wanted.

**Standing HOLDs (user-owned decision, do not touch):** `project_bundle_stiffness_params`,
`project_periodic_md` — both LIVE-REFERENCE, parked in the HOLD block above.
