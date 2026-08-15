---
name: ux-overhaul
description: "Approved-but-deferred UX flow work. User already chose the direction for each item — implement, don't re-question. Rank P2."
metadata: 
  node_type: memory
  type: project
  originSessionId: 880cb9b6-569c-448a-ad02-08f5fd187d03
---

# UX Overhaul — Approved Deferred Work

**Rank:** P2 — the remaining items are UI polish, nothing is blocked on them, and two of the
four have softened (item 15's target is orphaned; item 14's backend half is a large refactor).
But this file is the **sole owner** of the file-browser / library-panel / sidebar / modal /
toast ground — no `.claude/rules/*.md` and no other topic file covers it (probed 2026-07-31).

**Status (probed 2026-07-31):** the 2026-05-16 audit produced ~25 UX proposals; the user decided
each one. Everything in Batches A/B shipped except **one** (joint-targeted Polymerize). Batch C
has one real item left. Batch D is untouched. History → `project_ux_overhaul_archive.md`.

**Accessibility pass (2026-08-13):** the legacy top menu now has keyboard/ARIA menu semantics;
the shortcut help is generated from `input/shortcuts.js`; editable controls block design-level
file/edit shortcuts; Space is reserved for native control activation outside the workspace;
toasts are live regions; the WebGL workspace is labelled; and pointer-styled static/dynamic UI
rows receive button keyboard semantics through `ui/accessibility.js`. The user explicitly retained
canvas Tab selection-level cycling and the expert Delete/x/1–6 bindings.

**Don't re-litigate the decisions.** Each item was chosen by the user with full awareness of the
alternatives. If a tradeoff emerges during implementation that contradicts the decision, surface
it explicitly rather than silently re-deciding.

## Corrections from the 2026-07-31 audit (the archive is wrong about these)

| Archive claim | Reality |
|---|---|
| Item 7 `input/drag_scrub.js` "SHIPPED", wired into 7 panels | **File does not exist.** Zero hits for `dragScrub`/`drag_scrub` anywhere in `frontend/src`; none of the 7 named panels reference it. Removed at an unknown date, unrecorded. `frontend/src/input/` holds only `shortcuts.js`. **User decision pending** (parked in `plan_audit_ledger.md` HOLD) |
| `scene/overhang_binding_lines.js` shipped (dashed pre-bind connectors + Bind/Unbind menu) | **Deleted 2026-07-01** with `ui/overhang_binding_menu.js`; recorded in [[project_overhang_duplex_foundation]]:112, never crossed off here. Item 3's *own* file guesses (`scene/overhang_link_arcs.js`, `scene/crossover_connections.js`) both still exist |
| Part-origin fix #2: `originAxes.visible = false` at init | **Reverted.** `main.js:274-276` is `visible = true`; `_syncOriginAxesForEmpty` (`:279-285`) force-shows the triad for an empty part and never auto-hides. The "helper masquerading as a part gizmo" rationale no longer describes the code |
| GROMACS TODOs at `index.html:2845` and `main.js:10517` | `index.html:3302-3308`; **main.js is 8,070 lines** — the wiring moved to `ui/export_menu.js:330-338` (TODO :330, stub toast :338, pinned by `ui/export_menu.test.js:265`) |
| `_onAssemblyContextMenu` in `main.js` | **Moved** → `scene/assembly_pointer.js:591` (`onAssemblyContextMenu`); `main.js:6228` is a one-line `deferrableContextMenu` wrapper. `_lastRightClickedKind` = 0 hits repo-wide |
| `_openNewDesignModal`, `_attachGroupGizmo` in `main.js` | Both **moved**: `ui/new_design_modal.js` (`initNewDesignModal:40`) and `scene/group_gizmo.js` (`main.js:4896` is an alias). Still in main.js: `pinToFeature:6737`, `_enterAssemblyMode:3613`, `_rebuildOverhangLocations:1664`, `originAxes:274` |

## Live code — where this subsystem actually is (probed 2026-07-31)

