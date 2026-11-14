---
name: Design display geometry ownership
description: One document-local display frame and scene root own molecular geometry; renderers register producers or consumers instead of per-action fanout.
type: feedback
originSessionId: 56d058db-5d5d-46e6-a16b-461336fcaa1e
---

The part editor's molecular display is owned by
`designRenderer.getDisplayGeometry()` (scene group `designDisplay`).
Backbone/slabs, extension sites, crossover inserts and lines, flexible runs,
and overhang links inherit this root. Whole-model visibility uses
`designRenderer.setDesignVisible(bool)`; authoring display uses the same root.
Per-layer representation gates remain independent children.

The former instruction to enumerate five molecular owners is superseded.
Unfold owns arc topology/style buffers, **not a second implementation of endpoint
positions**. Animating a buffer is compatible with shared scene ownership.

Position writers operate on the observed helix controller. The display owner
batches a frame, runs extension layout then insert/flexible producers, and finally
connection consumers. Multi-operation animation and residue previews use
`display.transaction(...)`. New molecular consumers register once with this owner;
do not add per-action calls to refresh crossovers, inserts, or linkers.

Keys preserve loop-copy indices and synthetic extension/link/insert identities.
A new simulation frame replaces the previous frame; absent ordinary sites use
native positions, while absent inserts use current endpoint-derived placement.
Simulation poses never change authored records. Derived flexible positions are
published for other consumers. Visibility refresh only reads the committed pose.

Editor widgets (end handles, labels, joints), physical atomistic/surface meshes,
and assembly instances are separate hosts/layers. Assembly already parents
crossovers/inserts under each instance; its shared-instancing and simulation
adapters have not been migrated to the part editor's frame registry. Do not imply
that this part-editor refactor changes those coordinate pipelines.

Regression entry points: `display_geometry.test.js`,
`display_geometry.integration.test.js`, and
`frontend/e2e/display_geometry.spec.js`. Browser checks read real line buffers,
include a deliberately displaced negative control, and compare rendered pixels.
