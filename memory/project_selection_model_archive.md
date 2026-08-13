---
name: mature-selection-model-archive
description: "Historical phase-by-phase record for the shipped mature design-selection migration."
metadata:
  node_type: memory
  type: archive
  status: historical
  authority: supporting
  review_after: 2026-11-12
  created: 2026-08-12
---

# Mature selection model migration

This is the completed migration record and ongoing architecture contract for selection.
Read it before
changing selection state, picking, highlighting, Properties, Delete behavior,
Move/Rotate targets, selection filters, or cross-window selection sync.

Phases 0–9 are complete. Future changes must preserve the canonical sole-writer,
derived-highlight, context-isolation, and regression-gate rules recorded here.

## Goal

Every way of selecting the same logical entity must reach the same canonical state:
3D click, default drill, fixed selection level, lasso, modifier click, sidebar row,
spreadsheet row, keyboard action, atomistic pick, coarse pick, and programmatic API.

Target shape (exact naming may be refined in Phase 1):

```js
selection: {
  context: 'design',             // assembly uses a separate bounded subsystem
  level: 'base',                 // interaction policy, not selected entity state
  items: [
    { kind: 'base', key: 'h1:42:FORWARD' },
  ],
  primary: { kind: 'base', key: 'h1:42:FORWARD' },
}
```

All entry points emit intents through one controller:

```js
selection.replace(refs, options)
selection.select(ref, options)
selection.toggle(ref, options)
selection.extend(refs, options)
selection.clear(options)
selection.setLevel(level)
```

Picking resolves screen input to normalized entity references. It does not write store
fields or paint renderers. Highlighting, Properties, Delete, transform targets, and
other consumers derive their behavior from canonical selection selectors.

## Historical baseline and known debt at migration start

Audit date: 2026-08-12.

Current state is divided among:

- `selectedObject` for most single selections.
- `multiSelectedStrandIds`, `multiSelectedDomainIds`,
  `multiSelectedOverhangIds`, `multiSelectedExtensionIds`,
  `multiSelectedClusterIds`, and `multiSelectedBaseKeys`.
- Private crossover-arc selection in `selection_manager.js`.
- Private `_ctrlBeads`, used for end/measurement-related behavior.
- Private `_mode`, `_strandId`, `_drillClusterId`, `_crossoverId`, and renderer
  entry caches.
- Imperative highlights applied separately by gesture paths.

At audit time there were 41 direct design-selection state writes and 27 modules
reading `selectedObject`. These counts are baseline diagnostics, not permanent test
expectations.

Known divergences:

1. Default strand-to-base drill and explicit Base mode formerly ended in different
   states. They were unified on 2026-08-12 through `multiSelectedBaseKeys`; preserve
   that parity during migration.
2. Public `selectNucleotide()` still creates `selectedObject.type='nucleotide'`, while
   interactive base selection uses base keys.
3. Overhang single selection occupies both `multiSelectedOverhangIds` and a domain
   `selectedObject`.
4. Extension single selection occupies both `multiSelectedExtensionIds` and
   `selectedObject`.
5. Cluster selection stores cluster identity while also copying member strands into
   `multiSelectedStrandIds` to drive highlighting.
6. Crossover single selection uses `selectedObject`; multi-selection uses a private
   arc collection.
7. End selection and measurement anchors rely on private bead state even though they
   represent different concepts.
8. Some external code writes `selectedObject=null` without clearing private selection
   mode or renderer state.
9. Single and multi selection are separate models joined by
   `_promoteSelectionToMulti()`.
10. Coarse, cylinder, surface, atomistic, overlay, sidebar, spreadsheet, and 3D
    gesture paths contain overlapping dispatch behavior.

Intentional capability fallback: cylinder/surface representations may lack a pickable
individual base and resolve a click to a domain. This must become explicit resolution
policy with a tested reason, not a second state model.

## Binding invariants

These apply in every phase:

1. **One entity, one reference.** The same logical entity has one normalized identity
   regardless of entry path or representation.
2. **One selected set.** Single selection is `items.length === 1`, not a separate
   storage mechanism.
3. **Primary is explicit.** Ordered selection and the primary item are defined; no
   consumer infers primary from an arbitrary legacy array.
4. **Level is policy.** `selection.level` controls what a hit resolves to. It does not
   create a distinct storage format.
5. **Picking is pure resolution.** Pickers return a `SelectionRef` or miss/fallback
   result and never mutate selection or renderer state.
6. **Mutations are centralized.** Only the selection controller/reducer writes
   canonical selection state.
7. **Visuals are derived.** Renderer highlights are projections of canonical state and
   current geometry; they can be rebuilt without changing selection.
8. **Tools are separate state.** Measurement anchors, hover preview, lasso rectangle,
   and active transform sessions are tool/transient state, not ordinary selection.
9. **Consumers use selectors.** Delete, Properties, Move/Rotate, menus, feature log,
   exports, and panels query typed selectors rather than decode raw fields.
