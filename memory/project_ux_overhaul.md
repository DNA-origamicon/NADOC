---
name: ux-overhaul
description: "Approved but deferred UX flow-change work. User has already chosen direction for each item — implement when picked up; don't re-question the decision."
metadata: 
  node_type: memory
  type: project
  originSessionId: 880cb9b6-569c-448a-ad02-08f5fd187d03
---

# UX Overhaul — Approved Deferred Work (2026-05-16)

## Shipped 2026-07-16 — workspace list hygiene (out-of-session work)

- **Engine job folders hidden from the file lists.** `ui/sim_folders.js` (new, pure + tested):
  `SIM_FOLDER_NAMES` + `isSimFolderPath(path)` + `visibleWorkspaceEntries(entries, showSimFolders)`.
  `file_browser.js` and `library_panel.js` filter through it; each toolbar gained a **"show sim
  folders"** checkbox, OFF by default. Matching is **root-segment only** — `Projects/md_jobs/x.nadoc`
  stays VISIBLE (pinned by test); and it is a heuristic, not just the literal set:
  `root.endsWith('_jobs')` means a future engine's `*_jobs` folder auto-hides with no code change.
  Backslashes are normalised first.
- **Left sidebar width is now per design file.** `sidebar_resize.js` `leftWidthStorageKey(path)` →
  `nadoc.leftPanel.width.file:<encodeURIComponent(path)>`; re-read on the existing
  `nadoc:workspace-path-change`. **An unsaved design (null path) reuses the legacy global key**
  `nadoc.leftPanel.width` (pinned). The RIGHT panel width stays global — deliberate.

Audit session 2026-05-16 produced ~25 UX flow-change proposals across the
codebase. The user reviewed and decided each one. The smaller items were
implemented in that session (see "Shipped" below). The rest are queued here
with the approved direction so a future session can pick them up.

**Don't re-litigate the decisions.** Each item below has been chosen by the
user with full awareness of the alternatives. If a tradeoff emerges during
implementation that contradicts the decision, surface it explicitly rather
than silently re-deciding.

## Shipped 2026-05-16

