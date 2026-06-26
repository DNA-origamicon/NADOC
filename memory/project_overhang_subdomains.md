---
name: Overhang sub-domains (Phase 1 of overhang revamp)
description: SubDomain metadata on OverhangSpec; gapless tiling; CRUD endpoints; thermo cache; locked Phase 1 decisions
type: project
originSessionId: 935a01cd-ec4f-47db-bdfb-746860a085fb
---
Phase 1 shipped 2026-05-10. Part of a multi-phase overhang revamp: sub-domains → sequence mgmt → Domain Designer UI tab → per-sub-domain rotation → OverhangBinding ↔ kinematic joints → binding-event animations (unzip / shear / TMSD).

## Data model

`SubDomain` lives on `OverhangSpec.sub_domains`. Tiles the overhang strand gaplessly 5'→3'.

Fields:
- `id` — stable UUID. Deterministic UUID5 from `NADOC_SUBDOMAIN_NS` + `f"{ovhg.id}:whole"` for backfilled whole-overhang sub-domains; random `uuid4()` for split children.
- `name` — auto "a","b","c"... per overhang; user-editable. 5' half keeps original name on split; 3' half gets " (split)" suffix.
- `color` — hex `#RRGGBB` or None (inherit parent strand).
- `start_bp_offset`, `length_bp` — invariant: Σ lengths == backing domain length, contiguous (offset of N+1 == end of N).
- `sequence_override` — None = parent slice; len must == length_bp; bases ACGTN only.
- `rotation_theta_deg`, `rotation_phi_deg` — 2-DOF parent-relative. **Stored but UNUSED by geometry/atomistic until Phase 4.**
- `notes` — free text.
- Cached: `tm_celsius`, `gc_percent`, `hairpin_warning`, `dimer_warning`. Cleared on PATCH-sequence-override / merge / split / tm-settings change. Explicit recompute via endpoint.

## Locked design decisions (user Q&A 2026-05-10)

1. Sub-domains are addressable segments within one continuous strand — no new nicks, no new strand entities.
2. Every overhang always has ≥1 sub-domain. Old `.nadoc` files lazy-migrate via Pydantic `@model_validator(mode='after')` on `OverhangSpec` (idempotent).
3. Gapless tiling — every bp belongs to exactly one sub-domain.
4. Rotation = 2-DOF (theta around parent axis + phi from parent axis), parent-relative chain.
5. Per-sub-domain color override (default None = inherit strand).
6. Sequence ownership = parent canonical + per-sub-domain override. Top-level overhang sequence write returns 409 if any sub-domain has an active override.
7. Resize policy = last sub-domain absorbs Δ length. 422 if shrink pushes last below 1 bp or below its override length.
8. `Design.tm_settings: TmSettings(na_mM=50, conc_nM=250)` (configurable). PATCH-able via `/api/design/tm-settings`; invalidates all sub-domain Tm caches.

## Where sub-domains are constructed