| Thing | Location |
|---|---|
| Sim-folder hiding | `ui/sim_folders.js` — `SIM_FOLDER_NAMES:2`, `isSimFolderPath:17` (`root.endsWith('_jobs')` heuristic :19), `visibleWorkspaceEntries:22`. Importers: `ui/library_panel.js:14`, `ui/file_browser.js:16` — **both** pass the flag (`library_panel.js:245`, `file_browser.js:381`). Checkboxes OFF by default (`library_panel.js:121`, `file_browser.js:71`) |
| Per-file sidebar width | `ui/sidebar_resize.js` — `leftWidthStorageKey:26`, legacy global `LS_LEFT:23`, `nadoc:workspace-path-change` listener `:115-119` (left only), RIGHT stays global `:55-57`. Sole importer `main.js:180` |
| Modal primitive | `ui/primitives/modal.js` `createModal` — 22 call sites |
| Confirm primitive | `ui/primitives/confirm.js` `showConfirm` — ~25 call sites, **zero tests** |
| Toast | `ui/toast.js` — 374 call sites, **1 test** |
| Selection modifiers | `scene/selection_manager.js:3284` (capture-phase orbit disable), `:3300` Alt = bead, `:3304` Shift = additive, `:3308` Ctrl = lasso. Hint toast + `nadoc.hint.selModifiers.v1` at `main.js:1008-1017` |
| FL pick mode | `ui/feature_log_panel.js` `enterPickMode:1911` / `exitPickMode:1917`; `pinToFeature` `main.js:6737` → `ui/animation_panel.js:100` |
| Configurations-in-FL | `_configurationsMode` `ui/feature_log_panel.js:68,179,225,364,374,383`. `assembly_config_panel.js` confirmed deleted (tombstone `main.js:155`) |
| Scene inspector | `scene/scene_inspector.js` — Ctrl+Shift+I `:172`, `window.__nadocInspect:202`, wired `main.js:181`. `window.__nadocBoxAudit` `main.js:4686` → `assembly_renderer.js:1376` |
| CT-tab sort/filter | `index.html:2980,3019` + `:3192,3231` (search inputs), sticky thead `:3078-3084`, `:3281-3287`; wiring `overhangs_manager_popup.js:224,2035`, `assembly_overhangs_manager_popup.js:129,1051` |

## Open items

### 1. Polymerize-From-Mate (joint-targeted right-click) — the last Batch B item
Both anchors are alive: `assemblyRenderer.pickPartJoint` (`scene/assembly_renderer.js:1032`,
exported `:1786`; **no-op stub** in `assembly_renderer_shared.js:88` — and shared is now the
default renderer, so check that first) and `polymerizePanel.setSelectedJoint`
(`ui/polymerize_panel.js:606`). The right-click chain is `scene/assembly_pointer.js:591-636`
(overhang arrows → linker → belt → `pickInstance`) and **never calls `pickPartJoint`** — that is
the ~30-line edit, now in `assembly_pointer.js`, not `main.js`. The instance-targeted entry is
`ui/assembly_context_menu.js:207-208`; `show(inst, x, y)` (`:82`) takes no joint.
**Partly obsolete:** `setSelectedJoint` already ships on a *different* gesture —
`assembly_pointer.js:236-243` intercepts left-click while the polymerize panel is open and calls
it via `assemblyJointRenderer.pickJointAny(e)`. Decide whether the right-click variant is still
wanted before building it.

### 8. Migrate the overhangs-manager modal pair to `createModal()`
The only *real* remaining migration. Still hand-rolled: `index.html:2831`
(`#overhangs-manager-modal`) and `:3179` (`#assembly-overhangs-manager-modal`), both
`style="display:none;position:fixed;inset:0;…"` wrappers toggled directly —
`overhangs_manager_popup.js:1726`/`:1749`, `assembly_overhangs_manager_popup.js:175`/`:203`.
Neither file imports `createModal`. **The anti-pattern has since spread:**
`ui/conjugate_manager.js:330` explicitly "mirrors #overhangs-manager-modal" — a third
hand-rolled overlay written after this doc. Migrating the pair should take it too.
GROMACS export (`#gromacs-export-modal`) is still removed-with-a-stub-toast; re-implement only
when the exporter itself is re-worked.

**Modal recipe — REVISED (use this).** Keep `hidden` on the body DIV. Inside
`_build*ModalOnce()`, after grabbing the body but **before** passing it to `createModal`, call
`body.removeAttribute('hidden')`. Doing it at IIFE-init instead renders the body inline above
the canvas — that bug is what killed the gromacs migration.

