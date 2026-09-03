---
name: mature-selection-model
description: "Shipped architecture contract for canonical NADOC design selection, validation, regression gates, and the explicit assembly boundary."
metadata:
  node_type: memory
  type: project
  status: shipped
  authority: canonical
  review_after: 2026-11-12
  created: 2026-08-12
---

# Mature selection model

The design-selection migration is complete. This file is the concise contract future
sessions must read before changing selection state, picking, highlighting, Properties,
Delete behavior, Move/Rotate targets, filters, or cross-window selection sync.

Detailed phase notes and historical evidence are preserved in
[project_selection_model_archive.md](project_selection_model_archive.md). Consult that
archive only when investigating a past decision. The live entry-path matrix is
[selection_behavior_matrix.md](selection_behavior_matrix.md).

## Current model

```js
selection: {
  context: 'design',
  level: 'default',
  items: [{ kind: 'strand', id: 's1' }],
  primary: { kind: 'strand', id: 's1' },
}
```

- `frontend/src/scene/selection_ref.js` owns stable, serializable identity.
- `frontend/src/scene/selection_model.js` owns pure ordering, cardinality, toggle,
  reload, and reconciliation policy.
- `frontend/src/scene/selection_controller.js` is the sole production writer of the
  canonical store field.
- `frontend/src/scene/selection_manager.js` resolves gestures to controller intents and
  projects canonical refs onto live renderer geometry.
- Typed selectors feed Properties, Delete, transforms, menus, panels, automation, and
  cross-window sync.

Stable design kinds are `cluster`, `strand`, `domain`, `base`, `end`, `bond`,
`crossover`, `overhang`, `extension`, `protein`, and `nanoparticle`. Forced ligation is a crossover
subtype.

## Binding invariants

1. One canonical design-selection field; no writable compatibility projections.
2. Single selection means `items.length === 1`; there is no separate single slot.
3. `primary` is the most recently explicitly selected surviving ref.
4. `selection.level` is interaction policy, never a second identity representation.
5. Pickers resolve stable refs or explicit misses/fallbacks; they do not write state or
   paint renderers.
6. Only the controller/reducer mutates canonical selection.
7. Highlights are derived from canonical state plus live geometry and can rebuild
   without changing logical selection.
8. Hover, measurement anchors, lasso UI, and active transform sessions are transient
   tool state, not ordinary selection.
9. Consumers use typed selectors rather than decoding raw state shapes.
10. Replace, toggle, extend, clear, reload, and reconciliation are atomic transitions.
11. Refs contain stable IDs/keys, never mesh entries or Three.js objects.
12. Design reconciliation deterministically prunes stale refs while retaining survivor
    order and primary when possible.
13. Sidebar, keyboard, programmatic, fixed-level, and pointer paths for one entity must
    converge on the same endpoint.
14. The default strand-to-base drill and explicit Base mode share the exact base-key
    endpoint.
15. Architecture tests must reject legacy fields and any second direct writer.

## Ratified product decisions

- End is its own base-keyed ref kind.
- Forced ligations are crossover subtypes.
- Primary is the most recently explicitly selected survivor.
- Re-clicking the sole item clears it at fixed levels. Default drill remains
  hierarchical and may restart at strand.
- Overhang selection contains only an overhang ref; backing domain and strand are
  derived relations.
- Selection level resets to `default` across every reload and context change. It is not
  restored across files, workspaces, designs, or assemblies.
- Alt-click measurement anchors remain separate from canonical End selection.

## Design/assembly boundary

Assembly selection is intentionally a separate bounded subsystem. Its instance/group
hierarchy, group-dive navigation, instance-scoped cluster/joint targets, ordered
two-overhang workflow, and transform sessions do not fit the design ref vocabulary
without mixing selection and tool state.

- Entering assembly calls `selectionController.reload('assembly')`, producing an empty
  context sentinel and resetting level to `default`.
- The design controller is inert in assembly context, so hidden design gestures,
  reconciliation, and cross-window messages cannot repopulate design refs.