- `backend/core/models.py` — `OverhangSpec.@model_validator(mode='after')` backfills length-1 whole-overhang sub-domain when empty (safety net).
- `backend/core/lattice.py` — `make_overhang_extrude`, `_reconcile_inline_overhangs` (split path), `autodetect_overhangs` build the CORRECT-length whole-overhang sub-domain at creation time. (Validator can't see backing domain length; creation-site construction is primary.)
- `backend/api/crud.py` — `_backfill_sub_domains_if_empty` runs in `load_design` + `import_design`; repairs auto-backfilled length-1 sub-domains by inflating to backing length.

## Endpoints (all `/api/...`)

- `GET /design/overhang/{ovhg_id}/sub-domains` — list in 5'→3' order. Response `{"overhang_id", "sub_domains"}`.
- `POST /design/overhang/{ovhg_id}/sub-domains/split` — body `{sub_domain_id, split_at_offset}`. Strict interior. 5' keeps ID; 3' new `uuid4()`. Distributes override across split point.
- `POST /design/overhang/{ovhg_id}/sub-domains/merge` — body `{sub_domain_a_id, sub_domain_b_id}`. Must be adjacent 5'→3'. Survivor keeps A's ID. Phase-5+ binding-reference check is wired as empty-set stub.
- `PATCH /design/overhang/{ovhg_id}/sub-domains/{sd_id}` — body subset of `{name, color, sequence_override, rotation_theta_deg, rotation_phi_deg, notes}`. Auto-invalidates annotation cache + calls `_resplice_overhang_in_strand` when override changes.
- `POST /design/overhang/{ovhg_id}/sub-domains/{sd_id}/recompute-annotations` — recompute Tm/GC/hairpin/dimer using `design.tm_settings`.
- `PATCH /design/tm-settings` — body `{na_mM?, conc_nM?}`. Invalidates all sub-domain Tm caches.

All mutating endpoints wrap in `mutate_with_feature_log('overhang-bulk')`. Tiling invariant enforced post-op via `_validate_sub_domain_tiling`.

## Thermo

`backend/core/thermo.py` — `tm_nn(seq, na_mM, conc_nM)` (SantaLucia 1998 NN + 16.6·log10[Na+] salt correction); `gc_content(seq)`. Returns None for ambiguous bases. Homopolymer Tm values can be very negative (e.g. "AAAAA" @ 50 mM/250 nM → −57 °C) — mathematically correct (no stable duplex at those concentrations); UI should clamp/format for display.

`has_hairpin`, `has_dimer` promoted from `_has_hairpin`, `_has_dimer` in `overhang_generator.py`; underscore aliases preserved.

## Override-aware generation

`generate_overhang_sequence_with_overrides` in `overhang_generator.py` walks sub-domains, keeps overrides verbatim, fills unlocked slices via the 5-mer Johnson algorithm with overrides added to the diversity corpus ×10. Both `/api/design/overhang/{id}/generate-random` and `/api/design/generate-overhang-sequences` route through this when any sub-domain has an override; legacy path used otherwise.

## Strand write-back

`backend/core/sequences.py::assign_staple_sequences` walks sub-domains 5'→3' for any domain with `overhang_id != None`: uses `sequence_override` if set, else `spec.sequence[start:start+length]`, else `"N" * length`. Byte-identical to legacy for single-whole-overhang-no-override.

## Tests + smoke

- `tests/test_sub_domains.py` — 10 tests covering tiling invariant, deterministic UUID5, override survives regeneration, backward-compat load (via `to_json/from_json` round-trip — no fixture in `tests/fixtures/` has overhangs), 422 on bad tiling, 409 on top-level write with override, endpoint round-trip via TestClient, Tm/GC/hairpin sanity. All pass.
- `scripts/smoke_test_subdomains.py` — runs against live backend with `workspace/hinge.nadoc` (4 overhangs). 12 steps covering all endpoints + save/load round-trip. User-verified passing 2026-05-10.
- `just test` baseline: 1157 passed / 7 failed (all 7 pre-existing flakes: `test_teeth_closing_zig`, 5× `test_geometry_batch_*`, 1× `test_advanced_seamed_*`).

## Phase-2+ carryover (NOT shipped in Phase 1)

- `rotation_theta_deg/phi_deg` consumption by geometry layer → **Phase 4**.
- Frontend UI (split/merge controls, override editor, Tm settings panel, annotations panel) → **Phase 3**.
- Boundary-aware hairpin detection across sub-domain boundaries → Phase 2 collapse / Phase 3 UI warning.
- Single-sub-domain regenerate endpoint (regenerate only sub-domain N, not whole overhang) → Phase 2.
- Multi-sub-domain length-mismatch repair affordance on load → Phase 3 UI.
- `OverhangBinding.sub_domain_a_id`/`sub_domain_b_id` reference fields → **Phase 5**.

## Cross-phase invariants to defend

- 4 overhang lookup maps in `frontend/src/main.js` key on `overhang.id` (unchanged by sub-domains).
- Three-Layer Law: SubDomain lives on TOPOLOGY. Geometry/atomistic layers READ only.
- `_PHASE_*` constants in `lattice.py` LOCKED.
- `feedback_overhang_definition`: overhang remains one contiguous strand region embedded in scaffold; sub-domains are pure metadata.

## Phase 3 — Domain Designer UI (shipped 2026-05-10)

Tabbed integration in the Overhangs Manager popup adds a Domain Designer view alongside the existing Linker Generator UI. Implementation summary:

### Tab integration
- `frontend/index.html` (~L2336): wrapped the original 3-column grid + linker table in `<div id="tab-content-linker-generator">`; added a sibling `<div id="tab-content-domain-designer" hidden>` with the §B grid layout. Tab strip (`#ohc-tab-strip`) sits above the existing grid with `data-tab="linker-generator|domain-designer"` buttons.
- Tab controller lives in `frontend/src/ui/overhangs_manager_popup.js` as an inline closure (duplicates the pattern at `frontend/src/main.js#L8619`). `localStorage['nadoc.overhangsManager.activeTab']` persists the active tab across modal close/re-open. Default = `'linker-generator'`.
- Modal-content width toggles via inline `style.width`: 1000px when Domain Designer is active, 760px otherwise. Target element = `#ohc-modal-content`.

### Pane grid layout
```
grid-template-columns: 200px 1fr 300px
grid-template-rows:    60px 300px 1fr
grid-template-areas:
  "pathview pathview pathview"
  "overhang-list canvas annotations-panel"
  "overhang-list cross-refs cross-refs"
```
Stable IDs (used by Playwright + listeners): `#dd-pathview-canvas`, `#dd-overhang-list`, `#dd-preview-canvas`, `#dd-annotations-panel`, `#dd-cross-refs`.

### Pathview fork — `frontend/src/ui/overhang_pathview.js` (~390 LOC)
- Forked from `frontend/src/cadnano-editor/pathview.js`. Shared constants (`BP_W`, `CELL_H`, `PAIR_Y`, `GUTTER`) and `STAPLE_PALETTE` are re-exported / imported additively from the parent module.
- Single-row strip: sub-domains are drawn left→right by `start_bp_offset`, fill colored per sub-domain (`sd.color ?? strand.color ?? STAPLE_PALETTE[idx % N]`), with sequence letters (if `BP_W ≥ 7`), name label (top-left), Tm glyph (top-right inside cell), and warning ⚠ on hairpin/dimer.
- Override-locked sub-domains carry a dashed gold inset border (`#ffd33d`, `[3,2]`).
- Interaction model — `pointerdown` records `{startX, sdId}` via `_xToBp` hit-test; `pointermove` > 5px → drag mode (amber dashed ghost + tooltip `"Split at bp N → [len5p, len3p]"`); `pointerup` non-drag → `onSelectSubDomain(sdId)`; drag with `0 < rel < length` → `onSplit({sub_domain_id, split_at_offset})`. Hover (no pointer down) → debounced 50ms tooltip with Tm/GC/sequence/notes. Zoom/pan deferred.

### 3D preview — `frontend/src/ui/domain_designer_preview.js` (~330 LOC)
- Self-contained `THREE.Scene` + `PerspectiveCamera` + `WebGLRenderer({antialias:false, alpha:true})` rendered into `#dd-preview-canvas`. Optional `OrbitControls` for re-framing.
- Reuses `helix_renderer.buildHelixObjects(geometry, design, scene, customColors, loopStrandIds, helixAxes)` against a FILTERED design + geometry that allow-lists only the selected overhang's strand_id + sister overhangs' strand_ids + `__lnk__{connId}__a/b` linker strands (and matching helix_ids).
- Linker arcs via own `initOverhangLinkArcs(scene).rebuild(filteredDesign, filteredGeometry)`.
- Camera framing: `Box3` over backbone entry positions → `getBoundingSphere`; `distance = radius / tan(fov/2) * 1.2`.
- Render-on-demand: `_requestFrame()` queues a single `requestAnimationFrame`; no persistent rAF loop.
- Selection highlight: reuses `setBeadScale(1.3) + setEntryColor(0xffd33d)` pattern from `selection_manager.js#L1303`. `_highlightedEntries: Set` tracks boosted entries for cheap reset.
- Dispose sequence (on modal close): `_arcs.dispose()` → `scene.traverse(geom.dispose + material.dispose)` → `renderer.dispose()` → `renderer.forceContextLoss()` → `canvasEl.replaceWith(canvasEl.cloneNode(false))`.

### Annotations panel — `frontend/src/ui/domain_designer_panel.js` (~390 LOC)
- Owns left listing (`<details><summary>` groups per helix), right annotations panel, bottom cross-refs panel. Pathview + 3D preview are injected by the popup — this module imports neither Three.js nor Canvas2D.
- Listing rows update `store.domainDesigner.{selectedOverhangId, selectedSubDomainId}` via `setDomainDesignerSelection` action helper. Helix expansion state in `store.domainDesigner.expandedHelices: Set<helix_id>` via `toggleDomainDesignerHelix`.
- Annotations panel DOM hierarchy (all `class="dd-ann-*"` for stable Playwright selectors): name input (blur/Enter → PATCH), color input + clear button (change → PATCH with `color` or `null`), sequence override textarea (debounced 150ms → PATCH; live `✓` / `× length n/m` indicator), cached Tm/GC display, read-only Twist/Pitch hints (Phase 4 editable), red warning banner (hairpin/dimer), notes textarea (blur → PATCH), Gen button.
- **Gen button is disabled when `sd.hairpin_warning || sd.dimer_warning`** with a tooltip "Resolve the active hairpin/dimer warning first." Backend enforces the same rule with 422.

### Selection rule (locked §D)
Popup-local only. Clicking a sub-domain in the popup updates ONLY `store.domainDesigner.*`. NO writes to `selectedObject` / `multiSelectedOverhangIds`. Main-scene selection does not react to popup state while the modal is open.

### Boundary-hairpin detection (§I)
- `backend/core/overhang_generator.detect_boundary_hairpins(ovhg) -> list[dict]`: for each adjacent sub-domain pair (5'→3' order), concat the trailing 10 bases of the 5' sub-domain with the leading 10 bases of the 3' sub-domain → 20-base junction window → `has_hairpin(window)`. Reports `{boundary_index, sub_domain_a_id, sub_domain_b_id, sequence, position}`.
- `backend/api/crud._apply_boundary_hairpin_warnings(design, overhang_id) -> Design`: unions per-sub-domain inner-hairpin scan with boundary-driven warnings; clears stale flags whose boundary no longer reports. Invoked from `patch_sub_domain` (when sequence_override changed), `recompute_sub_domain_annotations`, `generate_overhang_random_sequence`, and the new `generate_sub_domain_random` endpoint.

### New endpoint — `POST /design/overhang/{ovhg_id}/sub-domains/{sd_id}/generate-random`
Body `{seed?: int}`. Re-rolls one sub-domain. Neighbours treated as locked (resolved sequence becomes a temp override in the generator corpus). Target's old override is dropped before re-roll. 422 if target has active `hairpin_warning` or `dimer_warning` (user must fix first). `random.seed(body.seed)` is applied when supplied for reproducible tests.

### Frontend API client wrappers (§H)
Added to `frontend/src/api/overhang_endpoints.js`:
`listSubDomains(ovhgId)`, `splitSubDomain(ovhgId, body)`, `mergeSubDomains(ovhgId, body)`, `patchSubDomain(ovhgId, sdId, body)`, `recomputeSubDomainAnnotations(ovhgId, sdId)`, `generateSubDomainRandom(ovhgId, sdId, {seed?})`, `patchTmSettings({na_mM?, conc_nM?})`.

### Store additions
`store.domainDesigner = { selectedOverhangId, selectedSubDomainId, expandedHelices: Set, activePane }`. Lives in the `selection` slice so popup re-renders coalesce. Helpers: `setDomainDesignerSelection`, `toggleDomainDesignerHelix`.

### Tests
- `tests/test_subdomain_boundary_hairpin.py` — 5 backend tests (boundary detection / no false positives / single regenerate preserves locked neighbours / regenerate blocked by warning / detection clears on unrelated patch). All pass.
- `frontend/e2e/domain_designer.spec.js` — 10 Playwright cases (tab strip visibility / default tab / pane switching / modal-width swap / localStorage persistence / listing renders / annotations panel populates / cross-refs panel renders / rename triggers PATCH / Gen disabled on hairpin warning / 3D toggle on-off).

## Phase 3 fix-up 2026-05-10

User-reported issues after the initial Phase 3 ship:
1. Selecting an overhang in the listing was inconsistently slow.
2. Drag-to-split, sequence-override edit, hairpin banner, and Gen button were all *unresponsive*.
3. Listing + tooltips exposed full helix UUIDs (`h_XY_3_1`) instead of human labels (`Helix 12`).
4. No way to inspect what was happening from devtools.

### Root cause of "all features unresponsive"

The annotations panel was a **full innerHTML rebuild on every store change**. Because the popup's tab controller subscribed to the global store and called `refresh()` → `_renderAnnotations()` blew away the textarea/Gen-button on every keystroke's debounced PATCH response. The user's textarea focus was lost mid-type and subsequent keys dropped on the floor. The same churn re-built the Gen button (so click handlers attached to the old element fired into the void) and the hairpin banner.

Fix in `frontend/src/ui/domain_designer_panel.js`:
- Track `_renderedOvhgId` / `_renderedSdId` between rebuilds.
- `refresh()` does a **full** rebuild only when the focused sub-domain identity changes; otherwise it calls `_patchAnnotationsInPlace()` which mutates only the read-only fields (`.dd-ann-cached`, `.dd-ann-rot`, `.dd-ann-warnings`, `.dd-ann-generate` disabled state, `.dd-ann-seq-header` length hint). The inputs keep their DOM identity → focus + caret survive PATCH round-trips.
- Sequence-input handler now re-reads the latest sub-domain inside the debounce callback so split-induced `length_bp` changes don't cause false length-mismatch errors.

### 3D preview gating

`#dd-preview-canvas` is now wrapped in `#dd-preview-canvas-wrap` with an overlay `#dd-preview-placeholder` and a `[data-test="dd-show-3d-toggle"]` checkbox below it. Default = **OFF**; the placeholder reads `"3D preview disabled. Click 'Show 3D preview' to enable. May lag with large designs."`

Wiring lives in `frontend/src/ui/overhangs_manager_popup.js`:
- `_ensureDomainDesignerInited()` no longer instantiates the preview; it now passes `preview: null` to the panel.
- `_wirePreviewToggle()` binds the checkbox change handler.
- `_enable3DPreview()` calls `initDomainDesignerPreview(...)` inside a try/catch (so any `buildHelixObjects` failure surfaces in the placeholder instead of bricking the panel); hands the live preview into the panel via `_ddPanel.setPreview(preview)`.
- `_disable3DPreview()` calls `preview.destroy()`, hands `null` back to the panel, restores the placeholder.
- `close()` resets both the toggle checkbox state and the placeholder before destroying the popup so the next open boots in the OFF state.

### Helix label fixes

`helix.id` UUIDs are no longer visible in the Domain Designer. New shared helper `_helixDisplayName(helix)` in `domain_designer_panel.js` returns `helix.label ?? '(' + helix.id.slice(0,8) + '…)' ?? '(unknown)'`. Used in:
- The `<details><summary>` group header in the left listing (`Helix {label} · {count}`).
- The `<summary>` `title` tooltip (shows full UUID on hover for debugging).
- The cross-refs entries' `→ {other-overhang-label} (Helix {label})` text.

### Debug instrumentation pattern

Each Domain Designer module now ships with:
```js
const DEBUG = true
const _debug = (...args) => { if (DEBUG) console.debug('[DD-<tag>]', ...args) }
```
Tags: `[DD-tab]` (popup), `[DD-panel]` (panel), `[DD-pathview]` (pathview), `[DD-preview]` (3D preview). Flip the flag to `false` in any file to silence that channel without touching the others. Log sites cover: tab activation + lazy-init timing; listing rebuild; overhang row clicks; panel refresh per sd; sequence input + PATCH fire + PATCH ok with ms; annotations update; hairpin banner show/hide; Gen click; pathview rebuild/pointerdown/drag start/drag move (throttled 1-in-4)/pointerup/split-fire/select-fire/hover; preview init/filter/buildHelixObjects start+end ms/initOverhangLinkArcs start+end ms/camera fit/highlight/dispose.

### Updated Playwright spec

`frontend/e2e/domain_designer.spec.js` now has **10 cases** (was 9). Timeouts dropped from 60-90s to 30s for all non-3D cases (the 3D pipeline is opt-in now). The dedicated `3D preview toggle enables the WebGL pane when opted in` case keeps the 120-second timeout. New listing assertion verifies the `Helix ` prefix renders without exposing a raw UUID.

## Phase 3 fix-up #2 (2026-05-10)

Four user-reported regressions after fix-up #1:

### Bug 1 — Helix labels still showing UUIDs

The earlier `_helixDisplayName(helix)` fallback chain was
`label ?? "(${id.slice(0,8)}…)"`. Because every helix in `workspace/hinge.nadoc`
has `label === null`, the UI showed `Helix (h_XY_2_…)` everywhere.

Fixed by taking `(helix, design)` and falling back to the helix's INDEX in
`design.helices` (cadnano convention: `Helix 0`, `Helix 1`, …). All three
call sites in `frontend/src/ui/domain_designer_panel.js` updated to pass
`design`.

### Bug 2 — `<details>` groups didn't expand

Root cause: the listing was wired with `<details>.addEventListener('toggle',
…)` that dispatched to the store. The store change fired a synchronous
re-render which blew away the `<details>` element mid-toggle, AND the new
element's imperative `det.open = true` triggered ANOTHER toggle event,
racing the user click. Net effect: clicking summary appeared to do nothing.

Fixed by:
- Listening on `summary.click` and calling `ev.preventDefault()` — the
  native toggle is fully bypassed.
- The click handler calls `toggleDomainDesignerHelix(helixId)`; the store
  update re-renders with `det.open` set declaratively from `expandedHelices`.
- A re-entrancy guard `_suppressNativeToggleRebuild` covers the keyboard-
  Enter case where the native toggle still fires.
- Added `display:block` + `list-style:revert` on `<details>` / `<summary>`
  to defend against any future popup CSS that might `display:contents` the
  container.

### Bug 3 — No visible selection feedback in pathview

The selected sub-domain was indistinguishable from the others; the user
could PATCH a sequence override but couldn't tell which segment it was
landing on.

Fixed in two places:
- Pathview (`frontend/src/ui/overhang_pathview.js`): selected sub-domain
  gets a 2-px solid gold border (`SELECT_CLR = '#ffd33d'`) inset 1 px from
  the cell edge. Visually distinct from the override-locked dashed gold
  border (a segment can carry both at once — the dashed border is inset
  further when the segment is also selected).
- Listing row (`frontend/src/ui/domain_designer_panel.js`): selected
  overhang row gets `background:#1f2937` + `border-left:3px solid #ffd33d`.
  Unselected rows reserve the 3-px slot with a transparent border so the
  layout doesn't shift on selection.

### Bug 4 — Pathview cadnano-rework

Total LOC: **734** (was 409, target 700-900). What's new on top of the
sub-domain coloured strip:

1. **BP ruler band** (top, 26 px tall). Major ticks every 7 bp (honeycomb)
   or 8 bp (square) with bp-number labels centred above; minor ticks every
   1 bp. Reuses `CLR_RULER_BG / CLR_RULER_TEXT / CLR_TICK_MINOR / CLR_TICK_MAJOR`
   from the shared palette.
2. **Helix-label circle in the GUTTER** (left, 40 px wide). Filled disc
   centred at `(GUTTER/2, midRowY)` with white bold label inside.
   Colour follows cadnano convention: FORWARD strand = blue
   (`CLR_LABEL_FWD_FILL`), REVERSE = red (`CLR_LABEL_REV_FILL`). Label text
   = helix `label` or `design.helices.findIndex(...)` index (matches Bug 1
   fix).
3. **2×N grid** — two rows per helix (`PAIR_Y = 12 px` separation, same as
   cadnano). Sub-domains draw on the row matching the overhang's
   FORWARD/REVERSE direction. Both rows render their cell background +
   column separators so the unused row is still visible as an empty track.
4. **5'/3' end caps** at the strand's TRUE termini (not at every sub-domain
   boundary): 5' = filled square (`sqSz = min(BP_W, CELL_H) * 0.80`),
   3' = filled triangle. Strand body BETWEEN caps is a thin coloured line
   (`sThick = CELL_H * 0.20`). Sub-domain boundaries are 1-px vertical
   separators on the body line.
