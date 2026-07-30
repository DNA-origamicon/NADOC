# Plan-Audit Ledger — archive

Closed rows moved out of `plan_audit_ledger.md` to keep the head lean (per its own ~200-line
rule and `CLAUDE.md` → context economy). **Never read this in a routine `/audit-plan` pass** —
open it only to mine a specific past verdict. The head carries the taxonomy, rubric, queue,
HOLDs, handoff and standing lessons.

## Results — plans audited 2026-07-24 / 07-25 (all terminal)

| Date | Plan | Codebase evidence | Verdict | Action |
|---|---|---|---|---|
| 07-24 | project_sequence_clear_fix | Reversal already shipped (`routes_assign_sequences.py`, pinned by `test_assign_staple_preserves_overhang_seq.py`); plan's own head says SUPERSEDED | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_advanced_staple_disabled | `optimize_staples_for_scaffold` bypassed at call site (perf); feature switched off, no resume intent | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_assembly_overhaul | "Planning — no implementation started" (2026-04-17); superseded by the shipped assembly system (`path_to_thousands`, `assembly_part_context`) | SUPERSEDED-DOCUMENTED | Deleted + pointer scrubbed (successors documented) |
| 07-24 | project_ball_joint | "Scoped only; no code yet" Phase-2 UX; `ClusterJoint.joint_type` still `Literal['revolute']` — never widened | DERELICT | Deleted + pointer scrubbed |
| 07-24 | project_blade_frontend | Already ARCHIVED 2026-07-20; modules kept dormant, one-line revive | DORMANT-REVIVABLE | Kept; banner firmed up |
| 07-25 | project_mate_connectors | Probe: create-mate route + router registered (`routes_assembly_joints.py:326`), `createMate`→`_alignAndAddJoint` single round-trip, `_defineAssemblyMate` wired to UI, blunt ends live on BOTH renderer paths. Of 4 listed defects: cache-invalidation MITIGATED (`invalidateInstance` now called after `patchOverhangRotationsBatch`, though `_sourceKey` still blind to ovhg rotation); other 3 unchanged in code. Head's "extracted, shared by both" claim STALE — legacy keeps its own ~270-line inline copy | UNFINISHED-ACTIVE | Kept; **rank P1**; head status banner + open-items rewritten against the probe; stale extraction claim corrected; no-test-pin gap recorded |
| 07-25 | project_surface_strands | Probe: anchors 1–9 EXISTS+WIRED (builder→runner→route→field-exclusion→display→UI/overlay+tests). Feature shipped 2026-07-17, not deferred. Gaps: `oxdna_design_fingerprint` omits capture state; `validate_capture_build` tests-only | UNFINISHED-ACTIVE | Kept; **rank P3**; head banner + open-items rewritten; **fixed stale MEMORY.md hook** (said "DEFERRED to Phase 2" — was shipped) |
| 07-25 | project_mate_connectors | Probe: ALL implemented anchors EXIST+WIRED (create_mate→route, _propagate_fk_inplace/_compose_add_joint shared, `assembly-create-mate` in SnapshotOpKind, shared+legacy `getInstanceBluntEnds` both live, no `()=>[]` stub). Feature ships. Locations drifted (routes_assembly_joints/geometry.py, scene/, ui/overhang_orientation_panel.js). 1 of 4 "known issues" (cache invalidation) FIXED — `_ooApplyDelta` now calls `invalidateInstance`+`rebuild`; 3 connector-placement bugs survive | UNFINISHED-ACTIVE | Kept; **rank P2**; head banner + relocations + open-items rewritten (cache issue struck as RESOLVED); MEMORY.md hook updated |