10. **Atomic transitions.** No subscriber may observe a transient empty or mixed state
    during promote/toggle/replace operations.
11. **Serializable identity.** Canonical refs contain stable IDs/keys, never live mesh
    entries, Three.js objects, or disposable geometry references.
12. **Design reconciliation is deterministic.** After design replacement, deleted refs
    are pruned and surviving refs retain order/primary consistently.
13. **Context isolation.** Design and assembly selection cannot accidentally consume
    each other's refs. Assembly migration is a deliberate later decision.
14. **Accessibility and automation parity.** Sidebar/keyboard/programmatic selection
    must produce the same state and command availability as pointer selection.

## Normalized reference vocabulary

Phase 1 must ratify exact encodings. Expected logical kinds:

| Kind | Stable identity | Notes |
|---|---|---|
| `cluster` | cluster ID | Do not duplicate member strands into selected items. |
| `strand` | strand ID | Linker-half identity stays distinct unless a command explicitly expands it. |
| `domain` | strand ID + domain index | May carry derived overhang relation, not duplicate identity. |
| `base` | app-wide base key | Includes backbone, extensions, fluorophores, extra crossover bases, flexible arcs, and ss-linker bridges. |
| `end` | base key + end role if needed | Decide whether this is a base ref plus semantic selector or its own kind. |
| `bond` | ordered from/to base keys + optional owner strand | Stable identity for a selectable backbone connection; renderer cones are only its visual hit target. |
| `crossover` | crossover/forced-ligation ID | Type/subtype is resolved from design state. |
| `overhang` | overhang ID | Must not masquerade as a domain selection. |
| `extension` | extension ID | Parent strand is derived. |
| `protein` | attachment ID | Preserve current selection capabilities. |

Refs should remain minimal. Rich entity data is derived from `currentDesign`; embedding
mutable domain/nucleotide objects in selection creates stale snapshots.

## Migration phases

### Phase 0 — Characterization and safety net

Status: complete (2026-08-12).

Deliverables:

- Inventory every selection writer, reader, private cache, renderer painter, keyboard
  command, context menu, cross-window event, and test-only API.
- Add a checked-in matrix with rows for entity kinds and columns for entry paths:
  default drill, fixed level, plain click, Ctrl/Shift toggle, lasso, sidebar,
  spreadsheet, programmatic selection, coarse/cylinder/surface, atomistic, overlay,
  design rebuild, Delete, Escape, and empty-space clear.
- Record current intended behavior and flag contradictions requiring product decisions.
- Add characterization tests before changing state shape.
- Add test helpers that snapshot logical selection independently from renderer internals.

Required regressions:

- Default strand→base equals explicit Base selection.
- Re-click/toggle behavior for every entity kind.
- Plain A then additive B retains A and B.
- Empty-space clear retains the configured selection level.
- Design reload/rebuild preserves valid refs and removes stale refs.
- Representation switching does not change logical selection.

Exit gate:

- The matrix covers all current entity kinds and entry paths.
- Every known divergence is classified as bug, intentional fallback, or pending product
  decision.
- Baseline tests pass in `just test-smart`; focused browser gestures are identified for
  Playwright coverage.

Completion evidence (2026-08-12):

- Checked-in entry-path, writer/reader, fallback, and coverage matrix:
  `memory/selection_behavior_matrix.md`.
- Six architecture characterization pins cover the known legacy split states and
  external direct-write boundary.
- 116 focused unit tests passed across selection policy, base identity/picking,
  Properties, transforms, and architecture characterization.
- `frontend/e2e/base_select.spec.js`: 7/7 Chromium WebGL gestures passed.
- The parity test uncovered a second divergence: explicit Base used projection-nearest
  resolution and could select a hidden bead behind the default drill's frontmost
  raycast hit. `_baseCandidateAt` now provides one raycast-first resolver for Base
  preview, plain click, and modifier click, with the magnet retained for exotic bead
  families. Default drill and explicit Base now select the same identity and state.

### Phase 1 — SelectionRef contract and pure reducer

Status: complete (2026-08-12).

Deliverables:

- Add a small module such as `scene/selection_model.js` containing:
  - ref constructors and validation;
  - stable equality/dedup/order helpers;
  - `replace`, `toggle`, `extend`, `clear`, `setLevel`, and `reconcile` reducer logic;
  - selectors for primary, by-kind refs, related strands/domains, and command targets.
- Decide and document `end` versus `base` semantics.
- Decide canonical treatment of `forced_ligation` as crossover subtype versus kind.
- Reject mixed design/assembly refs in one design selection.
- Keep the module free of DOM, Three.js, store, and API imports.

Validation:

- Table-driven unit tests for every reducer intent and kind.
- Property-style tests for deduplication, toggle involution, stable order, primary
  membership, reconciliation idempotence, and serialization round trips.
- Invalid/malformed refs fail safely and cannot enter state.

Exit gate:

- Pure model has complete unit coverage of invariants.
- No production gesture path is migrated yet unless guarded by compatibility tests.

Progress (2026-08-12, decision-independent foundation):

- Added `frontend/src/scene/selection_ref.js`, a pure identity module with no DOM,
  Three.js, store, or API dependency.
- Stable refs now normalize mutable input to minimal identity, compare structurally,
  deduplicate in stable order, reconcile through an injected live-identity predicate,
  and serialize/deserialize safely.
- End and forced-ligation kinds are deliberately absent pending the product decision;
  reducer ordering/toggle/persistence semantics are not yet implemented.

Completion evidence (2026-08-12):

- User approved recommendations 1–5 and overrode item 6: selection level resets across
  reloads rather than persisting.
- `selection_ref.js` now includes base-keyed `end` refs and crossover refs with
  `crossover|forced_ligation` subtype; `forced_ligation` is not a separate kind.
- `selection_model.js` implements normalized state plus pure replace/select/toggle/
  extend/clear/set-level/reload/context-change/reconcile transitions.
- Primary is the most recently explicitly selected survivor; removing it promotes the
  previous survivor. Fixed-level sole-item re-click clears through `select`, while
  unconditional `replace` supports hierarchical default drill.
- Reload and context-change clear items and reset level to `default` in every context.
- 85 focused identity, reducer, policy, and architecture tests passed.

### Phase 2 — Controller plus legacy compatibility projection

Status: complete (2026-08-12).

Deliverables:

- Add the canonical `selection` slice to the store.
- Add one controller as the only authorized writer to that slice.
- During migration, derive legacy outputs from canonical state through a compatibility
  adapter; never make canonical state derive bidirectionally from multiple legacy
  fields.
- Add development assertions detecting direct legacy writes or canonical/legacy drift.
- Expose typed selectors so consumers stop reading raw state.
- Establish event semantics for `selection-changed` and cross-window synchronization.

Compatibility rule:

- Canonical → legacy projection is temporary and one-way.
- If an unmigrated external path must write legacy state, route it through an explicit
  bridge command and log/assert its use; do not silently watch arbitrary store writes.

Validation:

- Contract tests prove canonical refs project to the exact legacy shapes expected by
  current consumers.
- Transaction tests prove subscribers see one atomic final state.
- Diagnostic test fails if canonical and projected legacy state disagree.

Exit gate:

- Controller is usable without changing existing UI behavior.
- Direct-write inventory has an owner and planned migration phase for every callsite.

Progress (2026-08-12):

- Added canonical `selection` store slice initialized by the pure Phase 1 model and
  included in the store's selection subscription slice.
- Added `selection_controller.js` with atomic canonical+legacy commits, typed intent
  methods, reload/reconcile, one-way `projectLegacySelection`, and explicit drift
  detection/assertion.
- Projection covers store-backed legacy shapes for strand, domain, base, overhang,
  extension, cluster/member-strand compatibility, crossover/forced ligation, and
  protein. Renderer-private End and multi-crossover adapters remain assigned to their
  later vertical slices.
- Controller is instantiated in `main.js`; new-design reset and design↔assembly context
  transitions now clear canonical/legacy selection atomically and reset level to
  `default` per the ratified decision.
- Controller is injected into `selection_manager.js`. Strand/domain V2 commits, all
  base-pool commits (plain/modifier/lasso/prune/clear), and selection-level changes now
  write canonical state first and project the old fields atomically. Renderer painting
  remains unchanged during this slice.
- Strand/domain multi-toggle, lasso, promotion, atomistic, regional overlay, cylinder,
  surface, linker, rebuild fallback, programmatic strand, and external highlight routes
  now enter through the controller when production dependencies are present. Remaining
  legacy fallbacks are explicit compatibility/test paths or assigned to Phases 4–6.
- Visual cleanup helpers accept non-committing teardown, so replacement gestures no
  longer publish intermediate empty canonical states. Public clear still performs one
  controller transaction projecting every legacy field at once.
- Cross-window `selection-changed` emission now observes the canonical slice once and
  derives ordered strand owners through a typed selector. Incoming sync uses the same
  controller-backed programmatic strand path; deselection remains window-local per the
  existing protocol.
- 98 focused controller/model/ref/filter/architecture/Properties tests and production
  build pass;
  after production writer injection, the 7/7 Chromium Base WebGL gesture suite also
  passes (plain, default drill parity, modifier, lasso, level/clear).
- Phase 2 exit gate passed: the controller is production-usable without changing the
  established UI contract; its transaction and drift tests pass; every remaining
  direct writer is assigned to the entity slice in Phases 3–6 or final legacy removal.
  Global drift enforcement remains deliberately deferred until those writers migrate.

### Phase 3 — Migrate base, strand, and domain vertical slice

Status: complete (2026-08-12).

Why first: these form the default drill ladder and reproduce the divergence that
triggered this project.

Deliverables:

- Convert bead/domain/strand pick results to normalized refs.
- Route default drill, fixed levels, modifier clicks, lasso, sidebar, spreadsheet,
  histogram, programmatic `selectStrand`, and `selectNucleotide` through the controller.
- Replace `_promoteSelectionToMulti()` for these kinds with ordinary `extend/toggle`.
- Migrate Properties, Delete, Move/Rotate target resolution, spreadsheet highlight,
  command palette, and relevant menus to selectors.
- Preserve explicit cylinder/surface base→domain fallback through a named resolution
  result and tested capability rule.

Validation matrix:

- Full/coarse beads, cylinders, surface, atomistic, regional atomistic, overlay.
- Default drill versus explicit Strand/Domain/Base levels.
- Pointer, lasso, modifier, spreadsheet, histogram, and public API parity.
- Single, multi, primary ordering, clear, Escape, Delete, design rebuild, and undo/redo.

Exit gate:

- No base/strand/domain consumer requires `selectedObject` or their legacy arrays.
- Equivalent entry-path snapshots are byte-for-byte equal after normalization.
- Focused unit/integration tests and Playwright gestures pass.

Completion evidence (2026-08-12):

- Default drill, fixed levels, modifiers, lasso, spreadsheet, histogram, public
  `selectStrand`, and public `selectNucleotide` now converge on canonical refs and
  controller intents. Programmatic nucleotide selection no longer creates a separate
  `selectedObject.type='nucleotide'` endpoint.
- Properties, Delete for these kinds, Move/Rotate targeting, bounding boxes,
  spreadsheet/list highlights, command palette, feature log, minimap/unfold views,
  simulation anchors, HUD/debug surfaces, and atomistic highlighting read canonical
  typed selection. Atomistic projection consumes a compiled canonical descriptor.
- Design replacement reconciliation prunes stale refs and preserves live refs/order;
  reload/open/context changes intentionally clear selection and reset the level to
  `default` per the user-approved contract.
- Static audit found no remaining base/strand/domain production consumer that depends
  on legacy selection fields except explicitly staged compatibility fallbacks for
  kinds assigned to Phases 4–6.
- Full frontend suite: 304 files and 5,490 tests passed. Four legacy-fixture files
  found by this gate were updated to construct canonical selection snapshots rather
  than mutating projected fields.
- Chromium WebGL Base suite: 7/7 passed, including normalized byte-for-byte parity for
  default strand→base drill and explicit Base mode. Production build and focused
  slice tests pass.

### Phase 4 — Migrate overhangs and extensions

Status: complete (2026-08-12).

Deliverables:

- Give overhang and extension selections their own canonical refs.
- Remove the dual state where one selection occupies a multi pool plus a domain/object.
- Derive related domain, parent strand, sequence-panel target, manager A/B choice, and
  animation target through selectors.
- Route 3D filters, sidebar list, manager popup, context menus, and programmatic APIs
  through the controller.

Validation:

- Single and additive selection from 3D and sidebar are identical.
- Overhang Connections, Overhangs Manager, Strand Animation, sequence editing, and
  Properties receive the same targets as before.
- Deleted/replaced overhangs and extensions reconcile without stale highlights.
- Direct binding/linker operations retain selected identities where valid.

Exit gate:

- `multiSelectedOverhangIds` and `multiSelectedExtensionIds` have no unmigrated
  consumers and can be removed or retained only as explicitly temporary projections.

Completion evidence (2026-08-12):

- Plain 3D/atomistic selection, modifier toggle, lasso, sidebar/programmatic overhang
  selection, extension selection, and cleanup now use canonical controller intents.
  Fixed-filter sole re-click clears; sidebar/programmatic selection remains an
  unconditional replace.
- Overhang Connections, Overhangs Manager, Strand Animation, Properties, Delete,
  sequence-list parent highlighting, and simulation anchors consume canonical typed
  refs/selectors. Overhang→domain and overhang/extension→parent-strand relations are
  derived live from the design.
- The compatibility projection retains only temporary overhang/extension ID arrays;
  it no longer manufactures a domain or extension `selectedObject`, eliminating the
  dual logical identity.
- Atomistic descriptors now derive overhang domain ranges and preserve extension IDs.
  Atom clicks, lasso, Base mode, and highlighting no longer collapse extension-tail
  atoms onto their anchor nucleotide; the pure atom→base resolver has regression tests.
- Focused slice gate: 281 tests passed. Full frontend gate: 304 files and 5,500 tests
  passed. Production build passed.
- New Chromium WebGL regression passed against a real overhang design: a 3D click and
  sidebar row produce identical canonical snapshots, and a fixed-filter sole re-click
  clears the selection.

### Phase 5 — Migrate clusters and transformations

Status: complete (2026-08-12).

Deliverables:

- Store only cluster refs as selected entities; derive member strands for visuals and
  commands.
- Route 3D cluster level, cluster sidebar rows, modifier selection, lasso, copy/paste,
  and Move/Rotate through the controller.
- Replace cluster/member-strand duplication and its synchronization rules.
- Define primary-cluster pivot behavior for ordered multi-selection.