5. **Hover-preview + click-commit split** replaces drag-to-split.
   `pointermove` over a sub-domain shows an amber vertical ghost line at
   the integer bp under the cursor with the canvas-drawn tooltip
   `"Click to split at bp N → [a, b]"`. `pointerup` within
   `CLICK_TOLERANCE_PX + BP_W` of the ghost line commits the split;
   otherwise the click counts as a plain selection. Boundary bps (rel==0
   or rel==length) never show a ghost and never commit a split.

What stayed the same: sub-domain coloured segments, override-locked dashed
gold inset border, warning ⚠ glyph, sub-domain name above the segment, Tm
in the bottom-right of the segment, sequence letters along the segment
when `BP_W >= 7`, debounced hover HTML tooltip with Tm/GC/sequence/notes.

### Updated Playwright spec

`frontend/e2e/domain_designer.spec.js` now has **11 cases** (was 10):
- `overhang listing groups by helix` — strengthened to assert no `(h_…`
  UUID prefix AND no hex-tail leakage AND the `Helix \S+ · \d+` shape, so
  the Bug 1 regression can't slip back in.
- **NEW:** `clicking a <summary> expands / collapses its helix group` —
  reads `details.open`, clicks summary, polls for the boolean flip, clicks
  again, polls for the flip back. Direct regression test for Bug 2.

