# Audit queue — empty — supporting detail

[Topic head](../../plan_audit_ledger.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Audit queue — empty

All former candidates below reached terminal verdicts on 2026-07-30/31. The crossed-out list is
historical evidence and must not be interpreted as actionable work.

Genuinely-unfinished-with-intent candidates (likely UNFINISHED-ACTIVE, need rank):
- ~~project_regional_autorefine~~ (LIVE-REFERENCE 07-30),
  ~~project_deformation_cluster_scope~~ (LIVE-REFERENCE 07-30),
  ~~project_cadnano_overhaul~~ (SUPERSEDED-DOCUMENTED, deleted 07-30),
  ~~project_assembly_part_context~~ (UNFINISHED-ACTIVE, P2, 07-30) —
  Phase-1-shipped, later-phase-deferred band is now **empty**.
  (`memory/trajectory_keyframes` was listed here but **the file does not exist** — the queue entry
  was fiction, struck 07-30. Nothing named `traj*`/`*keyfram*` is in `memory/`.)

Small-tail / verify-if-superseded:
- ~~project_overhang_sequence_display~~ (UNFINISHED-ACTIVE, **P2**, 07-31 — every anchor alive; the
  probe found a live overlay bug the doc couldn't know about),
  ~~project_assembly_groups~~ (UNFINISHED-ACTIVE, P2, 07-30),
  ~~project_ux_overhaul~~ (UNFINISHED-ACTIVE, **P2**, 07-31 — 2 "SHIPPED" entries describe deleted code),
  ~~memory/pipeline_validation_log~~ (SUPERSEDED-DOCUMENTED, deleted 07-31 — its "NOT YET
  VALIDATED" label was false in both directions; successor `crossover_parameterization`),
  ~~photo_mode_audit_plan~~ (root; SUPERSEDED-UNDOCUMENTED, deleted 07-30),
  ~~project_overhang_duplex_foundation~~ (UNFINISHED-ACTIVE, P1, 07-30)

Surfaced BY the 07-30 duplex pass (three duplex-blind or wrong-tense siblings — see its row):
- ~~project_overhang_duplex_cluster~~ (UNFINISHED-ACTIVE, **P2**, 07-31 — head was tense-wrong; shipped),
  ~~project_overhang_connections_panel~~ (UNFINISHED-ACTIVE, **P2**, 07-31 — every anchor alive;
  wrong only by undercount), ~~project_overhang_subdomains~~ (UNFINISHED-ACTIVE, **P2**, 07-31 — Phase 5's
  bind-locks-joint was reverted 05-14; Phase 6 shipped as `strand-anim`)

Ongoing loop-drivers — **out of scope, do not audit** (they're never "done" by design):
backend_router_carveup, main_js_carveup, design_automation_backlog, issues_ledger,
manual_validation_debt, SIM_COVERAGE_PLAN, project_cando_fem, project_atomistic_propagator.

## Path-scoped rule sweep — frontmatter triage (done 2026-07-30, reuse it)

Glob-vs-`ls` check of all 9 unaudited rules. **Don't re-run this; it's the ranking.**

| Rule | Frontmatter verdict |
|---|---|
| ~~`cadnano-2d`~~ | **REWRITTEN 07-30.** Glob `frontend/src/cadnano/**/*.js` matched **zero files** |
| ~~`cadnano-editor`~~ | **NEW 07-30** — 10,713 LOC that no rule covered at all |
| ~~`animation`~~ | **REWRITTEN 07-30.** `backend/api/animation*.py` matched **zero files**; body described a feature that never shipped |
| ~~`selection`~~ | **REWRITTEN 07-30.** Single glob missed 3 extracted siblings; body had a dangling `MAP_SELECTION.md`, a mechanically wrong deform gate, and 4 undercounted API surfaces |
| ~~`api-and-state`~~ | **REWRITTEN 07-30.** Globs resolved fine — the *body* was built on two symbols that don't exist, and its route index covered 13% of the API with 10 dead entries |
| ~~`main-init`~~ | **REWRITTEN 07-30.** Glob resolved fine — and the body was the worst yet (30/30 wrong line anchors, 6 dead symbols, a CRITICAL section guarding a subscriber that doesn't exist). **This retires the glob heuristic entirely**: a clean glob predicts nothing |
| ~~`rendering`~~ | **REWRITTEN 07-30.** Globs resolved fine — and the diagram's two central meshes (`iFwd`/`iRev`) never existed; 2 of 5 globbed files were never mentioned in the body |
| ~~`deformation`~~ | **REWRITTEN 07-30.** Globs resolved fine — the body's `CRITICAL` invariant was a **no-op** (obsoleted by `Design.copy_with`), its dependency direction was inverted, and it omitted the entire cluster-scoping dimension |
| ~~`unfold`~~ | **REWRITTEN 07-30.** Glob resolved — but it globbed **1 file of the 3** in the subsystem, and 3 of its 4 cross-feature claims were dead or **reversed** |
| ~~`strand-anim`~~ | **REWRITTEN 07-30.** Globs resolved *and* were correctly scoped (first pass needing no glob change) — and the body was the most accurate of the 11. Its one blind spot was structural: the "drop-in" it describes in the future tense **already shipped**, and it names none of its 4 production importers. **Sweep complete: 11 of 11 rules audited.** |

**Do not widen a stale rule's globs without auditing its body** — that just auto-loads wrong guidance
onto *more* files. Glob fix and body rewrite go together, in one pass, per rule.
