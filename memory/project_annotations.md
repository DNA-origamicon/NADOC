---
name: project-annotations
description: "Right-sidebar Annotations tab — view-only callouts + coloured target highlights for parts and assemblies; persistence, scope limits, file map."
metadata:
  node_type: memory
  type: project
  status: shipped
  authority: canonical
  review_after: 2027-01-01
  created: 2026-09-18
---

# Annotations (right sidebar → "Annotations")

Per-entry: text, icon (warning/attention/green check/red X/info/question/star/flag/pin), callout type
(elbow / straight / rounded / shelf), colour, transparency (0–80 %), size (0.7–2.5×), auto/manual
position, target = the canonical selection refs captured with **Use selection**.

- **Layers:** view metadata only. Targets are `selection_ref` refs resolved every frame against live
  `designRenderer.getBackboneEntries()`; nothing is written to topology/geometry.
- **Files:** `scene/annotation_{model,targets,layout,controller,overlay,subsystem,icons}.js` (+ css),
  `ui/annotation_panel.js`, wired by one `initAnnotations(...)` in `main.js` (after `selectionManager`
  exists — its frame callback reads it). e2e: `frontend/e2e/annotations.spec.js`.
- **Rendering:** callouts are DOM/SVG in `#canvas-area` (z-index 50, pointer-events only on the manual
  grip); highlight = `THREE.Points`, `depthTest:false`, `renderOrder 1200`. Both draw over the scene.
- **Manual mode:** pins `screenPos` (fractions of the viewport, top-left of box); toggling to manual
  pins the box where it currently sits. Drag = the hatched bottom-right grip.
- **Persistence:** saved IN the `.nadoc`: `Design.annotations: List[Annotation]` + `annotations_enabled`
  (models.py). Route `PUT /design/annotations` (`routes_display_metadata.py`, `mutate_display_metadata`: no undo
  entry, no feature-log entry, tiny response). Frontend: `currentDesign.annotations` is the source of truth;
  `annotation_controller` keeps a working copy, debounces 300 ms into `commit()` (subsystem: store write → the
  autosave watches `currentDesign` → backend PUT, sequential, re-asserted if a stale design response raced it).
  Wire format = snake_case (`annotationToWire/FromWire`); `refs` stored verbatim (camelCase selection refs).
  Rules: unsent/in-flight local edits are never overwritten by an incoming design; a design switch DROPS unsent
  edits (never writes into the wrong design); undo/redo keep the CURRENT annotations (`_restore_edit_snapshot`);
  excluded from atomistic topology hash + part-identity + periodic-cell derivative. Legacy localStorage
  annotations (`nadoc.annotations.v1:<id>`) are adopted once into an annotation-less design, then removed.
- **Response ordering:** `api/design_revisions.js` retains acknowledged annotation fields
  separately from full-design revisions. A delayed geometry response can still apply without
  erasing newer annotations; late acknowledgements for a closed design are ignored.
- **Global toggle:** `annotations_enabled` (checkbox atop the tab) hides callouts + highlights, keeps entries, saved in the file.
- **Auto placement:** `annotation_occupancy.js` projects visible backbone beads (stride-capped at 20k) +
  every protein/nanoparticle disc into a 12 px grid (SAT coverage + distance transform, rebuilt only when
  the camera/geometry signature changes). `annotation_layout.placeAuto` scores ring candidates around the
  anchor + the roomiest empty pockets: coverage of design ≫ overlap with other callouts, then leader
  length, then clearance. Anchorless → middle of the emptiest pocket. 60-point hysteresis keeps a
  still-good box from jittering while orbiting. Leader side is re-chosen every frame
  (`attachPoint`: left/right, or top/bottom when the anchor is within the box's x-span).
- **Protein / nanoparticle targets:** `annotation_external.js` → world bounding spheres (nanoparticle: mesh
  world pos + design radius; protein: `proteinRenderer.extentOf`, cached 120 ms). Highlight = halo sprite
  (`depthTest:false`), anchor = sphere centre.
- **Assembly support (2026-09-27):** same controller/panel/overlay; annotations + global toggle live in
  `Assembly.annotations` / `annotations_enabled` and save through `PUT /assembly/annotations` in `.nass`.
  User-limited target vocabulary: `assembly-part {instanceId}` and `assembly-overhang {instanceId,overhangId}`.
  “Use selection” prefers selected overhangs, then individually multi-selected copies, then the active
  instance; group and part-editor molecular refs are not captured (`assembly_annotation_refs.js`). Unnamed
  overhangs now have pick anchors using their IDs as display labels, without changing saved names.
  `assembly_annotation_targets.js`
  reuses part overhang matching, transforms source-local beads through the live instance matrix, and
  excludes hidden/deleted instances. Hull/cylinder views fall back to source nucleotide positions when
  their renderer deliberately allocates no bead meshes. Repeated sources remain independently addressable. Occupancy uses
  visible instance bounding spheres to avoid expanding every bead across an entire assembly; only
  annotated targets allocate world-space bead positions. Source `.nadoc` annotations are unchanged.
  Assembly undo/redo and feature-history seek preserve current annotations. Assembly response revisions
  reuse `createDesignRevisionTracker` to retain acknowledged notes against delayed geometry responses.
  Prepared sharing captures the same highlight UUIDs/callouts as parts.
- **Scope limits:** `__xb__` extra-base keys resolve once via `selectionManager.getBaseWorldPosition`
  (static position, not per-frame). Occupancy ignores whether a bead is hidden by a visibility filter.

**Open:** no cross-tab live sync beyond the `design-changed` broadcast. Not visually hand-checked: glow
intensity/size at low zoom, every callout type's look, placement on a dense multi-helix design.