Validation:

- Sidebar and 3D selections produce identical refs and highlight projection.
- Cluster membership changes re-derive visuals without changing cluster identity.
- Move/Rotate, joints, copy/paste, undo/redo, and design rebuild retain current behavior.
- Overlapping/default clusters resolve using documented policy.

Exit gate:

- Cluster selection no longer writes member IDs into selected strand storage.
- Transform tools consume typed selection selectors only.

Completion evidence (2026-08-12):

- Cluster plain/fixed-level clicks, modifier toggles, lasso, sidebar rows, clipboard,
  keyboard copy, Properties, and transform-tool activation now consume canonical
  cluster refs. The compatibility projection retains only cluster IDs; it no longer
  injects member IDs into selected strand storage.
- Cluster members are derived from the live design only for visual highlighting and
  command expansion. Membership edits therefore preserve cluster identity while
  naturally re-deriving the affected strands/domains.
- Ordered cluster refs expose an explicit most-recent primary cluster. Move/Rotate
  derives its activation group and pivot input from typed canonical selectors;
  single-cluster selection suppresses group activation as before.
- Atomistic selection descriptors derive exact domain ranges for domain clusters and
  whole-helix ranges for plain clusters, so coarse and atomistic highlights share the
  same cluster identity.
- Focused cluster/transform gate: 248 tests passed. Full frontend gate: 304 files and
  5,505 tests passed. Production build and `git diff --check` passed.
- New Chromium WebGL regression passed: a real 3D cluster click and its sidebar row
  produce byte-identical canonical snapshots, a sole re-click clears, and no member
  strand IDs appear in projected selection state.

### Phase 6 — Migrate crossovers, ends, proteins, and remaining entity kinds

Status: complete (2026-08-12).

Deliverables:

- Replace single crossover `selectedObject` plus private multi-arc state with crossover
  refs; derive live arcs for highlighting and context commands.
- Separate end selection from measurement anchors.
- Migrate protein attachment selection and any remaining special entities.
- Make forced-ligation handling explicit under the ratified Phase 1 contract.
- Remove obsolete `nucleotide`, `cone`, and renderer-entry identity forms where they
  represent presentation details rather than logical selection.

Validation:

- Xover fixed level, arc proximity, lasso, modifier toggle, Delete/nick, forced
  ligations, unfold view, and representation switches.
- End selection, extrude arrows, loop/skip menus, and end-specific keyboard commands.
- Protein selection in coarse/atomistic views and after attachment mutation.

Exit gate:

- No logical selection identity depends on a live renderer entry or private arc list.

Completion evidence (2026-08-12):

- Plain/fixed crossover clicks, modifier toggles, lasso, rebuild projection,
  Properties, Delete, selection HUD, right-click batch targeting, and forced-ligation
  subtype handling now use canonical crossover refs. Live arc wrappers are visual/hit
  adapters only and are re-derived by subtype+ID.
- Protein clicks now enter through controller intents. Protein highlight/gizmo,
  Properties, and Conjugate Manager derive the selected attachment from canonical
  refs; compatibility projection no longer creates a protein selectedObject.
- End plain-click, modifier toggle, and lasso now create base-keyed canonical End refs.
  Forced ligation and strand-end resize arrows consume those refs. Alt-click distance
  measurement remains a separate private tool-anchor pool and no longer creates End
  selection or resize arrows.
- Same-helix connector hits now normalize to a renderer-independent `bond` ref with
  ordered base keys (and owner strand where applicable). Delete derives its nick site
  from that ref; the old cone selectedObject is no longer a production endpoint.
- The real End-lasso gate exposed a coordinate-space divergence: instance-local
  positions were projected without mesh world transforms. Cylinder/backbone/extension
  lasso projection now applies `matrixWorld`, aligning lasso capture with screen hits.
- Focused Phase 6 gate: 169 tests passed. Full frontend gate: 304 files and 5,511 tests
  passed. Production build and `git diff --check` passed.
- Chromium WebGL forced-ligation suite: 2/2 passed—two additive End lassos and
  plain-click→Ctrl-click both retain the exact two canonical End refs and execute the
  same forced-ligation command. Selection level still resets on reload per user choice.

### Phase 7 — Derived highlighting and picker separation

Status: complete (2026-08-12).

Deliverables:

- Extract picking into pure-ish adapters that return hit candidates/ref resolutions.
- Add one highlight projection layer that consumes canonical refs plus live geometry.
- Rebuild highlights after geometry/representation changes without mutating selection.
- Keep hover preview separate from committed selection.
- Remove gesture-specific painting and private selected-entry caches once unused.

Validation:

- Golden logical snapshots paired with renderer-level assertions for selected glow,
  scale/color restoration, cylinder highlight, atomistic highlight, connector arcs,
  and rebuild behavior.
- Rapid representation changes and geometry rebuilds never clear or duplicate selection.
- Misses, hidden meshes, stale meshes, and disposed flexible-arc meshes are covered.

