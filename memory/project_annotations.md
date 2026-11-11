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

November 10 keyframe capture/duplicate: **Capture keyframe** above the pose selector
creates a new saved camera pose and fills the frame with the actually visible
annotation/view-volume/zoom-volume IDs. Part state pins the displayed feature-log
stage (including an explicit current end); assembly state creates a configuration
snapshot with joint values. Timing, text and trajectory settings remain intact.
The header copy icon sits between preview and delete and inserts a deep duplicate
with a new ID immediately below its source. Recapturing a copy creates a separate
pose/configuration. Both actions use one undoable backend metadata publication;
selected assembly parts use the existing source patch path. Shared modules:
`ui/keyframe_actions.js`, `api/keyframe_actions.js`, `backend/api/keyframe_actions.py`.
Browser coverage: `e2e/keyframe_capture.spec.js` passed. Full frontend: 10,297
passed / one skipped (906 files); backend focused: two passed; lint passed.
Smoke: 22 passed / two skipped / one existing Close Session progress-popup failure
before teardown. Backend selector: FULL due to shared models; broad suite not run.
Artifacts cleaned and summary retained in
`.development-artifacts/keyframe-capture/validation.json`. `main.js` LOC delta: 0.

November 10 keyframe deletion: `ui/keyframe_deletion.js` removes the row immediately,
filters pending IDs from playback/list refreshes, and yields a paint before stopping
preview/releasing trajectory caches. Deletions serialize per document; API null/false
or exceptions restore from the current document instead of an old snapshot. Queued
work is cancelled on context changes. Selected assembly parts use the same UI filter
while their source patch waits for acknowledgement, so API refusal leaves the source
unchanged. Both delete routes accept `metadata_only=true`:
the editor receives only ID/animations/revision, while undoable publication remains.
`api/keyframe_deletion_endpoints.js` merges metadata with revision tracking, preserving
live geometry and rejecting responses from replaced documents; busy popups are suppressed.
The prior latency path waited for a full molecular copy/publication/validation/response
before removing the row, then synchronously evicted trajectory preparation caches.
This change removes full response serialization (and the redundant part validation)
and moves remaining publication/cleanup behind the immediate visual response. Backend
copy/publication costs remain; no claim of a measured production-data speedup.
Validation: final browser workflow, 27 focused frontend checks, two backend undo
checks and lint passed. Full frontend: 10,281 passed / one skipped / one new test
failed during an in-flight edit; fresh focused run passes that test. Smoke retained
the two known setup/progress failures (21 passed / two skipped). Full backend
selection was deferred for unrelated worktree changes. Evidence and cleanup:
`.development-artifacts/keyframe-deletion/validation.json`. `main.js` LOC delta: 0.

November 10 keyframe volume options: keyframes share one expandable picker for
Annotations, View Volumes, and Zoom Volumes, with scrollable checkboxes and All/None.
Nullable `view_volume_ids` / `zoom_volume_ids` persist on part and assembly keyframes;
null retains working/checkpoint visibility, [] hides the channel. Preview/playback
applies display-only subsets and stop clears overrides. View volumes retain their
authored representation/coloring/outline settings. Zoom definitions, stable IDs, and zoom steps now persist in document metadata;
saved entries restore insets after reopening (see project_mixed_representation.md). UUIDs prevent stale keyframes from
selecting unrelated new insets. `main.js` only passes the zoom manager (LOC delta 0).

November 10 sidebar polish: numeric pixel-size and font-family dropdowns sit
directly beneath the callout text (the legacy `size` multiplier is retained on
wire; the UI shows `13 * size` pixels). `font_family` defaults to `system-ui`;
viewport, image export and shared callouts retain it. While a keyframe is selected,
working annotation edits immediately update matching display-only callouts while
preserving the keyframe's subset and working visibility. A pointer interaction in
the 3D viewport clears keyframe selection and stops its display override. The
annotation picker uses NAMD job-list styling and a bounded scroll area; action
buttons use the shared `.btn` system.

November 10, 2026: entries have editable reference names (default `Annotation N`)
and collapse to a header retaining the name, visibility and delete controls.
Animation keyframes have an annotation checkbox picker with All/None actions.
`annotation_ids: null` preserves legacy checkpoint/current visibility; `[]` hides
all annotations; explicit IDs show exactly those live-document annotations,
including entries hidden in the working editor. This is a transient playback
override for selection, individual/full preview and local presentation. Stopping
restores the working display; playback never writes annotation metadata.

November 6, 2026: **Save to feature log** at the top of the sidebar explicitly records
an `annotations-state` command containing the complete annotation configuration and
global visibility. Ordinary edits still autosave without feature entries. The shared
**Annotations and view volumes** history filter defaults off; filtering never removes
checkpoints from animation selections. Native replay and history seeking restore the
last checkpoint for each presentation channel (empty before its first checkpoint).
Undo/redo across a checkpoint restores that state; unrelated edits preserve live notes.
Playback uses a separate overlay controller, switches at keyframe endpoints, and
restores the working display on stop without persisting playback states. Assemblies
have the same save action and an independent presentation selector beside their
animation configuration selector. View volumes use the parallel `view-volumes-state`
command; neither action captures the other sidebar's uncheckpointed edits.

Per-entry: text, icon (warning/attention/green check/red X/info/question/star/flag/pin), callout type
(elbow / straight / rounded / shelf), colour, transparency (0–80 %), positive finite font size (editable pixels plus presets), auto/manual
position, target = the canonical selection refs captured with **Use selection**.

