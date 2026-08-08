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

Current next item is **TD-06, cross-cutting sweeps**:

1. Probe and retire or relocate the fictional/stale `docs/triage/` material.
2. Remove or repoint phantom `MAP_*.md` citations.
3. Sweep vestigial `null` composition-root initialization arguments.
4. Repair stale “keep in sync” comments by pointing to the real owner.
5. Replace line-number anchors in auto-loaded rules with stable symbol names.

Following items, in priority order: TD-07 dead scaffold API references; TD-08 divergent bundle-cell
copies; TD-09 deformation stragglers; TD-10 cluster-scoped deformation; TD-11 autorefine defaults;
TD-12 selection; TD-13 API/state documentation; TD-14 Cadnano-2D; TD-15 animation; TD-16 unfold.

## Decisions requiring the user

The archive retains the full `DEC-*` questions. Before processing a decision, copy its current
one-question framing into this head, obtain the answer, then archive the resolution.

## Per-iteration verification

- Backend code → `just test-smart`.
- Frontend code → `just test-frontend` plus app exercise or `NOT VERIFIED IN APP`.
- Prose-only resolution → no tests; state that explicitly.
- Deleted tested behavior → identify removed tests and remaining coverage.

## Next handoff

Run `/audit-debt` on TD-06 only. Probe every occurrence repo-wide, do not silently delete the
documentation directory, and archive the resolved evidence after each bullet reaches a terminal state.
