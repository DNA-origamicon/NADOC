---
name: selection-behavior-matrix
description: "Phase-0 characterization matrix for the mature selection model migration. Records current entry paths, state endpoints, consumers, fallbacks, and regression coverage."
metadata:
  node_type: memory
  type: project-support
  status: active
  authority: supporting
  created: 2026-08-12
---

# Selection behavior matrix

Companion to [project_selection_model.md](project_selection_model.md). Update this
matrix whenever a selection kind, representation, or command consumer changes.

## Canonical entry-path matrix (current behavior)

| Logical kind | Plain/fixed 3D | Default drill | Additive/lasso | Sidebar/programmatic | Current endpoint | Known divergence / fallback |
|---|---|---|---|---|---|---|
| Cluster | cluster level | n/a | canonical toggle/extend | cluster panel `selectCluster`/`toggleCluster` | `selection.items: cluster[]` | Member strands are derived highlight relations, never selected refs. |
| Strand | strand level | first click | canonical toggle/extend | spreadsheet, histogram, groups, `selectStrand` | `selection.items: strand[]` | None known. |
| Domain | domain level | cylinder/surface leaf fallback | canonical toggle/extend | related-target consumers | `selection.items: domain[]` | Representation fallback remains explicit behavior. |
| Base | base level | second default-drill click | canonical toggle/extend | `selectNucleotide`, transform/anchors | `selection.items: base[]` | Fixed Base and default drill share the same base-key endpoint. |
| End | end level | n/a | canonical toggle/extend | end tools | `selection.items: end[]` | Alt-click measurement anchors remain separate transient state. |
| Crossover / forced ligation | xover level/arc | cone/arc leaf | canonical toggle/extend | context/Delete helpers | `selection.items: crossover[]` with subtype | Live arc objects are renderer adapters only. |
| Overhang | overhang filter | n/a | canonical toggle/extend | overhang list/manager | `selection.items: overhang[]` | Domain/strand are derived relations. |
| Extension | extension filter | n/a | canonical toggle/extend | extension UI | `selection.items: extension[]` | Parent strand is a derived relation. |
| Protein | atom/coarse hit | n/a | canonical reducer supports cardinality | protein subsystem | `selection.items: protein[]` | Gesture multi-entry is not currently exposed. |
| Assembly instance | assembly pointer | n/a | `multiSelectedInstanceIds` | assembly panel | assembly-owned fields | Explicit Phase 9 boundary; never a design ref. |

## Entry-path parity requirements

Legend: `covered` has a focused test; `partial` has helper/unit coverage but no complete
gesture parity assertion; `gap` needs characterization before migration.

| Kind | 3D/fixed | Default drill | Modifier | Lasso | Sidebar | Programmatic | Representation parity | Lifecycle/rebuild |
|---|---|---|---|---|---|---|---|---|
| Cluster | partial | n/a | covered | partial | covered | covered | partial | partial |
| Strand | covered | covered | covered | covered | partial | partial | partial | partial |
| Domain | covered | covered fallback | covered | covered | partial | gap | partial | partial |
| Base | covered | covered | covered | covered | n/a | covered | raycast-first coarse parity covered; atomistic partial | covered key pruning |
| End | covered | n/a | covered | covered | n/a | covered helper | partial | covered projector/reconcile |
| Crossover | covered | covered | covered | partial | n/a | covered helper | partial | covered projector/reconcile |
| Overhang | covered | n/a | covered | covered | covered | covered | partial | partial |
| Extension | covered | n/a | covered | covered | partial | gap | partial | partial |
| Protein | partial | n/a | gap | gap | n/a | gap | partial | partial |

## State writer inventory

`frontend/src/scene/selection_controller.js` is the sole production writer of the
canonical `selection` field. The architecture gate scans production JavaScript for any
second writer and for every deleted compatibility-field name.

Private variables in `selection_manager.js` are renderer adapters (`_mode`, live entry
caches, live crossover arcs) or explicitly transient interaction state (`_ctrlBeads`,
hover, lasso UI). They are rebuilt from canonical refs and never establish logical
selection identity.

Assembly is explicitly separate: `activeInstanceId`, `multiSelectedInstanceIds`,
`activeGroupId`, `groupDiveStack`, assembly overhang A/B state, and private assembly
cluster/joint targets. The design controller is inert in assembly context.

## Major reader inventory

The baseline audit found split-field readers across 27 production modules. All design
consumers now use canonical refs or typed selectors, including:

- Properties and spreadsheet selection rendering.
- Delete and keyboard shortcuts.
- Command palette and context menus.
- Move/Rotate and nucleotide transform target resolution.
- Atomistic/surface highlighting.
- Overhang Connections, Overhangs Manager, Strand Animation, and sequence panels.
- Feature log and cross-window `selection-changed` events.
- API design reconciliation/pruning.

New consumers must use typed selectors; adding a parallel writable projection is an
architecture regression.

## Display identity contract

Selection refs retain stable internal IDs; UI consumers derive concise labels without
changing canonical identity:

- Strand display IDs are assigned from design-array order with independent 1-based
  series: staples `S#`, linkers `L#`, and every other strand type `X#`. Spreadsheet
  sorting does not renumber them.
- Selected ordinary bases render as `Type - helix[bp]`, using an explicit helix label
  when present and the design's zero-based helix index otherwise. Base groups are
  clustered first by type, then helix, with runs of three or more compressed.
- `OH` includes overhang-domain bases and `oh_binder` strands. Extension and crossover
  insert bases use their parent helix plus an anchor-relative tail/insert ordinal because
  their canonical keys intentionally live on synthetic helices.
- `frontend/src/ui/design_display_labels.js` is the sole formatter shared by the strand
  spreadsheet and Properties panel. Canonical refs and serialized design IDs remain
  unchanged.

## Intentional resolution policy

- Full/Beads modes can resolve an individual base.
- Cylinder and Surface modes may have no individual bead pick target; default drill may
  resolve to the domain. The future picker must return an explicit capability fallback
  such as `{ ref: domainRef, fallbackFrom: 'base', reason: 'representation-granularity' }`.
- Hidden or stale meshes must never become logical selection refs.
- Atomistic and overlay hits resolve back to the same design identity used by coarse
  representations.

## Regression gates

- `frontend/e2e/base_select.spec.js`: explicit Base gestures and default-drill/Base
  endpoint parity. The parity pin covers both canonical state and occlusion-correct
  target identity through the shared raycast-first `_baseCandidateAt` resolver.
- `frontend/src/scene/selection_architecture_characterization.test.js`: forbidden
  compatibility fields, sole-writer enforcement, mandatory controller, intent-only
  gesture paths, transient-anchor separation, and design/assembly boundary.
- Existing `selection_level.test.js`, `base_ref.test.js`, `base_pick.test.js`,
  `properties_panel.test.js`, and transform/anchor tests cover selection-level policy,
  key identity, picking families, and current consumers.
- `design_display_labels.test.js` pins strand numbering, helix labels, type clustering,
  range compression, and synthetic-base labels; `design_display_labels.spec.js` verifies
  spreadsheet-to-Properties parity through the running app.

## Ratified product decisions (Phase 1 complete)

1. End is its own base-keyed kind.
2. Forced ligations are crossover subtypes.
3. Primary is the most recently explicitly selected survivor.
4. Sole-item re-click clears at fixed levels; default drill stays hierarchical.
5. Overhang is the sole selected ref; its domain is a related selector.
6. Selection level resets to `default` across reloads and context changes.