Exit gate:

- Pointer handlers do only gesture recognition, hit resolution, and controller intents.
- Renderer highlight state can be discarded/rebuilt solely from canonical selection.

Progress (2026-08-12, review checkpoint):

- Added `selection_highlight_model.js`, a pure renderer-neutral descriptor covering
  every canonical kind with stable IDs/keys only. It contains no DOM, Three.js, meshes,
  or cached entries. Atomistic global/regional selection now consumes this descriptor
  before deriving live domain ranges and cluster membership.
- Added `selection_hit_resolver.js` and routed End beads, backbone connector cones, and
  crossover/forced-ligation arcs through pure metadata→ref resolvers. Hit resolution is
  now independently table-tested and no longer writes state or paints renderers.
- Inventory currently finds 50 imperative paint/cache/pick sites in
  `selection_manager.js`. The next high-risk step is to replace the interdependent
  `_highlight*`/`_applyMulti*` caches with one live-geometry projection without
  regressing mixed-representation scale/color restoration.
- Phase 7 foundation gate: 152 focused tests passed; production build and
  `git diff --check` passed. The immediately preceding Phase 6 full gate remains 304
  files / 5,511 tests plus 2/2 forced-ligation WebGL gestures.

Completion evidence (2026-08-12):

- `selection_manager.js` now has one canonical highlight projector. On every
  selection mutation or geometry/design rebuild it discards renderer-entry adapters
  and reconstructs Base, End, bond, crossover, cluster, strand, domain, overhang, and
  extension visuals from `selectionHighlightDescriptor()` plus current live geometry.
- Production 3D, sidebar, programmatic, modifier, lasso, atomistic, surface, cylinder,
  and linker selection paths commit controller intents without choosing a renderer
  painter. Direct painting remains only in explicit controller-free compatibility
  branches and in separate hover/measurement transient tools.
- Stable bond refs now resolve back to live cone geometry through
  `coneForBondRef()`, including ordered endpoint and optional strand disambiguation;
  rebuild tests cover that pure resolution contract.
- Reconciliation owns stale logical refs. The painter no longer prunes canonical Base
  keys or mutates selection while rebuilding visuals.
- Phase 7 gate: 306 frontend test files / 5,518 tests passed; production build and
  `git diff --check` passed. Chromium WebGL matrix passed 11/11 across Base parity and
  additive/lasso gestures, End forced ligation, 3D↔sidebar cluster parity, and
  3D↔sidebar overhang parity. One earlier combined run exposed pre-existing stale
  `drill_v2_select.spec.js` assumptions (hidden collapsed filter row and legacy
  `selectedObject.type='nucleotide'`); the migrated Base parity suite is authoritative.

### Phase 8 — Consumer completion, legacy removal, and hard enforcement

Status: in progress (2026-08-12), compatibility-deletion review checkpoint.

Deliverables:

- Migrate remaining consumers: Delete, Properties, menus, feature log, simulation
  restraints/anchors, export helpers, file reconciliation, cross-window sync, debug API,
  and automation hooks.
- Remove `selectedObject`, legacy `multiSelected*` design arrays, private selection mode
  mirrors, compatibility projection, and direct selection painting.
- Add lint/static checks or focused architecture tests preventing direct selection store
  writes outside the controller.
- Update path-scoped selection architecture documentation and public debug/test APIs.

Validation:

- Full unit suite and `just test-smart` per slice.
- Full `just test` pre-push gate.
- Playwright regression matrix across representative designs and render modes.
- No console errors, stale selections, duplicate commands, or highlight residue during
  open/new/undo/redo/delete/representation-switch workflows.
- Search gate confirms forbidden legacy fields/writers are absent except migration
  fixtures explicitly marked historical.

Exit gate:

- Canonical controller is the sole writer.
- All consumers use typed selectors.
- Compatibility code is deleted.
- Architecture documentation describes the shipped model, not the migration.

Progress (2026-08-12, compatibility-deletion review checkpoint):

- A production-only inventory reduced legacy-name hits to seven files. Four are
  comments or Properties-local display-adapter variable names; all actual legacy
  store access is now isolated to `state/store.js`, `selection_controller.js`, and
  controller-free compatibility branches in `selection_manager.js`.
- Delete no longer reads `selectedObject`; force-crossover activation no longer writes
  it; design lifecycle reset relies on `selectionController.reload()`; Properties has
  no legacy fallback or direct clear write; debug/automation strand state is canonical.
- Playwright tests no longer use `getSelectedObject()`. The drill regression was
  modernized to the ratified canonical hierarchy (strand → Base → strand), opens
  the collapsed selection-level menu, and now passes 3/3 alongside Base 7/7.
- Checkpoint gate: 306 frontend files / 5,518 tests passed; production build and
  `git diff --check` passed. The destructive next slice is intentionally paused for
  review before deleting the store fields, compatibility projection/tests, and every
  controller-free manager branch in one coordinated change.