The drag-to-split UX has no existing test → no test updates needed for the
interaction change. The hover-ghost preview + click-commit split path is a
manual smoke item (recommended: load `workspace/hinge.nadoc`, select any
overhang with `length_bp >= 5`, hover the cursor over the centre of the
strand body, confirm the amber line follows you and the tooltip reads
"Click to split at bp N → […, …]", click, confirm the split commits via a
network tab POST to `/api/design/overhang/{id}/sub-domains/split`).

Predicted pass count: 11/11 once the harness is started. The new spec case
relies on the default-expanded-on-first-render assumption (set is empty at
first paint → all groups open). If the persistence layer ever populates
`expandedHelices` before the first paint, the assertion still holds because
both clicks invert whatever the starting state is.

### What stayed and was NOT touched

- 3D preview gating (opt-in toggle, default OFF).
- Debug instrumentation across all four DD modules.
- Identity-tracked annotations panel (`_renderedOvhgId` / `_renderedSdId`
  short-circuit, in-place patches for read-only fields).
- Backend boundary-hairpin detection + generate-random endpoint.

## Phase 4 — Per-sub-domain rotation (shipped 2026-05-10)

Phase 4 wires the previously dormant ``rotation_theta_deg / rotation_phi_deg``
fields on ``SubDomain`` into the geometry pipeline + adds a 2-DOF rotation
gizmo in the main 3D scene + new HTTP endpoints + feature-log replay.

### Locked design decisions (do not renegotiate)

1. **Gizmo location** — MAIN 3D SCENE ONLY. NOT in the embedded Domain
   Designer 3D preview.
2. **Drag flow** — live PATCH `commit:false` debounced 50 ms during drag;
   final PATCH `commit:true` on pointerup.
3. **2-DOF rings** — gold torus (`#ffd33d`, ``r * 0.6`` hit tolerance) is
   the θ ring (around parent axis); cyan torus (`#39c5cf`) is the φ ring
   (plane containing parent axis + phi_ref).
4. **Log entry shape** — extended ``OverhangRotationLogEntry`` with three
   parallel optional lists: ``sub_domain_ids`` / ``sub_domain_thetas_deg``
   / ``sub_domain_phis_deg``. Legacy whole-overhang entries: trailing
   lists are empty (or ``None`` per slot in a mixed batch). Sub-domain
   entries: ``rotations[i] = [0,0,0,1]`` placeholder.
5. **Selection rule** — gizmo subscribes to
   ``store.domainDesigner.selectedSubDomainId``. NO push to
   ``store.selectedObject`` (Phase 3 rule preserved).
6. **Rotation convention** —
   * sd N=0 parent axis = helix tangent at the junction bp.
   * sd N>0 parent axis = upstream sub-domain's END tangent post all
     upstream rotations.
   * θ ∈ [-180, 180] around parent axis.
   * φ ∈ [0, 180] from parent axis.
   * φ-ref = world-Y projected onto plane ⊥ parent_axis; Z fallback when
     `|parent_axis · Y| > 0.9`.
   * Stored as (theta_deg, phi_deg); quaternions computed at runtime via
     ``_quat_from_theta_phi`` in ``backend/core/deformation.py``.

### Backend chain math

``backend/core/deformation.py`` (~L586) ships ``_quat_from_theta_phi``:

* Pure helper, unit-tested by ``tests/test_subdomain_chain_math.py``
  (9 tests covering identity, θ-only, φ-only, combined, φ=180 axis flip,
  3-element cumulative chain, world-Y fallback, and argument-range
  validation).
* Compose order: θ spin around parent_axis FIRST, then φ tilt around
  ``parent_axis × phi_ref_after_θ``.

``apply_overhang_rotation_if_needed`` (deformation.py ~L800) now applies
two layers per overhang:

1. **Legacy whole-overhang rotation** (preserved behavior; identity case
   short-circuits as before).
2. **Sub-domain chain** — walks sub-domains from JUNCTION outward (5'→3'
   for overhangs at strand 3'; 3'→5' for overhangs at strand 5').
   Each non-identity sub-domain rotates the slice of bp from its
   junction-side end through the free tip of the overhang around the
   running parent-axis frame. Linker complement domains whose bp range
   overlaps the slice ride along.

The companion helix-axes path (deformation.py ~L1700) mirrors the same
two-layer logic so axis sticks + per-domain shafts track sub-domain
rotations.

### New model field semantics

``OverhangRotationLogEntry`` (models.py ~L665) carries the
``@model_validator(mode='after')`` ``_validate_subdomain_lists``:

* Trailing lists must be length 0 or ``len(overhang_ids)``.
* When ANY trailing list is populated, all three are normalised to that
  length (pads with ``None``).
* Per-index slot semantics:
  - ``sub_domain_ids[i] is None`` → legacy whole-overhang slot;
    ``rotations[i]`` is the quaternion; thetas/phis at that index MUST
    be ``None``.
  - ``sub_domain_ids[i]`` is UUID → sub-domain slot; thetas/phis MUST be
    populated; ``rotations[i]`` is the placeholder ``[0,0,0,1]``.
* Out-of-range angles raise ``ValueError`` at construction time.

### Endpoints (all `/api/...`)

* **PATCH** ``/design/overhang/{ovhg_id}/sub-domains/{sd_id}/rotation``
  Body ``{theta_deg, phi_deg, commit}``. Returns
  ``_design_response_with_geometry`` so the frontend re-renders in a
  single store tick. ``commit:false`` mutates state via
  ``set_design_silent`` (no feature_log entry); ``commit:true`` appends
  an ``OverhangRotationLogEntry`` (single sub-domain slot) and coalesces
  with the previous entry if it's the same (ovhg_id, sd_id) within
  2 seconds (window: ``_SUBDOMAIN_COALESCE_WINDOW_S``).
* **PATCH** ``/design/overhang/{ovhg_id}/sub-domains/rotations-batch``
  Body ``{ops: [{sub_domain_id, theta_deg, phi_deg}], commit}``.
  All-or-nothing validation (422 on duplicate sub_domain_id or any
  out-of-range angle). Single log entry on commit.
* **GET** ``/design/overhang/{ovhg_id}/sub-domains/{sd_id}/frame`` →
  ``{pivot:[x,y,z], parent_axis:[x,y,z], phi_ref:[x,y,z]}``.
  Computed post upstream rotations; parent_axis + phi_ref are
  unit-normalised; phi_ref lies in the plane ⊥ parent_axis.

