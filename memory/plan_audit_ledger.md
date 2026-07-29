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
| 07-25 | project_mate_connectors | Probe: create-mate route + router registered (`routes_assembly_joints.py:326`), `createMate`→`_alignAndAddJoint` single round-trip, `_defineAssemblyMate` wired to UI, blunt ends live on BOTH renderer paths. Of 4 listed defects: cache-invalidation MITIGATED (`invalidateInstance` now called after `patchOverhangRotationsBatch`, though `_sourceKey` still blind to ovhg rotation); other 3 unchanged in code. Head's "extracted, shared by both" claim STALE — legacy keeps its own ~270-line inline copy | UNFINISHED-ACTIVE | Kept; **rank P1**; head status banner + open-items rewritten against the probe; stale extraction claim corrected; no-test-pin gap recorded |
| 07-25 | project_surface_strands | Probe: anchors 1–9 EXISTS+WIRED (builder→runner→route→field-exclusion→display→UI/overlay+tests). Feature shipped 2026-07-17, not deferred. Gaps: `oxdna_design_fingerprint` omits capture state; `validate_capture_build` tests-only | UNFINISHED-ACTIVE | Kept; **rank P3**; head banner + open-items rewritten; **fixed stale MEMORY.md hook** (said "DEFERRED to Phase 2" — was shipped) |
| 07-28 | project_mixed_representation | Probe: PATH A **shipped**, not in-progress — model+`Design.representation_overrides` [models.py:1054,2275], routes moved crud.py→`routes_display_metadata.py:117/142` (registered), 13 backend tests (doc said 9), `resolveRepOverrides`+`editOverridesForSegments`, `_installInstanceAlpha`/`_applyRepOverrides`, `_applyRepresentationOverrides` (setDetailLevel re-sync intact), `_appendRepresentationMenu` ×6 sites, F-key master reset moved main.js→`ui/representation_switcher.js:256`, `initAtomSurfaceDisplay` wired at main.js:2442. UI was listed "pending" — it shipped. `editOverridesForStrands/ForClusters` named as shipped **do not exist** (column pivot replaced them). Real gaps: curved `_curvedCylGroup` + impostor beads uncovered, `iLinkerBindingCylinders` global-LOD only, no `representation_overrides.test.js`, photo mode reads overrides nowhere (+ suspected bead-`discard` bug from `_withHighDetailGeometry` swapping in `hd.bead` with no `instanceAlpha`). No superseding mechanism exists | UNFINISHED-ACTIVE | Kept; **rank P1**; head banner + code-location table rewritten, stale symbol/test-count/path claims corrected, 8-item live open-list appended; MEMORY.md hook updated |
| 07-28 | project_simulate_panel_overhaul | Probe: Phase A/B **shipped+live** (`#simulate-body`←main.js:2413, `collapsible:false` ×6 panels, `engine_selector` tabs+strip, periodic_md_panel/overlay ABSENT). Phase C **half done**: foundation `job_run_control.js` live (3 importers), oxDNA `_runControl`:1201 + NAMD `mdRunControl`:176 (always-RUN, `#md-jobs-job-ctl-btn` handler:2214) wired — but **mrDNA + CanDo entirely unstarted** (no `job_run_control` import; coarse/fine/stop trio at mrdna:202/cando:268). Master card partial: `#md-jobs-progress` GONE, but `#mrdna-jobs-progress`/`#cando-jobs-progress` still un-hidden+painted (mrdna:416, cando:603) → two bars visible; `masterStepText`:187 exported with no consumer outside its test. Doc's test paths wrong (`tests/`, not `backend/tests/`); anchors event payload richer than documented (halo reads `highlighted`). No supersession — `md_sidebar_audit` owns only NAMD's half | UNFINISHED-ACTIVE | Kept; **rank P1**; 880-line file split → lean head + `_archive.md`; head rewritten as status banner + 15-row code-location table + 7 live open items; MEMORY.md hook updated |
| 07-25 | project_mate_connectors | Probe: ALL implemented anchors EXIST+WIRED (create_mate→route, _propagate_fk_inplace/_compose_add_joint shared, `assembly-create-mate` in SnapshotOpKind, shared+legacy `getInstanceBluntEnds` both live, no `()=>[]` stub). Feature ships. Locations drifted (routes_assembly_joints/geometry.py, scene/, ui/overhang_orientation_panel.js). 1 of 4 "known issues" (cache invalidation) FIXED — `_ooApplyDelta` now calls `invalidateInstance`+`rebuild`; 3 connector-placement bugs survive | UNFINISHED-ACTIVE | Kept; **rank P2**; head banner + relocations + open-items rewritten (cache issue struck as RESOLVED); MEMORY.md hook updated |

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

▶ **NEXT:** `project_dumbbell_autoscaffold` — head says "tests pass, visual still wrong," which is
the one failure mode this loop hasn't hit yet: green tests over a wrong result. Probe the dumbbell
routing entry point + whatever oracle its tests assert on, and decide whether the visual defect is
still reproducible in current code (→ UNFINISHED-ACTIVE, rank by how load-bearing dumbbell routing
is) or was fixed by later scaffold-router work (→ SUPERSEDED-*; check `project_scaffold_router` and
`project_seamless_router` for the successor). If the "visual still wrong" claim can't be reproduced
from the code alone, park the reproduction question under HOLD rather than guessing.

*Pattern worth carrying (now 4 for 4 — `surface_strands`, `mate_connectors`, `mixed_representation`,
`simulate_panel_overhaul`):* the plan's own status text is stale in **both** directions.
`mixed_representation` claimed "UI pending" (it shipped) *and* claimed two shipped helpers that no
longer exist; `simulate_panel_overhaul`'s newest block claimed four progress bars were all still
rendered-but-hidden — NAMD's was deleted and mrDNA's/CanDo's are *visible*. Diff every head claim
against the probe line-by-line; never trust the top-line banner. Corollary: probes keep finding
**paths** moved by the carve-ups (crud.py → routes_*, main.js → ui/*) and **test paths** that were
never right — a code-location table in the head is worth more than the prose around it.

*New this pass:* a plan whose head has grown into a reverse-chronological work log (880 lines here)
should be **split head/archive as part of the audit** — the rank and the live open-items list are
unreadable buried under 40 dated ⚡ blocks. Splitting is mechanical and is the audit's deliverable
as much as the verdict is.

**Standing HOLDs (user-owned decision, do not touch):** `project_bundle_stiffness_params`,
`project_periodic_md` — both LIVE-REFERENCE, parked in the HOLD block above.