### Phase 9 — Assembly evaluation and optional convergence

Status: complete; assembly remains an explicitly bounded selection context.

Deliverables:

- Audit `activeInstanceId`, `multiSelectedInstanceIds`, `activeGroupId`, group dive,
  assembly overhang A/B selection, and assembly pointer behavior against the mature
  design-selection contract.
- Decide whether to reuse the reducer with `context:'assembly'`, keep a parallel
  controller with shared primitives, or intentionally remain separate.
- Record the decision in architecture documentation before implementation.

Exit gate:

- Assembly either adopts the shared contract with parity tests or has an explicit,
  justified boundary and no accidental coupling to design selection.

#### Phase 9 audit and boundary decision (2026-08-12)

Assembly selection is intentionally not folded into the design-selection slice in this
migration. The audit found five assembly concepts with different identity and lifecycle
requirements: single/multiple PartInstances, recursive PartGroups plus `groupDiveStack`,
instance-scoped design clusters, instance-scoped part-joint targets, and an ordered
two-end assembly-overhang workflow. Several are also transform-session prerequisites,
not merely ordinary selected entities. Treating those fields as design refs would either
lose their composite instance identity or mix tool/navigation state into ordinary
selection.

The chosen boundary is:

- `selection` and `selectionController` own design entities only.
- Entering or leaving assembly commits an empty canonical context sentinel and resets
  level to `default`, honoring the user-approved reload rule.
- The design controller is inert while `selection.context === 'assembly'`; hidden design
  gestures, reconciliation, or cross-window messages cannot repopulate design refs.
- Assembly keeps `activeInstanceId`, `multiSelectedInstanceIds`, `activeGroupId`,
  `groupDiveStack`, and `assemblyOverhangSelection` in the assembly slice. Private
  assembly cluster/joint targets remain transform/pointer-session state.
- Design ref vocabulary contains no assembly kinds, and assembly consumers do not decode
  design refs. Context switches are the only deliberate connection.

This is a scope boundary, not an endorsement of assembly's split single/multi storage as
the final model. A future assembly-modernization project should introduce a dedicated
`AssemblySelectionRef` vocabulary and assembly controller, reuse the pure ordering and
toggle primitives where their semantics match, and migrate PartInstance/PartGroup first.
It should not broaden the design ref union or reuse the design controller blindly.

Boundary regressions are pinned by the controller isolation test and the architecture
gate that verifies context reloads, controller ownership, separate assembly fields, and
absence of assembly kinds from the design ref vocabulary.

## Testing strategy

Use a pyramid; do not rely exclusively on pixel gestures.

### Unit

- Reference construction, equality, serialization, validation, and reconciliation.
- Reducer intent semantics and invariants.
- Selectors for Properties, commands, parent/related entities, and transform targets.
- Representation capability fallback resolution.

### Integration with fake store/render adapters

- One controller transaction per gesture intent.
- Compatibility projection during migration.
- Derived highlight instructions for each ref kind.
- Geometry rebuild and design reconciliation.
- No stale renderer objects in canonical state.

### DOM/UI

- Sidebar, spreadsheet, filter buttons, Properties, and command enabled state.
- Equivalent entry points yield identical normalized snapshots.

### Playwright/WebGL

- Default drill versus explicit level parity.
- Plain plus additive selection, lasso, Escape, empty-space clear.
- Representation switches: Full, Beads, Cylinders, Surface, and atomistic modes.
- Selection survival through geometry rebuild, undo/redo, and file/design replacement.
- Context-menu and Delete behavior for each entity kind.

### Static/architecture gates

- Direct canonical store writes outside the controller are forbidden.
- After Phase 8, legacy field names are forbidden in production code.
- Canonical refs must pass serialization validation and contain no Three.js/DOM objects.

## Regression matrix template

Each migrated kind must fill this matrix in its tests or phase notes:

| Dimension | Required cases |
|---|---|
| Entry | 3D, fixed level, default drill where applicable, sidebar, programmatic |
| Cardinality | none, one, multiple, primary item |
| Mutation | replace, toggle, extend, clear, prune stale |
| Representation | Full/Beads, Cylinders, Surface, atomistic/overlay where supported |
| Lifecycle | geometry rebuild, design replace, undo, redo, delete selected entity |
| Consumer | Properties, highlight, Delete/menu, Move/Rotate or relevant tool |
| Miss/fallback | empty space, hidden mesh, unsupported granularity |

## Rollout and rollback rules

- Migrate one vertical slice at a time, including its pickers, controller path,
  consumers, highlights, and tests.
- Keep commits phase-scoped and behavior-preserving where possible.
- Compatibility projection remains until all consumers for that kind migrate.
- Do not maintain two writable sources of truth.
- If a phase regresses behavior, roll back that vertical slice rather than adding a
  reverse sync watcher.
- Any approved behavior change must be recorded here under Decisions with date,
  rationale, and affected regression cases.

## Decisions required before implementation