### 14. AbortController + backend abort endpoints — frontend half is nearly free
Backend is **untouched**: no `POST /op/{op_id}/abort`, no op-keyed cancel flag (the only `op_id`
hits are unrelated deformation record IDs in `routes_deformation.py`).
Frontend is **further along than the doc knew, and mis-wired**: `ui/op_progress.js:47` already
accepts `onCancel` and renders `#op-progress-cancel` (`_cancelHandler:19-35`) — but
`api/client.js:337` calls `showOpProgress(...)` **without** it, so the busy popup that wraps
every request is uncancellable. Only `ui/animation_panel.js:1419,1489` pass `onCancel`.
`api/client.js:309` does mint an AbortController, but it is `_timeoutCtrl` (hard request
timeout), not a user cancel; it forwards a caller-supplied `signal` at `:312-315`.
~14 viz modules mint their own controllers (`oxdna_display.js:390`, `mrdna_display.js:76`,
`cando_display.js:152`, `oxdna_jobs_panel.js:810,936`, `animation_player.js:422`, …).
**Cheapest first step:** give `client.js` a per-request controller and pass `onCancel` into
`showOpProgress` — that alone buys cancellation for every short op, no backend work.

### 15. Validation Report: clickable rows + severity + jump-to-locate — RE-SCOPE BEFORE BUILDING
`ui/validation_report_panel.js` exists (41 ln) but has **0 importers**, and its mount point
`#validation-report-content` **does not exist in `index.html`** — implementing this as written
edits a module nothing loads. Rows are interpolated `<div class="vr-row">`, severity is binary
(`r.ok` → `vr-ok`/`vr-fail`). `ui/validation_panel.js` (165 ln, `initValidationPanel:138`) is
likewise unimported. Both are already triaged as **HELD** in [[project_tech_debt]]:98,103 —
which cites *this* item as the reason they're held. Circular: decide the panel's fate there
first (mount it or delete it), then this item is either a real feature or moot.

### 16. `showConfirm` destructive sites missing `danger: true` (new, found 2026-07-31)
Three delete actions focus **Confirm** by default instead of Cancel:
`ui/assembly_panel.js:1433` (Delete gear relation), `:1595` (Delete belt path),
`ui/chain_sim_panel.js:178` (Delete chain project). Every other `Delete*` site passes `danger`
(`file_deletion.js:59`, `assembly_panel.js:239,642`, `overhangs_manager_popup.js:2154,2459`,
`domain_designer_panel.js:817`, `overhang_connections_panel.js:1070,1137`,
`selection_manager.js:105`, `main.js:4055,4553`). One-word fix each.

### 17. `ui/import_menu.js` never migrated off the legacy `showToast(msg, ms)` form (new)
4 sites — `:84,134,186,219`, all `showToast('…coordinate convention.', 8000)` — the only file of
374 call sites still on the numeric-2nd-arg form. It still works (`ui/toast.js:6` keeps
back-compat), so this is hygiene, not a bug.

### 18. Test debt on the primitives this overhaul created (new)
`ui/primitives/confirm.js` (~25 consumers) and `ui/edit_feature_popover.js` have **no tests**;
`ui/toast.js` (374 consumers) has **1**. `ui/assembly_context_menu.js` and
`ui/validation_report_panel.js` have none. `sim_folders` and `sidebar_resize` have 2 each — the
only two modules here the doc claimed tests for, and both claims hold.

### Gap, not a rival: sim-folder filtering in the pickers
`ui/file_picker.js:79-80` and `ui/folder_picker.js:74-77` iterate a *different* (folder-scoped)
API response and do **not** filter sim folders. Not a duplicate implementation — the workspace
listers (`file_browser`, `library_panel`) both route through `sim_folders.js` cleanly — but a
user browsing via a picker still sees `*_jobs`.

## Deferred indefinitely (not on roadmap)

- Command palette expansion (user explicitly deferred 2026-05-16)
- OrbitControls damping (user kept current 2026-05-16)
- Drag-marquee in cadnano select tool (audit suggestion, no user decision yet)
- Preset thumbnails in `presets_panel.js` (`ui/presets_panel.js` HELD in [[project_tech_debt]])
- Keyboard nav (arrow keys) in list popups (mate list, instance list, FL, configurations, keyframes)
- Hover tooltip with strand_id/helix_id/bp on raycast hit (medium-risk; conflicts with current cursor management)
- Custom hover cursor change when over selectable instances (same reason as above)

## How to apply

1. Pick one item, open the file(s) it points to. Line refs above are from **2026-07-31**.
2. `main.js` is 8,070 LOC and **rising** — new cohesive logic goes in a module, never the closure.
3. Implement. Each item is independent.
4. After ship: delete the entry here (not in the archive), update `MEMORY.md` if the hook changes.

**Why:** this file is the single record of *what* and *why* — losing it means re-running the
audit and re-asking the user, which they explicitly invested time in to avoid.
**How to apply:** open it whenever picking up UX work; treat each entry as a small spec.