### Undo + seek-replay

``crud.py`` ``_seek_feature_log`` was extended to track both whole-overhang
and sub-domain state separately:

* Walks all ``overhang_rotation`` entries in the active window.
* For each index, branches on ``sub_domain_ids[i] is None``: whole-overhang
  slot updates ``overhang.rotation``; sub-domain slot updates the matching
  ``SubDomain.rotation_theta_deg / rotation_phi_deg``.
* Empty-state seek (-2) zeroes every (overhang.rotation,
  sub_domain.theta/phi) that has any op in the log.

``_rollback_last_feature`` for overhang_rotation entries now walks the
log backward to find the previous WHOLE-overhang or sub-domain slot for
each affected entity, defaulting to identity / (0, 0) when none.

### Frontend modules

* ``frontend/src/scene/sub_domain_gizmo.js`` (~330 LOC) — new module.
  Public API ``initSubDomainGizmo(store, controls, { sceneRef, cameraRef,
  canvasRef, onLiveRotate, onCommitRotate })``. Subscribes to
  ``store.domainDesigner.selectedSubDomainId`` and attaches/detaches
  itself. Live debounce 50 ms; final commit on pointerup; Shift snaps to
  5°. Window-exposed at ``window.__nadocSubDomainGizmo`` for the
  Playwright spec.
* ``frontend/src/api/overhang_endpoints.js`` adds
  ``patchSubDomainRotation``, ``patchSubDomainRotationsBatch``,
  ``getSubDomainFrame`` (raw JSON, no design-sync).
* ``frontend/src/ui/domain_designer_panel.js`` replaces the read-only
  Twist / Pitch row with two `<input type="number">` + `<input
  type="range">` pairs (``.dd-ann-theta-input`` / `.dd-ann-phi-input`
  + `.dd-ann-theta-slider` / `.dd-ann-phi-slider`). Live PATCH on
  `input` (100 ms debounce, commit:false); commit on `change` /
  blur / Enter (commit:true). Identity-preserved DOM check at the
  in-place patch site so a gizmo-driven backend response doesn't
  clobber a focused input.
* ``frontend/src/main.js`` (~L5708) calls ``initSubDomainGizmo`` right
  after ``initClusterGizmo``.
* ``frontend/src/scene/animation_player.js`` (~L107) adds
  ``_subDomainStateAtIndex`` next to ``_clusterStateAtIndex``; the
  keyframe state object carries a ``subDomainState`` field. Per-frame
  slerp is deferred to Phase 6 — seek/restore applies the full state
  at each keyframe boundary.

### Tests (shipped)

* ``tests/test_subdomain_chain_math.py`` — 9 pure-math tests (run
  BEFORE the helper was wired into the geometry pipeline).
* ``tests/test_subdomain_rotation.py`` — 15 tests covering geometry
  effect, chain composition determinism (sequential vs batch),
  linker bridge co-rotation, log entry shape + round-trip, undo restore,
  frame endpoint, φ-range / θ-range clamps, commit:false vs commit:true,
  coalescing 2-s window, legacy entries default to [], and validator
  rejection of malformed entries.
* ``frontend/e2e/sub_domain_rotation.spec.js`` — 8 Playwright scenarios.
  Not auto-run; manager's call.

``just test`` baseline before this session: 1163 passed / 6 failed / 9
errors (test_geometry_batch_* + test_advanced_seamed_* + missing
``workspace/10hb.nadoc`` for test_atomistic_round_trip). After Phase 4:
**1187 passed** / 6 failed / 9 errors — net +24 (chain math 9 +
rotation 15). No regressions; the 6 failures and 9 errors are all
pre-existing and unrelated to Phase 4.

### Phase 5+ carryover

* ``OverhangBinding.sub_domain_a_id / sub_domain_b_id`` reference fields
  (Phase 5).
* Per-frame slerp interpolation for sub-domain (theta, phi) during
  animation playback (Phase 6).
* ``helix_renderer.borrowSubDomainBeads`` helper for live drag preview
  WITHOUT a backend round-trip — currently the live PATCH path provides
  acceptable latency at 50 ms debounce; the borrow/restore API can be
  added later if needed.

### Open issues to verify in-app

1. The default `phi_ref` derivation favours world-Y; on helices oriented
   along world-Y the gizmo will pick world-Z as the in-plane reference.
   No automatic continuity guarantees between adjacent sub-domains; the
   parent-axis-rotated ref keeps composition deterministic but visual
   ring orientation may snap when a φ-only rotation crosses 90° relative
   to world-Y. Acceptable for Phase 4; revisit if user reports.
2. Linker complement co-rotation is bp-range-overlap based. A linker
   that spans multiple sub-domains rotates with whichever sub-domain's
   chain it intersects; the cumulative downstream chain in
   ``apply_overhang_rotation_if_needed`` handles the rest. No design
   mutation occurs (sub-domain virtual split lives in numpy masks only).

## Phase 5 — OverhangBinding + driver-binding kinematic coupling (shipped 2026-05-10)

Phase 5 introduces ``OverhangBinding`` records linking two sub-domains on
different overhangs. Flipping ``bound`` to True freezes the ClusterJoint
connecting the two parent clusters at the angle that brings the duplex
chord to its B-DNA length. Frequently-bound bindings select a *driver*
(latest ``created_at``); the *first claimant* snapshots the joint's
pre-binding angle window so it can be restored after the last bound
binding is released.

### Data model — ``OverhangBinding``

Lives on ``backend/core/models.py`` next to ``OverhangConnection``.

Fields:
- ``id`` — random UUID4.
- ``name`` — auto ``B1``, ``B2``, … (smallest unused).
- ``created_at`` — ``time.time()`` at construction; driver tiebreak (latest
  wins, lex ``id`` as second tiebreak).
- ``sub_domain_a_id`` / ``sub_domain_b_id`` — must differ.
- ``overhang_a_id`` / ``overhang_b_id`` — denormalized parent pointers
  (fast filter without resolving sub-domains).
- ``bound`` — False at creation; True locks ``target_joint_id`` at the
  computed ``locked_angle_deg``.
- ``binding_mode`` — ``'duplex'`` (default) or ``'toehold'``.
- ``target_joint_id`` — Optional. ``None`` = auto-detect (1-DOF only).
- ``locked_angle_deg`` — Set on bound transition; cleared on unbind.
- ``prior_min_angle_deg`` / ``prior_max_angle_deg`` — Set only on the
  FIRST CLAIMANT for the joint (earliest ``created_at`` among bindings
  targeting that joint, bound or not). Cleared when the last claimant
  for the joint unbinds.
- ``allow_n_wildcard`` — True by default; controls how N bases are
  treated in the WC complementarity check.

Cross-model ``@model_validator(mode='after')`` on ``Design`` enforces (when
``overhang_bindings`` is non-empty — short-circuit otherwise for backward
compat):
- sub-domains resolve to existing sub-domains on existing overhangs;
- ``sd_a.length_bp == sd_b.length_bp``;
- antiparallel Watson-Crick complementarity via
  ``backend.core.sequences.is_watson_crick_complement`` (skipped when
  either sequence isn't resolvable yet — lets users seed bindings
  before sequences are assigned);
- mutual exclusion: the unordered pair ``{sd_a, sd_b}`` may appear at most
  once across ``overhang_connections`` linker attach endpoints AND
  ``overhang_bindings``;
- ``overhang_a_id`` / ``overhang_b_id`` match the parents of the
  referenced sub-domains;
- ``target_joint_id``, when set, resolves to an existing cluster joint.

Per-instance validator additionally rejects: ``sd_a == sd_b``;
``bound=True`` without ``target_joint_id`` or ``locked_angle_deg``.

### Locked-angle solver — ``backend/core/binding_relax.py``

Public ``compute_locked_angle(design, binding, geometry) -> float``
(degrees). Pipeline:
1. Resolve each binding's owning cluster via parent overhang → helix →
   cluster (``_overhang_owning_cluster_id`` reused from
   ``linker_relax.py``). 422 when both ends sit on the same cluster.