| Area | Change |
|---|---|
| `frontend/src/ui/toast.js` | Severity variants (info/success/warning/error), stacking, `×` dismiss, optional action button. Backward-compat with `showToast(msg, durationMs)`. |
| `frontend/src/main.js` | **F** key now frames selection bbox (strands/domains/single nuc) before falling back to fit-all. `_currentOrbitMode` initial value fixed. Selection-count HUD pill added to canvas-area. Photo mode hides view cube + mode indicator (`store.photoActive` flag set so other modules can subscribe). |
| `frontend/src/scene/view_cube.js` | rAF loop skips CSS write while hidden. |
| `frontend/src/scene/cross_section_minimap.js` | Backing store scales by `devicePixelRatio` (clamped to 2); ctx pre-scaled. |
| `frontend/index.html` | Duplicate `display:none` in `#sync-debug-panel` removed. Selection-count HUD container added. |
| `frontend/src/ui/library_panel.js` | Search input above sort bar; auto-expands folders with matches. |
| `frontend/src/cadnano-editor/main.js` | **Esc** drops back to Select tool when not in help modal. |
| `frontend/src/ui/feature_log_panel.js` | Floating label follows rail thumb during drag. |
| `frontend/src/ui/polymerize_panel.js` | Live colored cost preview; blocking confirm only fires at ≥20. |
| `frontend/src/ui/extrude_panel.js` | A/B style alternates removed (Fusion-style retained). |
| `frontend/src/input/drag_scrub.js` | NEW: drag-scrub helper for `<input type=number>`. Wired in polymerize, animation, extrude panels. |
| `frontend/src/main.js` + `frontend/src/cadnano-editor/main.js` + `frontend/src/ui/library_panel.js` | All 117 `alert()` calls rewritten to `showToast(msg, { severity: 'error' })`. Script at `/tmp/alert_to_toast.py` (regex-literal aware version recommended; current version has a one-line gap on regex-literal-containing functions — caught by `grep -c "alert("` after the script and fixed by hand). |
| `frontend/src/scene/photo_renderer.js` | Bloom-related fix: PMREM env bake reordered to AFTER composer creation in `activate()` (was producing black/colored-filter viewport because PMREMGenerator side effects contaminated freshly-created composer RTs). Also: bloom slider drags no longer dispose+rebuild the composer — just tweak `bloomPass.strength/radius/threshold` uniforms when bloom is already enabled. |
| `frontend/src/scene/assembly_renderer.js` + `frontend/src/main.js` | Added `assemblyRenderer.onRebuildComplete(fn)` subscriber API. `_rebuildOverhangLocations()` now subscribes to it, fixing overhang-location arrows vanishing after every assembly rebuild (was hooked to 1 of 9 rebuild sites in main.js). |
| `frontend/src/ui/assembly_context_menu.js` + `frontend/src/main.js` | Right-click on a part instance now exposes Show/Hide, Edit Part…, Duplicate, Polymerize…, Delete in addition to the existing Repr/Move-Rotate/Define-Connector/Fixed/Allow-Joints. Verbs are opt-in via callbacks (`onToggleVisible`, `onEditPart`, `onDuplicate`, `onPolymerize`, `onDelete`); sidebar (`assembly_panel.js`) continues to expose the same actions independently. |
| `frontend/src/ui/overhangs_manager_popup.js` + `assembly_overhangs_manager_popup.js` + `frontend/index.html` | Connection-Types tab: filter input above each side list (A/B) — case-insensitive substring on overhang label; auto-keeps the currently-selected overhang visible. Linker/binding table: clickable column headers (Name/Type/Length/Overhangs/Bound) toggle sort with ▲/▼ arrow, plus sticky `<thead>`. Both per-part popup (`#ct-list-search-{a,b}` + `#ct-table`) and assembly popup (`#aohc-list-search-{a,b}` + `#aohc-table`). Assembly variant additionally filters across part name + overhang name, auto-expanding any part with a matching overhang. |
| `camera_panel.js` + `photo_panel.js` + `bend_twist_popup.js` + `main.js` Move/Rotate panel | dragScrub helper wired in (in addition to polymerize/animation/extrude from before). Coverage now: camera pose FOV (re-attaches per `_rebuild`), photo-mode controls (lighting / bloom / fluoro / mist sliders), bend/twist plane-bp inputs, cluster Move/Rotate tx/ty/tz/rx/ry/rz/joint-angle. Joints panel and deformation_editor have no number inputs to scrub — skipped intentionally. |
| `frontend/src/ui/primitives/confirm.js` (new) + `main.js` + `feature_log_panel.js` + `polymerize_panel.js` | Promise-returning `showConfirm({title, message, danger, confirmLabel, cancelLabel})` modal primitive built on `createModal`. Replaces 9 `window.confirm(...)` calls in the original alert→toast follow-up scope: main.js (clear-all loops/skips, delete strand from palette, assembly atomistic warning), feature_log_panel.js (delete loadout, revert FineRouting cluster, revert-to-before-feature design + assembly, delete assembly feature), polymerize_panel.js (large-polymerize gate at ≥20 new instances). Dangerous prompts focus the Cancel button by default; non-destructive focus Confirm. |
| `frontend/src/scene/selection_manager.js` + `main.js` + `.claude/rules/selection.md` | Selection-modifier remap (2026-05-17): Ctrl-drag = lasso (unchanged), Alt-click = measurement-bead pick (moved from Ctrl-click), Shift-click = additive multi-select (toggle hit strand in `multiSelectedStrandIds`; also toggles crossover arc in multi-arc set when `selectableTypes.crossoverArcs` is on). Ctrl-click no-drag is now a no-op. Capture-phase listener disables OrbitControls on Ctrl/Alt/Shift+left to prevent pan/rotate competition. One-time startup toast (gated on `localStorage` key `nadoc.hint.selModifiers.v1`) hints users to the new bindings. |
| `frontend/src/ui/feature_log_panel.js` + `animation_panel.js` + `main.js` | Animation panel's "State" picker: flat `<select>` of every feature_log entry replaced with a **Pin to feature** button. Button label shows current pinned feature (or "— not pinned —"); when pinned, a `×` Unpin button appears alongside. Clicking the pin button calls `main.js`'s `pinToFeature()`, which switches the left sidebar to the feature-log tab and calls a new `featureLogPanel.enterPickMode(callback)` API. The user clicks a feature row; the callback receives the feature index, the FL panel exits pick mode, and the sidebar switches back to the Scene tab. Pick mode renders a blue banner ("Click a feature to pin the keyframe to. [Cancel]") at the top of the FL panel and re-routes row clicks from seek to callback. Assembly mode keeps its existing configuration `<select>` (configurations are small named sets and don't have the scaling problem). |
| `frontend/src/scene/overhang_binding_lines.js` (new) + `main.js` | Dashed 3D connectors between overhang pairs that have an `OverhangBinding` record. Bound = solid green; unbound (pre-bind) = translucent amber. Endpoints use a representative backbone position per overhang. Module exposes `rebuild(design, geometry)`, `setVisible(v)`, `hitTest(raycaster)`. Main.js wires a store subscription so lines rebuild on design/geometry change (skipped in assembly mode — `OverhangBinding` is per-part). Right-click on a binding line opens a small custom context menu with **Bind / Unbind** and **Delete binding** (uses `showConfirm` for delete). The original audit assumed this line already existed; in reality it was never shipped — added here. Cross-part `AssemblyOverhangBinding` not yet covered (follow-up). |

## Queued — Batch B leftovers (still open)

### Assembly context menu — Polymerize-From-Mate (joint-targeted variant)
The instance-targeted Polymerize… entry is shipped (opens the panel; user picks mate inside). The joint-targeted variant ("right-click a joint indicator → Polymerize from this mate") is deferred — it needs the contextmenu handler to call `assemblyRenderer.pickPartJoint(ndc, camera)` first, fall through to `pickInstance` if no joint hit, and then call `polymerizePanel.setSelectedJoint(jointId); polymerizePanel.open()` for the joint case. ~30 lines in `_onAssemblyContextMenu` + a small new context-menu variant.

### Part-origin gizmo follow-up: centroid anchor + bounding-box leaks — SHIPPED 2026-05-17 (session 2)

User reported that after the earlier phantom-instance fix, a mysterious gold/white "icon" was still floating at each part's part-local origin, the bounding box extended far past visible geometry, and the Move/Rotate gizmo planted at the part-local origin rather than visible center. Iterative inspector-driven debugging found four overlapping causes; all fixed:

1. **Centroid-anchored Move/Rotate gizmo.** `frontend/src/scene/instance_gizmo.js` now accepts a world-space `centroidWorld` parameter. When supplied, the dummy is placed at the centroid and the centroid is cached in instance-local coords (`_centroidLocal = inv(instance_mat) · centroidWorld`); on every drag frame the recovered instance world matrix is `dummy · T(-centroid_local)`. Wired in `main.js _attachGroupGizmo` to pull the centroid from `assemblyRenderer.getInstanceCenters()`. Solves: gizmo placement on parts (e.g. polymerize-seeded) whose part-local origin sits well outside the visible structure.
2. **World-origin AxesHelper masquerading as a part gizmo.** `main.js` allocated `originAxes = new THREE.AxesHelper(4)` at world (0,0,0) and added it to the scene visible-by-default. When a part's centroid happened to be near the world origin (always true for the first instance in a fresh assembly), the helper read as "part-specific." Fix: `originAxes.visible = false` at init; `is-on` class removed from `#menu-view-axes` in `index.html`. **View > Origin Axes** toggle still flips it on for users who want the world frame.
3. **Part-joint indicator opt-in only.** `assembly_renderer.js _rebuildPartJointIndicators` no longer renders the orange-passive variant on every part. Indicators are built only when `inst.allow_part_joints === true` (the explicit right-click → "Allow Part Joints" opt-in). Removed the passive `0xff8c00` color path entirely; the only variant left is the highlighted yellow `0xffff88` at scale 2x. Indicators appear/disappear immediately when the user toggles the context-menu checkbox (`api.patchInstance` updates the store, which triggers the renderer's rebuild). Shaft/tip/ring meshes additionally got `userData.skipBounds = true` so they don't bloat the BoxHelper even when shown.
4. **Bounding-box leaks → see LESSONS D4.** `_computeGroupBox` in `assembly_renderer.js`:
   - Empty `InstancedMesh` (`count === 0`) was falling through to the regular-Mesh branch and contributing its **template** geometry's bounding box (e.g. an unpositioned fluorophore sphere) at the instance origin — pulling minZ down to ~0 even though no fluorophores existed.
   - Per-leaf `visible` check missed hidden parent groups (e.g. `_curvedCylGroup.visible = false`'s TubeGeometry children whose own `visible` was true). Fix: walk the parent chain via `_isVisibleUnder(obj, stopAt)`.
   - Both fixes flow through to `getInstanceCenters()` (same `_computeGroupBox` call), so the gizmo centroid is now also tight.

**New diagnostics that stay in the codebase:**
- `window.__nadocInspect.toggle()` — Ctrl+Shift+I scene-object inspector with click-to-table output. Now reports `instanceId`, `instanceLocalPos`, `instanceWorldPos`, `instanceScale`, `instanceColor`, and `flags` (NaN/zero/huge scale) for InstancedMesh hits. Visibility check upgraded to walk the parent chain (was leaf-only, surfacing false hits on hidden subtrees).
- `window.__nadocBoxAudit(instanceId?)` — dumps every mesh's contribution to the active instance's bounding box, sorted by extent. Outliers section flags rows reaching the global min/max on any axis. Use whenever the BoxHelper looks too big.

### Scene inspector debug overlay + phantom-instance + workspace-grid fixes — SHIPPED 2026-05-17
A user-reported "part-specific origin gizmo" in an assembly turned out to be **multiple overlapping things**, isolated using a new debug tool.

**New: `frontend/src/scene/scene_inspector.js`** — Ctrl+Shift+I toggles an inspect mode. Click any 3D object → console.table + toast with: type, name, material, color, world position, userData, ancestor chain up to scene root, plus the top 3 hits if stacked. Filters by `obj.visible` so invisible-but-pickable proxies still surface. Available as `window.__nadocInspect.toggle()` for console use. Tagged the joint-indicator groups in `joint_renderer.js` (`name: 'clusterJointIndicator'`) and `assembly_joint_renderer.js` (`name: 'assemblyMateIndicator'`) so they're easy to identify when hit.

**Bug 1: workspace plane-picker grid leaked into assembly view.** The XY/XZ/YZ semi-infinite faded grid planes from `workspace.js` (intended for the new-design lattice-orientation picker) were still in the scene when an assembly was opened. Fix in `main.js _enterAssemblyMode`: explicit `workspace.hide()` on assembly entry. Inspector confirmed the hit-target `MeshBasicMaterial` (`userData.planeName: 'XZ'`) at world origin.

**Bug 2: phantom InstancedMesh instances at world origin.** All four cylinder InstancedMeshes in `helix_renderer.js` allocated with `Math.max(1, count)` capacity — required because Three.js refuses size-0 InstancedMesh. But when `count === 0`, the single phantom instance rendered with the default all-zero `instanceMatrix`, which produces NaN/degenerate vertices that show as a small floating shape at world (0,0,0). Visible in coarse-LOD ("cylinders" rep — the assembly clone default) for designs with no curved-helix overhangs (most designs). Fix: set `mesh.count = realCount` right after construction; Three.js honours `.count` for rendering regardless of capacity, so count=0 renders nothing. Applied to all four meshes (helixCylinders, curvedHelixCylindersProxy, overhangCylinders, curvedOverhangCylindersProxy). Long comment block documents the pattern for future readers.

### Modal migrations #3-4 — autobreak / background — SHIPPED 2026-05-17
- `#autobreak-modal` → `<div id="autobreak-modal-body">` + lazy createModal. Cancel + Run Autobreak in actions row. Was wrapped in an IIFE that holds local state (`_animTimer`, `_runAutoBreak3d`); preserved the IIFE pattern.
- `#background-modal` → `<div id="background-modal-body">`. Three-button action row: Cancel + Reset + Apply (Cancel is just close; Reset rolls back state and re-syncs; Apply is also just close — the form already mutated state via input events). The "Apply Underwater Theme" button stays inside the body since it's a content action, not a footer verb.

### Modal migration bug + #5 gromacs-export — REMOVED 2026-05-17
A migration mistake on gmx + bg: I called `body.removeAttribute('hidden')` at module-init time (top of the IIFE), not inside the `_build*ModalOnce()` lazy-build function. Effect: the body div rendered **inline in the page above the canvas** until the modal was opened. Visible on `#background-modal-body` and `#gromacs-export-modal-body`.
- **Fix for background:** moved `removeAttribute('hidden')` inside `_buildBackgroundModalOnce()` so the unhide happens after createModal reparents the body into the detached overlay.
- **gromacs-export-modal:** user requested removal pending a clean re-implementation. The `<div id="gromacs-export-modal-body">` block in `index.html` is now an HTML comment. The dialog wiring (`_buildGmxModalOnce`, `_onGmxExport`, the poll loop against `/api/design/export/gromacs-status/{jobId}`) is also removed; menu item shows a "GROMACS export is being re-worked" toast. TODO comments in both `index.html:2845` and `main.js:10517` describe what to re-add (and remind the next person to **unhide inside the build function, not at IIFE init**). The original implementation is in git history under commit b97f44a's pre-state.

### Modal recipe — REVISED
The original `index.html`-based hidden body + `removeAttribute('hidden')` at init pattern is brittle. New rule for the remaining migration (overhangs-manager pair): keep `hidden` on the body DIV. Inside `_build*ModalOnce()`, after the body is grabbed but before passing to `createModal`, call `body.removeAttribute('hidden')`. CreateModal then reparents the body into its detached overlay; the unhide doesn't cause a flash because the overlay isn't in the document until `.open()`.

### Modal migration #2 — `#assign-scaffold-modal` — SHIPPED 2026-05-17
Same recipe as the new-design pilot. Outer wrapper replaced with `<div id="assign-scaffold-modal-body" hidden>`; Cancel/Apply lifted to `actions`; inline styles tokenized. `modal.dataset.targetStrandId` replaced with a module-level `_ascTargetStrandId` variable (the dataset trick relied on the outer modal div which no longer exists). Existing event wiring (radio change → `_ascUpdateWarning`, textarea input → char count + invalid char check) moved into `_buildScaffoldModalOnce()` so it attaches just once. Enter on the body commits, except inside the textarea where Enter inserts a newline.

### Modal migration pilot — `#new-design-modal` — SHIPPED 2026-05-17
First hand-rolled modal migrated to `createModal()`. Pattern:
- HTML: the outer `<div id="new-design-modal" style="display:none;...">` wrapper is replaced with a hidden `<div id="new-design-modal-body" hidden>` containing just the form fields (warning + name input + lattice radios). All field IDs preserved (`#new-design-name`, `#new-design-unsaved-warn`, `#new-design-name-error`, `input[name="new-lattice-type"]`).
- Inline styles updated to use design tokens (`var(--color-bg-canvas)`, `var(--text-sm)`, etc.) instead of literal hexes.
- Cancel + Create buttons removed from HTML — they're now `createButton`-created and passed to the modal's `actions` array.
- `main.js`: `_openNewDesignModal()` lazily builds the modal via `createModal({title:'New Part', size:'sm', body:_newDesignBody, actions:[cancelBtn, createBtn]})` on first open; subsequent opens call `modal.open()` on the cached controller. Form reset (clear name, hide warn, etc.) happens before each open. Enter on the name input commits via a one-line keydown handler.
- Removed: manual Escape/Enter keydown handler (createModal already handles Escape + backdrop close), inline `display:none/flex` toggle, hardcoded modal chrome styles.

Pattern for the remaining 5 modals: same recipe — replace outer wrapper with a hidden body div, lift Cancel/primary buttons to `actions`, lazy-build on first open, cache the controller.

### Mate preview during 2nd-connector pick — SHIPPED 2026-05-17
`frontend/src/scene/assembly_joint_renderer.js` `_onMatePointerMove` now drives a live ghost-preview of where `instance_b` will land while the user is hovering candidate second connectors (after they've clicked the first). Uses the existing `_computeAlignTransform` / `_onLivePreview` machinery — same code path the post-pick preview already used, just wired to hover instead of click. Honors the existing "Preview" checkbox in the mate sidebar. Cleared on hover-off, pointer-leave, or pick of the second connector (the existing click handler then re-applies the same transform as a settled preview). Settles into the actual joint on Create Mate.

### Configurations consolidation into FL panel — SHIPPED 2026-05-17
`assembly_config_panel.js` deleted; its DOM block removed from `frontend/index.html`. Configurations now live in the existing Feature Log panel via a new "Configurations" option in the assembly target dropdown. Implementation:
- `_configurationsMode` flag (module-level) re-enables the previously-dead `_isAssemblyConfigMode()` path.
- Selecting "Configurations" sets `_configurationsMode = true`, fires `_rebuildAssembly(assembly)` (existing dead-but-correct rendering path).
- `_refreshTitle` switches the panel title to "Configurations" and shows the "+ Capture Configuration" button only in this mode; hides Loadouts (design-mode concept).
- `_renderCurrentView` routes to `_rebuildAssembly` when in config mode, ahead of the "select a part" prompt branch.
- `main.js` import + `initAssemblyConfigPanel(...)` call removed.

### Gizmo axis colors — N/A (already correctly implemented)
Audited 2026-05-17. The "RGB-by-axis for axis-aligned constraints, custom colors for bond-aligned" convention is already in place: cluster gizmo in `centroid` mode + instance gizmo + overhang gizmo all use native `THREE.TransformControls` (RGB by default); cluster gizmo in `joint` mode is intentionally orange because the axis is along a joint bond; sub-domain θ/φ rings stay gold/cyan for the same reason. The audit's premise was wrong — no work needed.

### Feature-log schema edit popover — SHIPPED 2026-05-17
`frontend/src/ui/edit_feature_popover.js` (new) — schema-driven modal editor for feature_log entries. Hardcoded `OP_SCHEMAS` table keyed by `op_kind` declares the editable fields per op (type/min/max/options/etc.); the popover builds one labelled input per field, validates on Save, resolves with the patch object (or null on cancel). Built on `createModal` + `createButton`. Replaces:
- Design-mode prompt at `feature_log_panel.js:1095` (length_bp for bundle-create / extrude-segment / extrude-continuation / extrude-deformed-continuation / overhang-extrude)
- Assembly-mode prompts at `feature_log_panel.js:1436` (assembly-polymerize: count + direction; assembly-overhang-connection-add/patch: length_value + length_unit + bridge_sequence)

Adding a new editable op_kind is a one-line addition to OP_SCHEMAS. `editFeature(...)` returns null when the op_kind isn't in the schema (shows a toast). Caller can fall back if needed; for now both call sites just abort.

### Panel resize — SHIPPED 2026-05-17
`frontend/src/ui/sidebar_resize.js` (new) + CSS rules in `frontend/index.html` (`.panel-resize-handle`) + 4-px handle `<div>` injected at the inner edge of `#left-panel` and `#right-panel`. Drag updates `style.width`; clamps to 200–600 px; releases below MIN_PX*0.5 snap the panel shut via the existing `.hidden` class. Width persists to `localStorage` keys `nadoc.leftPanel.width` / `nadoc.rightPanel.width`, restored on init by `initSidebarResize()` (called from main.js right after the left-sidebar tab wiring). The canvas re-fit is already handled by the existing ResizeObserver on `#canvas-area` — no extra plumbing needed. During drag, the left panel's CSS `transition: width 0.15s` is temporarily suppressed so it doesn't lag behind the pointer.

### Remaining confirm() migrations — SHIPPED 2026-05-17
Every `window.confirm()` in the frontend has been migrated to `showConfirm` (from `frontend/src/ui/primitives/confirm.js`). Total: 18 callsites across 9 files (9 in the first pass, 9 in this follow-up). Files touched in this follow-up:
- `frontend/src/scene/selection_manager.js` — Delete linker
- `frontend/src/ui/file_browser.js` — Overwrite file, Delete folder, Delete file
- `frontend/src/ui/assembly_panel.js` — Delete connector in use, Apply atomistic representation
- `frontend/src/ui/assembly_context_menu.js` — Atomistic warning
- `frontend/src/ui/library_panel.js` — Delete folder, Delete file
- `frontend/src/ui/overhangs_manager_popup.js` — Delete binding, Delete linker
- `frontend/src/ui/domain_designer_panel.js` — Delete binding
- `frontend/src/ui/photo_panel.js` — Overwrite profile (×2), Delete profile (sync handlers became async)
- `frontend/src/cadnano-editor/main.js` — Clear loops/skips (mirrors main.js path)

No `confirm(` calls remain in `frontend/src/` other than a single past-tense comment in `polymerize_panel.js:244`.


### 2. Assembly context menu: add Duplicate / Delete / Edit Part / Show-Hide / Polymerize From Mate
**File:** `frontend/src/ui/assembly_context_menu.js`
**Decision:** add all five verbs. Sidebar (`assembly_panel.js:297-403`) keeps the same actions; the menu colocates them with the object.
**Polymerize-From-Mate** is only valid when the right-click hit is on a joint indicator — gate that entry on `_lastRightClickedKind === 'joint'` and call into `polymerizePanel.setSelectedJoint(jointId)` followed by `polymerizePanel.open()`.

### 3. Right-click verb on the dashed pre-bind 3D line → toggle bind
**Files:** the dashed line is drawn somewhere in `overhang_link_arcs.js` or `crossover_connections.js` (verify which renders the pre-bind line). Hook a raycast hit into selection_manager's context menu, expose a "Toggle bind" entry that calls the existing bind/unbind API.

### 4. Selection modifier semantics: measurement → Alt; Ctrl/Shift = additive selection
**File:** `frontend/src/scene/selection_manager.js`
**Decision:** Move measurement pick (`_ctrlBeads`) from Ctrl-click to Alt-click. Ctrl-click and Ctrl-drag still do lasso; Shift+click now adds to multi-selection. Update `path-scoped rules/selection.md` after.
**Risk:** muscle memory. Add a single startup toast or status-bar hint the first time the user holds Ctrl, pointing to the new mapping.

### 5. Overhangs Manager + CT-tab: sortable columns + sticky header + filter input
**Files:**
- `frontend/src/ui/overhangs_manager_popup.js` — two list panels need a search input each; rows need to honour a sort key.
- `frontend/src/ui/spreadsheet.js` and the CT-tab table (find via grep) need `<thead position:sticky;top:0;background:var(--color-bg-surface)>` and click-on-header sort.

### 6. Animation panel "Pin to feature" button → FL picker mode
**File:** `frontend/src/ui/animation_panel.js`
**Decision:** Per-keyframe button (replaces the flat `<select>` at lines 603-628). Click pin → right sidebar switches to FL panel in a special "pick" mode, user clicks a feature row, FL panel closes, keyframe's `state_at_feature_id` is set.
**Plumbing:** FL panel needs a `enterPickMode(callback)` / `exitPickMode()` API. Keyframe row stays in the animation panel; only the picker UX changes.

### 7. dragScrub rollout — SHIPPED 2026-05-17
Helper applied to: polymerize_panel, animation_panel, extrude_panel (Batch B initial), then camera_panel (per `_rebuild`), photo_panel, bend_twist_popup, main.js Move/Rotate panel. Joints panel and deformation_editor had no number inputs — intentionally skipped. **Still skipped:** spreadsheet cell editors (text-focus required), assign-scaffold-modal sequence offset input.

## Queued — Batch C (each is its own session)

### 8. Migrate remaining hand-rolled modals to `createModal()` primitive
**Decision:** one at a time. Pilot + 3 follow-ups shipped 2026-05-17 (new-design, assign-scaffold, autobreak, background). Remaining:
1. `#gromacs-export-modal` — removed during the pass because of the unhide-at-init bug; re-implement using the revised recipe (see "Modal recipe — REVISED" in Shipped section). Stub toast wired so the menu item doesn't crash.
2. `#overhangs-manager-modal` + `#assembly-overhangs-manager-modal` (paired) — the biggest pair (tabs, lists, table inside); deserves its own session
**Pattern (from pilot):** replace outer wrapper with a hidden body div; preserve all inner IDs; lift Cancel/primary buttons to `actions`; lazy-build on first open and cache the controller; remove inline `display:none/flex` toggles and the hand-rolled Escape/Enter handler (createModal owns those).


## Queued — Batch D (largest)

### 14. AbortController + backend abort endpoints
**Decision:** True cancellation, including server-side.
- Frontend: `api/client.js` creates an AbortController per long fetch, passes `signal` and registers `onCancel: () => ctrl.abort()` with `op_progress`.
- Backend: New `POST /op/{op_id}/abort` endpoint. Long solvers (autostaple, autobreak, scaffold_router, seamless_router, GROMACS exporter, atomistic builder) need to be refactored to (a) generate an op_id, (b) check a cancellation flag periodically.
**Order:** Frontend signal wiring first (free cancellation for short ops). Then backend abort endpoint, one solver at a time.

### 15. Validation Report: clickable rows + severity + jump-to-locate
**File:** `frontend/src/ui/validation_report_panel.js`
**Decision:** Each row becomes a button that calls `store.setState({ selectedObject: ... })` and `_centerOnStrand(strandId)`. Add severity column (info/warn/fail) with token colours. Rename the `validation_panel.js` (dead handedness checkpoint walkthrough) to "Renderer Checkpoints" if/when it's revived — currently it's not imported anywhere so the rename was N/A in 2026-05-16 session.

## Deferred indefinitely (not on roadmap)

- Command palette expansion (user explicitly deferred 2026-05-16)
- OrbitControls damping (user kept current 2026-05-16)
- Drag-marquee in cadnano select tool (audit suggestion, no user decision yet)
- Preset thumbnails in `presets_panel.js`
- Keyboard nav (arrow keys) in list popups (mate list, instance list, FL, configurations, keyframes)
- Hover tooltip with strand_id/helix_id/bp on raycast hit (medium-risk; conflicts with current cursor management)
- Custom hover cursor change when over selectable instances (same reason as above)

## How to apply

1. Pick one item, open the file(s) it points to.
2. Check whether the codebase shape still matches what's described — file/line refs are from 2026-05-16.
3. Implement. Each item is independent.
4. After ship: cross it off this file (delete the entry), update `MEMORY.md` if needed.

**Why:** This file is the single record of *what* and *why* — losing it means re-running the audit and re-asking the user, which they explicitly invested time in to avoid.
**How to apply:** open it whenever picking up UX work; treat each entry as a small spec.