- **Layers:** view metadata only. Targets are `selection_ref` refs resolved every frame against live
  `designRenderer.getBackboneEntries()`; nothing is written to topology/geometry.
- **Files:** `scene/annotation_{model,targets,layout,controller,overlay,subsystem,icons}.js` (+ css),
  `ui/annotation_panel.js`, wired by one `initAnnotations(...)` in `main.js` (after `selectionManager`
  exists — its frame callback reads it). e2e: `frontend/e2e/annotations.spec.js`.
- **Rendering:** callouts are DOM/SVG in `#canvas-area` (z-index 50, pointer-events only on the manual
  grip); highlight = `THREE.Points`, `depthTest:false`, `renderOrder 1200`. Both draw over the scene.
- **Manual mode:** **Edit box in view** pins `screenPos` (fractions of the viewport,
  top-left of the rotated bounding rectangle). Drag the box or + grip to move it;
  eight edge/corner handles resize it and the ⟳ handle rotates it. Shift locks aspect
  ratio while resizing and snaps rotation to 15°.
- **Persistence:** saved IN the `.nadoc`: `Design.annotations: List[Annotation]` + `annotations_enabled`
  (models.py). Route `PUT /design/annotations` (`routes_display_metadata.py`, `mutate_display_metadata`: no undo
  entry, no feature-log entry, tiny response). Frontend: `currentDesign.annotations` is the source of truth;
  `annotation_controller` keeps a working copy, debounces 300 ms into `commit()` (subsystem: store write → the
  autosave watches `currentDesign` → backend PUT, sequential, re-asserted if a stale design response raced it).
  Wire format = snake_case (`annotationToWire/FromWire`); `refs` stored verbatim (camelCase selection refs).
  Rules: unsent/in-flight local edits are never overwritten by an incoming design; a design switch DROPS unsent
  edits (never writes into the wrong design); ordinary undo/redo keep current annotations; crossing a saved checkpoint restores it;
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
  Assembly undo/redo and feature-history seek restore explicitly checkpointed annotations; otherwise they preserve current annotations. Assembly response revisions
  reuse `createDesignRevisionTracker` to retain acknowledged notes against delayed geometry responses.
  Prepared sharing captures the same highlight UUIDs/callouts as parts.
- **Scope limits:** `__xb__` extra-base keys resolve once via `selectionManager.getBaseWorldPosition`
  (static position, not per-frame). Occupancy ignores whether a bead is hidden by a visibility filter.

**Open:** no cross-tab live sync beyond the `design-changed` broadcast. Not visually hand-checked: glow
intensity/size at low zoom, every callout type's look, placement on a dense multi-helix design.

- **Load order and font sizing (2026-11-10):** `annotation_load_gate.js` hides callouts and
  highlights until part geometry / assembly renderer readiness, opening UI completion, and a
  painted model frame. Document switches cancel stale readiness callbacks. The size control
  accepts custom positive finite pixel values (including fractions) alongside presets. Saved
  size remains a scale relative to 13 px, without the former clamp. `annotation_font_fit.js`
  bounds initial DOM/SVG font allocation and fits oversized labels inside the current viewport;
  resize refits without changing saved values. Canvas export uses the fitted display size;
  shared snapshots keep the requested size so guests fit their own view.

- **Slide-style boxes (2026-11-10):** `box_size` stores optional width/height in CSS pixels
  (32–10,000 wide, 24–10,000 high); `rotation_deg` stores the screen-plane angle.
  Legacy annotations default to automatic box sizing and zero rotation. Sidebar numeric
  width/height/angle controls mirror the viewport handles; **Auto-size box** removes
  fixed dimensions while retaining the angle. Resizing preserves the requested font size
  and wraps text; fitting finds the largest font that fits if shrinking is necessary.
  Rotation-aware bounds keep boxes on screen and leaders meet the rotated box edge.
  Gestures support cancellation and operate in local box axes. Playback/shared views
  hide editing handles; snapshots, prepared sharing, and canvas exports retain dimensions
  and angle. Shared part/assembly annotation controllers use the same implementation.
  Modules: `annotation_box_math.js`, `annotation_box_handles.js`, `annotation_box_controls.js`.
  Browser gesture coverage: `e2e/annotation_box.spec.js`.

- **Transient annotation selection (2026-11-10):** viewport and sidebar entries share
  selection via `annotation_selection.js`; viewport picks scroll the matching sidebar
  card into view, and sidebar pointer/focus interactions select its viewport box.
  Clicking elsewhere or changing documents clears selection. Only the selected box
  shows small resize squares and paired curved rotation arrows at all four corners.
  Selecting an automatically positioned annotation does not save or pin it.
  Viewport move/resize/rotation requires the manual-positioning checkbox; controls
  appear only while that annotation is also selected. Cancel restores the prior position. Icon-picker interactions
  retain selection. Selection is never stored in a design or shared presentation.
- **Corner arrow reference (2026-11-10):** rotation controls now use a filled,
  double-headed quarter-circle arrow outside each corner, mirrored horizontally
  and vertically around the box. Their clipped hit areas leave the corner resize
  squares accessible. This replaces the circular paired-arrow icon.

- Resize controls use eight sharp teal squares with dark borders, centered on the
  four corners and four edge midpoints, matching the corner-arrow reference.
- **Rendered square regression (2026-11-10):** global accessibility button styling
  imposed a 32px minimum height, stretching nominal 16px handles to 16×32px.
  Annotation handles explicitly override `min-height: 0`. The browser regression
  measures all eight actual elements (16×16px) and equal screen bounds at 30° and
  120°, in addition to gesture/selection/manual-toggle behavior.