2. Find candidate joints between the two clusters; if
   ``target_joint_id`` is set, restrict to that one. 422 when
   ambiguous (>1 with no explicit target) or empty.
3. 1-DOF only — multiple joints between the two clusters raises 422
   ``multi-DOF binding relax not yet supported``.
4. Pivot anchors = bp at the junction-side end of each sub-domain (the
   bp on the parent overhang's strand at offset ``start_bp_offset``).
5. Target chord = ``(sd_a.length_bp - 1) * BDNA_RISE_PER_BP``.
6. Reuses ``linker_relax._optimize_angle`` clipped to the joint's
   ``[min_angle_deg, max_angle_deg]`` window; loss = chord magnitude
   residual squared. Returns θ in degrees.

### Endpoints (all ``/api/...``)

- ``GET /design/overhang-bindings`` — list ``{"overhang_bindings": [...]}``.
- ``POST /design/overhang-bindings`` — 201; body
  ``{sub_domain_a_id, sub_domain_b_id, binding_mode?, target_joint_id?, allow_n_wildcard?}``.
  404 on missing sub-domain; 422 on length mismatch / non-WC / unresolvable
  sequence; 409 on mutex collision; auto-names ``B{n}``; ``bound=False``.
- ``PATCH /design/overhang-bindings/{id}`` — body subset of
  ``{name, bound, binding_mode, target_joint_id, allow_n_wildcard}``.
  Transitions:
  * ``False → True``: resolve target_joint_id (explicit or auto-detect via
    the relax solver's 1-DOF restriction), compute ``locked_angle_deg``,
    snapshot the joint's current window onto the first claimant (only if
    no snapshot exists yet — idempotent re-toggle safe), apply driver to
    joint.
  * ``True → False``: clear ``bound``, clear ``locked_angle_deg``, re-select
    driver; if no driver remains restore the joint window from the first
    claimant's snapshot AND clear that snapshot.
  * ``target_joint_id`` change while bound: release old joint, claim new.
  Returns ``_design_response_with_geometry``.
- ``DELETE /design/overhang-bindings/{id}`` — if the binding being deleted
  is the first claimant AND there are other claimants, migrate the
  ``prior_min/max`` snapshot onto the next-earliest claimant before
  removing. After removal the driver is re-applied; if no claimants
  remain at all, the joint window is restored from the deleted binding's
  carried snapshot (fallback path) so the joint un-locks.

### Driver helpers (private in ``crud.py``)

- ``_select_driver_for_joint(design, joint_id)`` — latest ``created_at``
  among bound bindings targeting this joint; lex id tiebreak.
- ``_first_claimant_for_joint(design, joint_id)`` — earliest
  ``created_at`` among bindings (bound OR unbound) targeting this joint.
- ``_apply_driver_to_joint(design, joint_id)`` — when a driver exists,
  set ``joint.min_angle_deg = max_angle_deg = driver.locked_angle_deg``;
  when absent, restore from the first claimant's snapshot. Pure
  function — caller commits inside ``mutate_with_feature_log``.

All three helpers and the snapshot/restore steps execute inside the same
``mutate_with_feature_log`` callback as the binding mutation so the
overhang_bindings list and the cluster_joints list stay atomically
consistent.

### Frontend wiring

- ``frontend/src/api/overhang_endpoints.js`` adds
  ``listOverhangBindings``, ``createOverhangBinding``,
  ``patchOverhangBinding``, ``deleteOverhangBinding``. All but the list
  endpoint funnel through ``_syncFromDesignResponse``.
- ``frontend/src/ui/domain_designer_panel.js`` ``_renderCrossRefs`` now
  emits a "Bindings (n)" subsection below the existing linker
  cross-refs. Rows show name pill, mode badge (duplex green ``#3fb950``
  / toehold amber ``#bf8700``), sd_a ↔ sd_b labels, partner overhang
  label, joint name + locked angle, Bound checkbox, Delete button.
  Row click (excluding form controls) calls
  ``setDomainDesignerSelection`` to navigate to the partner. The
  "+ Create binding" button inlines a small form with partner select
  (filtered to matching ``length_bp`` and different parent overhang),
  mode radio (duplex default), joint select (Auto-detect default).
  ``[DD-bind]`` debug channel added alongside ``[DD-tab]`` /
  ``[DD-panel]`` / ``[DD-pathview]`` / ``[DD-preview]``.
- ``frontend/src/ui/overhangs_manager_popup.js`` extends ``ddApi`` with
  the three new wrappers.
- ``frontend/src/scene/cluster_gizmo.js`` ``_showRing`` now treats
  ``joint.min_angle_deg === joint.max_angle_deg`` as locked: ring
  material switches to ``MeshBasicMaterial({color: 0x808080,
  opacity: 0.4, transparent: true})`` and the ring's pointerdown handler
  early-returns without engaging the drag handler.

### Sub-domain split / merge propagation

Both endpoints now check ``design.overhang_bindings`` for references and
reject with 409 ``{"error": "sub_domain_referenced_by_binding",
"binding_ids": [...]}``. This replaces the empty-set stub the Phase 1
endpoints had wired.

### Tests

- ``tests/test_overhang_bindings.py`` — 15 tests covering WC helper
  edge cases, POST happy path + length / WC / mutex rejections, PATCH
  bound-True snapshots + locks, bound-False restores, driver semantics,
  multi-DOF rejection, split rejection with referencing binding_ids,
  DELETE-restores-window when last bound claimant goes away, and
  ``Design.model_dump_json`` round-trip.
- ``frontend/e2e/overhang_bindings.spec.js`` — 6 Playwright cases
  (Bindings header renders, Create button toggles form, form exposes
  partner / mode / joint controls, list endpoint reachable via client
  wrappers, empty-state message renders, all four client wrappers
  exposed as functions). DOM-only — no WebGL / gizmo state assertions.

### Deviation from plan

- Plan asserted ``is_watson_crick_complement("ACGT", "ACGT") is False``,
  but ``ACGT`` is its own antiparallel reverse complement (canonical
  4-mer palindrome). Test was rewritten to use ``AAAA``/``TTTT`` (True)
  and ``AAAA``/``AAAA`` (False) so the basic-rejection contract is
  still covered without contradicting the antiparallel rule.

### Phase 6+ carryover

- Frame-by-frame slerp of the locked angle during animation playback
  (binding events as keyframes — unzip / shear / TMSD).
- Toehold-mediated strand displacement: the ``binding_mode='toehold'``
  pathway currently differs from duplex only in metadata + UI badge
  colour; the geometric / kinematic constraint is identical. A future
  pass should add the toehold's ssDNA branch as an extra strand and
  drive the displacement via a separate joint.
- Multi-DOF binding relax (currently 422). Requires the same Powell
  multi-axis optimization that ``relax_linker`` already supports for
  linkers; the loss term will need adjusting because both pivot
  anchors can rotate independently.

---

## Session checkpoint — 2026-05-10 (pause)

Manager-overseen multi-phase build paused at session time limit. Five
phases shipped + verified to varying depths; Phase 6 not started.

### Shipped + verified

| Phase | What | Verification |
|---|---|---|
| 1 | Sub-domain data model + 6 CRUD endpoints + thermo cache + override-aware generation | `just test` 1163 pass + 12/12 smoke (`scripts/smoke_test_subdomains.py` against `workspace/hinge.nadoc`) ✅ |
| 2 | Folded into Phase 3 (boundary hairpin + per-sub-domain regenerate endpoint) | covered by Phase 3 backend tests |
| 3 | Domain Designer tab (tab integration, helix-grouped listing, forked cadnano-style pathview, gated 3D preview, annotations panel, boundary-hairpin detection, single-sd regenerate endpoint) | `just test` 1162 + 2 fix-ups; user-verified app-side after fix-up #2 |
| 4 | Per-sub-domain 2-DOF rotation (chain composition, linker bridge propagation, `OverhangRotationLogEntry` extension, 3 new endpoints, `sub_domain_gizmo.js`, editable θ/φ inputs) | `just test` 1186 (+23) + user smoke "passes well enough" ✅ |
| 5 | `OverhangBinding` (cross-model validator, mutex with linkers, `is_watson_crick_complement`, `binding_relax.compute_locked_angle`, driver-binding semantics, 4 CRUD endpoints, gizmo locked-state visual, Domain Designer Bindings UI, split/merge propagation) | `just test` 1201 (+15) + user smoke verified through **step 5** (create binding, toggle bound, see joint visual lock) |

### Phase 5 smoke — completed through step 5 only

User confirmed steps 1-5 work: tab open, Bindings (0) section, +Create binding form, submit, [✓ Bound] toggle, cluster gizmo ring goes grey on lock. **Steps 6-9 not exercised** in this session — secondary issues (unspecified by user) interfered. Items to retest next session:
- Step 6: multi-binding driver-swap (two bindings share a joint; bind both → latest wins; untoggle → first takes over).
- Step 7: delete bound binding → joint range restored, ring returns to gold.
- Step 8: split a sub-domain referenced by a binding → expect 409 with `binding_ids`.
- Step 9: try to create a binding where a linker already references the same sub-domain pair → expect 409.

### Carryover list (open items across all phases)

**Phase 3:**
- Pathview hover tooltip DOM leak (created on hover, cleared only via `destroy()`).
- Modal width toggle (760 ↔ 1000 px) is mildly janky on tab switch; consider always-1000px.
- Cross-refs `OverhangBinding` UI now active (Phase 5 work landed in this surface — no longer carryover).

**Phase 4:**
- `helix_renderer.borrowSubDomainBeads()` live-preview helper not implemented; live drag relies on 50 ms debounced PATCH round-trips. Add if user reports drag lag.
- `_subDomainStateAtIndex` snapshot is wired into `_kfState` but seek-restore call site doesn't consume it yet. Phase 6 work.
- φ-ref discontinuity when parent axis crosses near world-Y (acceptable for v1).

**Phase 5:**
- Multi-DOF locked-angle relax (current solver 422s on multi-DOF cluster pairs; needs Powell multi-axis path from `linker_relax.py`).
- Toehold mode currently differs from duplex only in metadata + badge color. Geometric constraint is identical. A real toehold model would add the ssDNA branch as an extra strand and drive displacement via a separate joint.
- `_sub_domain_at_attach` heuristic in mutex check is coarse (`root → first sd, free_end → last sd`); could be refined using OH 5p/3p polarity.

**Phase 6 (not started):**
- `BindingEventLogEntry` (or similar) feature_log subtype: `{binding_id, t_start, t_end, event_type: 'unzip'|'shear'|'tmsd', invading_strand_id?: str}`.
- Animation player extension: branch per `event_type` for per-bp fade timing (unzip = sequential along duplex; shear = simultaneous; TMSD = invading strand entry).
- New `frontend/src/scene/binding_overlay.js` for the visual "hybridization bond" tube between bound sub-domain anchors (decoupled from the animation primitive; useful even without animation).
- Export determinism check (existing video export reads from `seekTo(t)` — new primitive must be deterministically computable from t).

### Files touched across all five phases (impact map)

**Backend new:**
- `backend/core/thermo.py` — SantaLucia 1998 Tm + GC%.
- `backend/core/binding_relax.py` — Phase 5 locked-angle solver.

**Backend modified:**
- `backend/core/models.py` — `SubDomain`, `TmSettings`, `OverhangBinding`, `Design.overhang_bindings`, `OverhangRotationLogEntry` schema extension, cross-model `Design` validator.
- `backend/core/lattice.py` — sub-domain construction at 3 creation sites.
- `backend/core/overhang_generator.py` — `generate_overhang_sequence_with_overrides`, `detect_boundary_hairpins`, promoted hairpin/dimer helpers.
- `backend/core/sequences.py` — `assign_staple_sequences` walks sub-domains; `is_watson_crick_complement`.
- `backend/core/deformation.py` — Phase 4 chain composition (`_quat_from_theta_phi`, sub-domain chain walk, linker bridge propagation).
- `backend/api/crud.py` — total of **11 new endpoints** across Phases 1-5 (5 sub-domain CRUD + tm-settings + sub-domain regenerate + 3 rotation + 4 bindings).

**Frontend new:**
- `frontend/src/ui/overhang_pathview.js` — Phase 3, forked cadnano-style pathview.
- `frontend/src/ui/domain_designer_preview.js` — Phase 3, gated 3D mini-scene.
- `frontend/src/ui/domain_designer_panel.js` — Phase 3, panel + listing + annotations + cross-refs.
- `frontend/src/scene/sub_domain_gizmo.js` — Phase 4, 2-DOF rotation gizmo.

**Frontend modified:**
- `frontend/index.html` — tab strip + Domain Designer pane.
- `frontend/src/ui/overhangs_manager_popup.js` — tab controller + lazy init + 3D-toggle wiring.
- `frontend/src/cadnano-editor/pathview.js` — constant re-export block (additive).
- `frontend/src/api/overhang_endpoints.js` — 13 new client wrappers.
- `frontend/src/state/store.js` — `domainDesigner` sub-state + action helpers.
- `frontend/src/scene/cluster_gizmo.js` — Phase 5 locked-state visual (grey ring + drag rejection on min==max).
- `frontend/src/scene/animation_player.js` — `_subDomainStateAtIndex` snapshot (seek-restore consumption deferred).
- `frontend/src/main.js` — `initSubDomainGizmo` wiring + `store.domainDesigner` default.

**Tests new:**
- `tests/test_sub_domains.py` — 10 tests (Phase 1).
- `tests/test_subdomain_boundary_hairpin.py` — 5 tests (Phase 3).
- `tests/test_subdomain_chain_math.py` — 9 tests (Phase 4).
- `tests/test_subdomain_rotation.py` — 15 tests (Phase 4).
- `tests/test_overhang_bindings.py` — 15 tests (Phase 5).
- `frontend/e2e/domain_designer.spec.js` — 11 Playwright (Phase 3).
- `frontend/e2e/sub_domain_rotation.spec.js` — 8 Playwright (Phase 4, not run).
- `frontend/e2e/overhang_bindings.spec.js` — 6 Playwright (Phase 5, not run).

**Scripts new:**
- `scripts/smoke_test_subdomains.py` — Phase 1 manual smoke harness (12 steps, user-verified).

**Total**: +**54 backend tests** (1147 → 1201) over the full sequence. Frontend Playwright spec'd but not run end-to-end since fix-up #2.

### Resume guide for next session

1. **First**: re-read this section + recent commits in `project_overhang_subdomains.md`.
2. **Investigate** the "various other issues interfered" mentioned by the user at Phase 5 smoke step 5 — likely candidates: (a) Phase 3 modal width jank, (b) Phase 4 gizmo attachment edge cases, (c) Phase 5 W-C validator over-strictness when sequence is partially N-filled. Open devtools console: `[DD-tab]`, `[DD-panel]`, `[DD-pathview]`, `[DD-bind]`, `[DD-preview]` channels are live.
3. **Resume Phase 5 smoke** from step 6 onward.
4. **Then Phase 6**: dispatch audits (animation player extension surface + per-bp fade extension + new feature_log subtype registration) → planner → implementer.

No commits made — all work is in the dirty working tree. Manager will commit only on user request.


## Phase 7 — Domain Designer pathview rework + ss linker single-strand topology (2026-05-11)

User-driven multi-session iteration on the Domain Designer pathview. Major changes:

### Pathview rewrite (`frontend/src/ui/overhang_pathview.js`)

Cadnano-faithful single-canvas pathview rendered into `#dd-pathview-canvas` (forked from `frontend/src/cadnano-editor/pathview.js`). Layout pillars:

- **Light cadnano background** (`CLR_BG = #f0f2f5`); ruler, gutter, cell tints all match the main editor.
- **Free pan/zoom**: right- or middle-drag = pan; wheel = zoom centred on cursor. Reset View button top-left.
- **Grid extends to ±50 bp** beyond the strand body; the empty extension cells provide context.
- **Two reserved DNA tracks per grid** — sequence letters never spill into the opposite row.
- **Cadnano-style root end**: the overhang's root end has NO cap; the colored body line ends at the cell-centre of the terminal bp where the crossover arc takes over.
- **Free-end cap drag → resize**: hover the free-end cap, cursor switches to `ew-resize`; drag → orange ghost shows new length; release → POST to backend.

### Multi-grid layout (active when a linker exists)

Three stacked 2×N grids:
- **Top — partner overhang grid**: full sub-domain bars + UP-arc going to a distant point (signals "continues into other bundle").
- **Middle — linker bridge grid**: ds = strand A (blue) on FWD row + strand B (orange) on REV row. ss = single strand `__s` (teal) on the centre row.
- **Bottom — selected overhang grid**: legacy single-grid render, with DOWN-arc.

Each grid gets its own helix-label disc in the gutter:
- Partner: helix label, blue/red per FWD/REV.
- Linker: connection name (e.g., "L1"), neutral grey ring (not a strand-type label).
- Selected: legacy disc.

`_layout = _computeLayout()` runs once per draw and stashes `{isMulti, linker, partner, linkerStrands, selectedYShift}`. `_rowYsWorld(kind)` returns row Ys per grid kind. `resetView()` clamps zoom by both horizontal-fit and vertical-fit (so all three grids fit).

### ss linker — single-strand topology (THIS PHASE'S BIG BACKEND CHANGE)

**Old**: ss linker = TWO complement-only strands (`__a`, `__b`), no virtual bridge helix; the bridge was "represented by frontend arc only."

**New**: ss linker = ONE strand `__lnk__{conn.id}__s` with domains `[complementA, bridge, complementB]`. The strand traverses 5'→3' from overhang A's binding domain, through the ssDNA bridge on the linker helix, into overhang B's binding domain. Bridge polarity: FORWARD bp 0 → L-1 so `complementA.3' → bridge.5'` and `bridge.3' → complementB.5'` chain correctly.

`backend/core/lattice.py:generate_linker_topology` now creates the virtual `__lnk__` helix for BOTH ds and ss, and dispatches to either `_build_ds_linker_strand` (per-side, legacy) or `_build_ss_linker_strand` (single).

### Linker bridge length-resize persists complement bp ranges

`backend/api/crud.py:patch_overhang_connection`: on length change, snapshot every linker strand's complement (non-bridge) domain bp ranges + direction, run remove+regenerate, then restore the snapshot onto the regenerated strand by `helix_id` match. Handles both ds (1 complement per strand) and ss (2 complements on `__s`).

### Bindings + crossovers in pathview

For ds: each strand has ONE binding domain on ONE overhang grid; one crossover arc per strand connecting the bridge's strand-position-determined end (5' or 3') to the binding's junction end.

For ss: the SINGLE `__s` strand has TWO binding domains (one on each overhang grid); two crossover arcs (bridge's 5' ↔ complementA's 3' junction, bridge's 3' ↔ complementB's 5' junction).

Cap convention: caps drawn ONLY at strand TIPS — `domain.findIndex(...) === 0 → 5' cap`; `=== domains.length - 1 → 3' cap`; middle → no caps. Body lines terminate at cell-centres on crossover-junction ends.

### Editing model — perspective lock + multi-grid edits

User-locked semantics:
- `domainDesigner.selectedOverhangId` = LISTING-selected overhang. Perspective anchor for the multi-grid stack. **Only changed by clicks in the listing.**
- `domainDesigner.selectedSubDomainId` = active sub-domain (can belong to either the listing-selected OR the partner overhang). Pathview gold halo, listing sub-domain row highlight, and annotations panel all key off this independently.
- `_focusedSubDomain()` walks ALL overhangs to find the active sd.
- `_focusedOvhg()` returns the OWNER of the active sd (could be partner) so PATCH calls hit the right overhang_id.

Editable surfaces in the pathview:
- Selected overhang: select sub-domain (left-click), split (right-click), free-end resize (drag cap).
- Partner overhang: same as selected. Clicks update only `selectedSubDomainId`, leaving the listing-perspective anchor untouched.
- Linker bridge: drag either strand-tip OR cell-centre crossover end → `patchOverhangConnection({length_value})`.
- Linker binding domain (3' triangle on each overhang grid): drag → `resizeStrandEnds([{strand_id, helix_id, end:'3p', delta_bp}])` against the linker strand directly.

### Other touchpoints

- 3D preview removed entirely (`frontend/src/ui/domain_designer_preview.js` deleted; toggle + canvas + placeholder stripped from `index.html` and the popup; `_preview` field removed from `domain_designer_panel.js`). Freed grid slot now hosts Cross-References & Bindings in the middle column.
- Rotation tools removed: θ/φ sliders in Annotations panel deleted; `initSubDomainGizmo` call in `main.js` gutted (left a `void initSubDomainGizmo` so the import isn't tree-shaken). Rotation data on `SubDomain` is preserved if loaded; just no UI.
- New backend endpoint `POST /design/overhang/{id}/resize-free-end` ([crud.py:7124-7244](backend/api/crud.py#L7124)): wraps `resize_strand_ends` and re-tiles sub-domains so the LAST one absorbs Δ length (Phase 1 locked policy). Robust to "orphan" overhangs (id not on any strand domain) via three-tier fallback (strict → tagged-on-helix → first-on-helix).
- Pathview's `_overhangDomain` and `_strandEnds` use the same orphan-fallback so polarity stays locked across resizes.
- Main 3D scene rebuilds suppressed while DD is open: new `domainDesigner.modalActive` flag + `setDomainDesignerModalActive(active)` setter; `design_renderer.js` stashes pending rebuilds and flushes once on close.

### Tests

- `tests/test_sub_domains.py` — added `test_resize_free_end_grows_and_shrinks` covering the new resize endpoint with sequence_override length tracking. **11/11 pass**.
- `tests/test_overhang_connections.py` — added `test_patch_length_preserves_resized_complement_domains` (binding persistence across bridge resize) + `test_ss_linker_bridge_polarity_chains_5p_to_3p`. Updated three pre-existing ss tests for the new single-strand convention. **62/62 pass** (was 60).
- Full backend suite: 1203 passed (1202 baseline + 2 new tests; one of the 2 new is `test_patch_length_preserves_resized_complement_domains` and the other is the polarity test). 6 pre-existing failures + 9 errors unchanged.
- DD e2e suite: 9/11 pass (same 2 pre-existing failures: summary-toggle flake + Gen-test dynamic-import store mismatch).

### Files touched in Phase 7

**Backend modified**: `backend/api/crud.py` (overhang resize endpoint + linker complement persistence), `backend/core/lattice.py` (ss single-strand topology + always-create virtual helix).
**Frontend modified**: `frontend/src/ui/overhangs_manager_popup.js` (callback wiring), `frontend/src/ui/domain_designer_panel.js` (rotation removal + `_focusedOvhg` walk), `frontend/src/state/store.js` (`modalActive` flag + setter), `frontend/src/scene/design_renderer.js` (deferred-rebuild guard), `frontend/src/main.js` (gizmo gutted), `frontend/src/api/overhang_endpoints.js` (`resizeOverhangFreeEnd` wrapper), `frontend/index.html` (multi-grid pane structure + canvas height bumps).
**Frontend new**: `frontend/src/ui/overhang_pathview.js` was already untracked; this phase brought it to ~2k LOC.
**Tests modified**: `tests/test_overhang_connections.py` (4 ss tests refactored + 2 new), `tests/test_sub_domains.py` (1 new resize test).

### Known follow-ups

- Linker bridge nucleotides for ss don't flow through `/api/design/geometry` (the test asserts complement halves only); 3D rendering of the ssDNA segment is deferred.
- Backend gets stuck (Recv-Q saturated) under repeated curl + Playwright bursts; user restarts `just dev` periodically.
- Complement-on-orphan-overhang resize uses three-tier helix-id fallback — investigate if the orphan condition can be cleaned up at design-load time.
- Linker resize while a binding is selected may need a cache-invalidation hook on the cluster_joints reference; not exercised yet.