- Leaving assembly calls `selectionController.reload('design')`, again empty/default.
- Assembly retains `activeInstanceId`, `multiSelectedInstanceIds`, `activeGroupId`,
  `groupDiveStack`, and `assemblyOverhangSelection` in its own store slice. Private
  assembly cluster/joint targets remain pointer/transform-session state.
- Design refs never acquire assembly kinds, and assembly consumers never decode design
  refs.

This boundary does not declare assembly's split single/multi storage mature. A future
assembly modernization should create a dedicated `AssemblySelectionRef` vocabulary and
assembly controller, reuse pure reducer primitives where semantics match, and migrate
PartInstance/PartGroup first. Do not extend the design ref union with ambiguous assembly
IDs or reuse the design controller blindly.

## Completed phase ledger

| Phase | Result |
|---|---|
| 0 Characterization | Behavior matrix, writer/reader inventory, parity pins. |
| 1 Ref + reducer | Stable refs, reducer contract, all seven product decisions. |
| 2 Controller + compatibility | Atomic controller and temporary one-way projection. |
| 3 Base/strand/domain | Canonical first vertical slice and drill/Base parity. |
| 4 Overhang/extension | Canonical identity plus related target selectors. |
| 5 Cluster/transform | Cluster-only refs; member strands became derived relations. |
| 6 Remaining kinds | End, crossover subtype, protein, and bond refs. |
| 7 Derived visuals | One live-geometry highlight projector. |
| 8 Legacy removal | Seven fields, projection, fallbacks, readers, and writers deleted. |
| 9 Assembly decision | Explicit context boundary and controller isolation ratified. |

## Required validation

For every changed kind or consumer, cover the applicable matrix dimensions:

- Entry: 3D, fixed level, default drill, sidebar, programmatic.
- Cardinality: none, one, multiple, primary.
- Mutation: replace, toggle, extend, clear, stale-ref prune.
- Representation: Full/Beads, Cylinders, Surface, atomistic/overlay where supported.
- Lifecycle: geometry rebuild, design replace, undo/redo, deletion.
- Consumers: Properties, highlight, Delete/menu, Move/Rotate or relevant tool.
- Miss/fallback: empty space, hidden mesh, unsupported granularity.

Run at minimum:

```bash
cd frontend
npm test
npm run build
npx playwright test \
  e2e/base_select.spec.js e2e/drill_v2_select.spec.js \
  e2e/forced_ligation_key.spec.js e2e/cluster_selection_model.spec.js \
  e2e/overhang_selection_model.spec.js --reporter=list
```

For an assembly-boundary change also run:

```bash
cd frontend
npx playwright test e2e/assembly_select.spec.js --reporter=list
```

Always run `git diff --check`. The architecture characterization test is mandatory: it
scans production for forbidden compatibility fields, rejects a second canonical writer,
requires the manager controller, and pins the assembly boundary.

## Completion evidence (2026-08-12)

- 307 frontend unit-test files / 5,524 tests passed on the rebased tree.
- Production build passed.
- 14/14 representative design-selection WebGL gestures passed.
- 3/3 assembly-selection boundary gestures passed.
- Spreadsheet-to-Properties display-ID browser exercise passed; the shared formatter's
  unit coverage includes strand numbering, helix/type clustering, range compression,
  and synthetic extension/crossover labels.
- Repository smoke gate passed (23/23).
- `git diff --check` passed.
- Memory lint still reports two unrelated pre-existing missing-index entries
  (`project_crossover_catenation.md`, `project_nucleotide_transform.md`); this plan and
  its archive are discoverable.

## Future-session protocol

1. Read this head and inspect the current matrix; avoid the archive unless historical
   rationale is needed.
2. Preserve unrelated shared-worktree changes.
3. Add or update matrix coverage before introducing a new kind, representation, or
   command consumer.
4. Keep mutations intent-only and visuals derived.
5. Run focused tests during work, then the full unit/build/WebGL gates above.
6. Update this head only for current invariants, decisions, evidence, or next actions;
   move detailed history to the archive.
