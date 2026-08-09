---
type: project
status: active
authority: canonical
review_after: 2026-09-01
---
# Tech-debt ledger

Driver for the `/audit-debt` loop. Full item narratives and closed history are in
[the archive](project_tech_debt_archive.md). A debt item is a claim to probe, not a fact.

## Operating rule

Probe the named anchor before acting. Choose exactly one terminal result:

- **STALE** — anchor is gone, already fixed, or never existed.
- **FIXED** — small, safe, verified correction.
- **DELETED** — proven dead with zero callers and no unresolved product decision.
- **DECIDE** — user judgment is required.
- **PROMOTE** — real but large enough to require its own project/plan.
- **ACCEPTED** — deliberate state that should not be rediscovered.

Never invent scope. Deletion questions and retired-feature decisions go to the user.

## Queue

This head was reconciled against the detailed archive on 2026-08-08. Before that pass it stopped at
TD-16 even though TD-17 through TD-30 were active in the archive. The archive remains the narrative
store; this table is the authoritative active queue.

| Priority | Item | Current claim |
|---|---|---|
| P1 · parked | **TD-30** | Extra-base insert ring piercing. Dedicated topology session only; do not treat the 2026-08-07 suite totals as current without rerunning. |
| P1 | **TD-07** | Two scripts still call removed `auto_scaffold(design, mode=…)`; retire or port them. |
| P1 | **TD-08** | Divergent `CELLS_6HB` / `CELLS_18HB` fixture definitions still share misleading names. |
| P1 | **TD-09** | Deformation comments plus possible deformation loss in assembly flattening. |
| P1 | **TD-10** | `_arm_filter_cluster` still resolves cluster scope by list order. |
| P1 | **TD-11** | Autorefine route/function `finetune` defaults still disagree; unsigned ranking needs a product/algorithm pass. |
| P1 | **TD-12** | Selection comments/state writes need re-probing after the 2026-08-08 selector UI change. |
| P1 | **TD-23** | Duplex-foundation stragglers and the zero-caller sequence reassignment helper. |
| P2 | **TD-13–TD-20** | API/state, Cadnano-2D, animation, unfold, strand-animation, fixture-skip, dead-module, and composition-root stragglers. Process one item at a time from the archive. |
| P2 · blocked | **TD-28** | Linker/relax audit waits for an explicit unblock after the basic-design geometry settlement. |
| P2 | **TD-24–TD-26** | Photo-mode v1 residue, lint scope, and undeclared `unligatedCrossoverIds` store state. |
| P3 · blocked | **TD-21** | Delete legacy OverhangSpec pose overlay only after duplex-cluster migration. |
| P3 · promote | **TD-22** | Rule coverage program; this is a project, not a small debt fix. |

**Closed 2026-08-08:**

- **TD-06.** The stale `docs/triage/` corpus was deleted after a repo-wide probe; its phantom
  `MAP_*.md` citations disappeared with it. Remaining bullets are owned by TD-09/12/13/14/15/16.
- **TD-27 — SUPERSEDED-DOCUMENTED.** The shared `HelicalSite` architecture shipped through phases
  0–10 on 2026-08-07, followed by removal of legacy slab positioning and full/atomistic coordinate
  alignment on 2026-08-08. Live invariants are owned by `project_helical_site.md` and
  `project_atomistic_source_of_truth.md`; unresolved insert topology is TD-30.

## Decisions requiring the user

The archive retains the full `DEC-*` questions. Before processing a decision, copy its current
one-question framing into this head, obtain the answer, then archive the resolution.

## Per-iteration verification

- Backend code → `just test-smart`.
- Frontend code → `just test-frontend` plus app exercise or `NOT VERIFIED IN APP`.
- Prose-only resolution → no tests; state that explicitly.
- Deleted tested behavior → identify removed tests and remaining coverage.

## Next handoff

Process **TD-07** next. Do not start TD-28 or TD-30 as part of that pass. For any other pickup,
read only that item's detailed section in `project_tech_debt_archive.md` and verify every anchor
before editing code.