- Whether `end` is its own ref kind or a semantic view of a base ref.
- Whether forced ligations are a crossover subtype or distinct kind.
- Whether primary selection is always the most recently added item.
- Whether re-clicking a sole selected item clears it consistently across all kinds.
- Whether selecting an overhang should make its backing domain a related target only,
  or expose both through a compound selector.
- Whether selection level persists across files/workspaces.
- Exact boundary between committed selection, hover preview, tool anchors, and active
  transform sessions.

## Progress ledger

Update this table at the end of every selection-migration session.

| Phase | Status | Evidence / next action |
|---|---|---|
| 0 Characterization | complete | Matrix + 6 architecture pins; 116 focused unit tests and 7/7 Base WebGL gestures green. Also fixed raycast-vs-projection Base target divergence. |
| 1 Ref + reducer | complete | Approved contract implemented; 85 focused tests green. Level always resets across reloads per user decision. |
| 2 Controller + compatibility | complete | Canonical store/controller, atomic one-way projection, typed selectors, broadcast integration, and drift/transaction tests green. |
| 3 Base/strand/domain | complete | Canonical vertical slice complete; 5,490/5,490 unit tests and 7/7 Base WebGL gestures green. |
| 4 Overhang/extension | complete | Canonical producer/consumer slice; 5,500 unit tests, build, and real 3D↔sidebar overhang parity regression green. |
| 5 Cluster/transform | complete | Canonical cluster-only state; 5,505 unit tests, build, and real 3D↔sidebar cluster parity regression green. |
| 6 Remaining kinds | complete | Canonical crossover/End/protein/bond identities; 5,511 unit tests, build, and 2/2 forced-ligation WebGL gestures green. |
| 7 Derived visuals | complete | One canonical live-geometry projector; 5,518 unit tests, build, and 11/11 representative WebGL gestures green. |
| 8 Legacy removal | complete | Seven fields, compatibility projection, fallback writers/readers removed; controller is mandatory and sole writer. 306 files / 5,514 tests, build, diff check, and 14/14 WebGL design-selection gestures green. |
| 9 Assembly decision | complete | Explicit bounded context ratified; design controller is inert in assembly. Runtime/static isolation gates and 3/3 assembly-selection gestures green. |

## Session resume protocol

At the start of a future session:

1. Read this file and the path-scoped selection architecture rule.
2. Inspect `git status`; preserve unrelated/shared-worktree changes.
3. Read the latest Progress ledger row and any Decisions added below.
4. Re-run the focused tests named by the active phase before editing.
5. Work on only one phase or one explicitly bounded vertical slice.
6. Update status, evidence, newly found divergences, decisions, and exact next action
   before ending the session.
7. Do not mark a phase complete until every listed exit gate passes.

## Decisions

- 2026-08-12: Default strand→base drill and explicit Base selection must share the
  app-wide base-key endpoint. This is a binding parity rule, not a temporary detail.
- 2026-08-12: The migration will be incremental with a one-way compatibility layer;
  a flag-day rewrite is rejected because selection has broad command and renderer
  consumers.

## Immediate next action

The design-selection migration is complete. Keep the canonical architecture gate in the
standard unit suite and add entries to `memory/selection_behavior_matrix.md` whenever a
new selection kind, representation, or command consumer is introduced. Treat assembly
selection modernization as a separate project under the Phase 9 boundary above.

Recommended Phase 1 package:

1. `end` is its own semantic ref kind, keyed by the underlying base key. This preserves
   end-specific commands without confusing any selected base with a terminus.
2. `forced_ligation` is a subtype of `crossover`, because it uses the same arc picking,
   selection, Delete, and highlight mechanics while command selectors can inspect the
   subtype.
3. `primary` is the most recently explicitly selected surviving item. Removing it makes
   the previous item primary; reconciliation preserves order.
4. Plain re-click of the sole selected item clears it consistently at fixed levels.
   Default drill remains hierarchical: first click selects strand, next resolves leaf.
5. Overhang selection contains only an `overhang` ref. Its backing domain and parent
   strand are related selectors, not additional selected items.
6. **User override:** selection level does not persist; every reload and every
   design/assembly open/create resets it to `default`.

## Ratified Phase 1 decisions

- 2026-08-12: End is its own semantic ref kind keyed by its underlying base.
- 2026-08-12: Forced ligation is a crossover subtype.
- 2026-08-12: Primary is the most recently explicitly selected surviving item.
- 2026-08-12: Plain re-click of the sole item clears it at fixed levels; default drill
  remains hierarchical and may use unconditional replace.
- 2026-08-12: Overhang selection contains only an overhang ref; backing domain/strand
  are derived relations.
- 2026-08-12: Selection level resets to `default` across all reloads/context changes.
- 2026-08-12: Assembly selection remains a separate bounded subsystem. The design
  controller becomes inert in assembly context; a future assembly migration gets its
  own ref vocabulary/controller rather than extending design refs with ambiguous IDs.
