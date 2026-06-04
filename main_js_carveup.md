# main.js carve-up map — stateful-subsystem extraction backlog

**Purpose.** main.js is one ~15.6k-line `async function main()` closure. The pure-helper well is
drained (see `main_js_extraction_log.md`); the remaining mass is *stateful subsystems* — panels,
dialogs, menus, and event-handler clusters. This file is the **prioritized backlog** for extracting
them. Each session claims ONE region, factory-extracts it, and checks it off here.

**How to use this map (per session — ideally a FRESH session to keep token cost low):**
1. Read this file + `main_js_extraction_log.md` (conventions + difficulties ledger) +
   `.claude/rules/main-init.md` (the extraction loop + gesture-validation harness).
2. Pick the topmost unchecked region in the highest-priority tier (or one the user names).
3. **Want-it-first gate (cheap, do it):** before investing in a clean factory + tests, confirm the
   feature is still wanted/used. We once extracted `loop_popup` with 10 tests, then deleted it an
   hour later because the feature was unwanted. A 30-second check saves that.
4. Extract to a factory `initX({deps})→{api}` (mirror `initEndExtrudeArrows` / `initMeasurementTool`).
   Pure cores (math, data shaping) come out as separately-tested pure functions.
5. **Gate:** `just test-frontend` green (≥1 test per pure fn; factory tests via jsdom + mock store).
   Interactive (canvas-gesture) regions: add/extend a gesture e2e using `e2e/helpers/scene_harness.js`.
   ALL stateful regions: one app exercise + `just smoke` before commit.
6. One region per commit. Update this map (check the box, note the commit) + add a metrics row to the
   log. If a region turns out coupled/unsafe, log it in the difficulties ledger and move on.

**Line numbers drift** as the file shrinks — they are a 2026-06-03 snapshot at main.js = 15,614 LOC.
**Anchor by the `// ──` banner text** (stable) when locating a region, not the line number.

**Dependency surface** below is a rough pre-read estimate — VERIFY by reading the region when you
claim it. The map's job is sequencing + module naming + risk tiering, not exact deps.

**Don't:** parallelize edits to main.js (worktrees collide on the shared import block + closure —
serial is correct for one god-file). Don't touch `_PHASE_*`, backend, or rendering invariants.

---

## Tier 1 — high-value, well-bounded panels/dialogs (do first)

Self-contained feature blocks that map cleanly to a factory; lowest coupling, highest LOC payoff.

- [ ] **Help / Hotkeys modal** — banner `// ── Help / Hotkeys modal` (~13793–14139, ~346 ln) →
  `ui/help_modal.js`. Deps: DOM (static content) + a hotkey list. Risk: LOW (mostly static markup).
  No gesture e2e; smoke only.
  ⚠️ **LINE-SPAN MISLEADING (verified 2026-06-03):** the actual help-modal wiring is only ~6 lines
  (13793–13799). The 13793–14139 span is a grab-bag — Help-menu *debug* toggles (OH-roots/domain-ends/
  linker-debug/FJC-sim) + the whole **Create Seam** handler. The modal alone isn't worth a factory
  (the markup lives in index.html; only `.classList` toggles are here). De-prioritize, OR rescope to
  "Help-menu wiring cluster" and bundle the debug toggles. The Create-Seam handler is a separate
  region (pairs with `scaffold_coverage.js`) — don't fold it in.
- [x] **Strand length histogram** — banner `// ── Strand length histogram` (~12614–12813, ~200 ln) →
  `ui/strand_length_histogram.js`. Deps: store (currentGeometry/Design), DOM canvas, api (delete-by-bin
  context menu). Has a pure core (bin counts) — extract + test that. Risk: LOW-MED.
  **DONE** (extraction #20, commit pending) — factory `initStrandLengthHistogram` + pure
  `computeStrandLengthBins`; −192 ln off closure; 13 vitest (6 pure + 7 jsdom factory); smoke 21/21 +
  real-app expand exercise. 2D-canvas hit-testing covered by jsdom click test (no scene_harness needed).
- [ ] **Overhang sequences panel** — banner `// ── Overhang sequences panel` (~2488–2715, ~227 ln) →
  `ui/overhang_sequences_panel.js`. Deps: store, api, DOM, selectionManager. Risk: MED.
- [ ] **Strand groups panel** — banner `// ── Strand groups panel` (~2715–2913, ~198 ln) →
  `ui/strand_groups_panel.js`. Deps: store (strandGroups), DOM rebuild + subscribe. Risk: MED.
- [ ] **Library panel (welcome screen)** — banner `// ── Library panel (welcome screen)`
  (~9291–9527, ~236 ln) → `ui/library_panel.js`. Deps: api (file list), DOM, import callbacks. Risk: MED.
- [ ] **Fluorescence + FRET checker** — banner `// ── Fluorescence + FRET Checker` (~13712–13793,
  ~80 ln) → `ui/fret_panel.js` (pairs with existing `scene/fret_util.js`). Deps: store, DOM, fret_util.
  Risk: LOW-MED.

## Tier 2 — import / export menus (mechanical, repetitive)

Many sibling handlers that each wire a menu item → api call → download/import. Extract as one factory
per direction with a handler table.

- [ ] **Export menu** — banners `// ── Export Sequences (CSV)` … `// ── Export GROMACS …`
  (~13046–13266, ~220 ln) → `ui/export_menu.js`. Deps: api, design state, file-download helper. Each
  export is independent → easy to test the wiring table. Risk: LOW-MED (no canvas).
- [ ] **Import menu + callbacks** — banners `// ── Import helpers` … `// ── Import PDB` + library import
  callbacks (~12813–13046, ~233 ln) → `ui/import_menu.js`. Deps: api, lattice autodetect, DOM dialogs.
  Risk: MED (autodetection branch).

## Tier 3 — assembly interaction (big, higher coupling — gesture-e2e REQUIRED)

The largest single blocks and the most coupling into assembly state. Each needs a gesture e2e
(scene_harness) + smoke. Split the giant ones; don't extract 900 lines in one commit.

- [ ] **Assembly canvas pointer handler** — banner `// ── Assembly canvas pointer handler` +
  `// ── PartGroup click-through` (~11298–11815, ~517 ln) → `scene/assembly_pointer.js`. Deps:
  assemblyRenderer, camera, store, group helpers, lasso. Contains `_onAssemblyClick`. GESTURE E2E.
  Risk: HIGH. **Split:** (a) joint-ring pick, (b) instance select, (c) group click-through.
- [ ] **Polymerize / kinematics / joint-pick cluster** — banners `// ── Polymerize along a belt` …
  `// ── Joint arrow pick handler` (~8187–9171, ~984 ln) → MULTIPLE modules
  (`scene/kinematics_ticker.js` already exists — move ticker wiring there;
  `scene/joint_pick.js`; polymerize → its own). Deps: assemblyRenderer, assemblyJointRenderer, api,
  store. Risk: HIGH. **Must split into ≥3 commits.**
- [ ] **Rigid-body group gizmo + PartGroup gizmo** — banners `// ── Rigid-body group gizmo attachment`
  + `// ── PartGroup gizmo` (~10406–10836, ~430 ln) → `scene/group_gizmo.js`. Deps: TransformControls,
  store, assemblyRenderer, group helpers. GESTURE E2E. Risk: HIGH.
- [ ] **Multi-select visual feedback (purple union BoxHelper)** — banner `// ── Multi-select visual
  feedback` (~11106–11298, ~192 ln) → `scene/multi_select_box.js`. Deps: scene, store, assemblyRenderer
  (instance centers). Has a pure core (union bbox — see existing `selection_bbox.js`). Risk: MED.
- [ ] **Coalesced assembly part-refresh** — banner `// ── Coalesced assembly part-refresh`
  (~9814–10014, ~200 ln) → `scene/assembly_refresh.js`. Deps: assemblyRenderer, store, setTimeout
  coalescing state. Risk: MED-HIGH (timing/coalescing — assert the debounce, not just the output).

## Tier 4 — menus / toggles / shortcuts (many small handlers)

- [ ] **Keyboard shortcuts** — banner `// ── Keyboard shortcuts` (~6608–7136, ~528 ln) →
  `ui/keyboard_shortcuts.js` as `initKeyboardShortcuts({commandMap, ...})`. ONE giant keydown handler;
  factor to a key→action table so it's testable by dispatching synthetic keydowns. Deps: nearly
  everything (it's a dispatcher) — pass a command object. Risk: MED-HIGH (broad surface, but mechanical).
- [ ] **View menu toggles + selection/tool filters** — banners `// ── View menu toggle pill state` …
  `// ── View tool buttons` (~6124–6489, ~365 ln) → `ui/view_toggles.js`. Deps: store, DOM buttons.
  Risk: MED.
- [ ] **Coloring / orbit / tools submenus** — banners `// ── Tools menu (Bend / Twist)` …
  `// ── Coloring submenu` (~5737–6019, ~280 ln) → `ui/view_menus.js` (pairs with existing
  `scene/coloring_modes.js`). Deps: store, designRenderer, DOM. Risk: MED.

## Tier 5 — file / session infra (central — extract carefully, late)

These touch boot/lifecycle. High blast radius; do after the loop is well-grooved.

- [ ] **File open / save + assembly save** — banners `// ── File open / save` +
  `// ── Assembly file save helpers` (~4279–4620, ~340 ln) → `ui/file_io.js`. Deps: api, store,
  file overlay, multi-doc. Risk: HIGH.
- [ ] **Menu bar + multi-document spawn** — banners `// ── Menu bar` + `// ── Multi-document: New / Open`
  (~4681–5004, ~320 ln) → `ui/menu_bar.js`. Deps: doc_id, broadcast, every menu action. Risk: HIGH.
- [ ] **Connection monitor / autosave / SSE** — banners `// ── Backend connection monitor` …
  `// ── Library SSE` (~9527–9814, ~287 ln) → `app/lifecycle.js`. Deps: api, /health, store, badges.
  Risk: HIGH (lifecycle).

## Tier 6 — dev-only / debug (no user risk; extract anytime to de-bloat)

Gated by `?debug` / `import.meta.env.DEV`. Safe to move (smoke still applies); good "warm-up" targets
for a fresh session.

- [ ] **Extension arc debug tools** — banner `// ── Extension arc debug tools (dev only)`
  (~14760–15184, ~424 ln) → `scene/debug/extension_arc_debug.js`. Dev-only. Risk: LOW.
- [ ] **Browser dev-tools debug helpers** — banner `// ── Browser dev-tools debug helpers`
  (~2950–3362, ~412 ln) → `scene/debug/devtools_helpers.js`. Dev-only (`window.__*`). Risk: LOW.
- [ ] **Label / terminus audit** — banner `// ── Label / terminus audit` (~7356–7565, ~210 ln) →
  `scene/debug/terminus_audit.js`. Debug. Risk: LOW.

---

## Already-extracted (for reference — do NOT re-propose)

See `main_js_extraction_log.md` for the full list. Modules under `scene/` and `ui/`: bundle_geometry,
rotation_math, measurement_tool, scaffold_coverage, strand_length, overhang_maps, gear_math,
assembly_diff, design_queries (+flexibleRunForBead), cluster_joint_math, aksel_format,
assembly_groups_util, color_util (+hexFromInt, atomColorsFromLetters), fret_util, vec_math, motion_chip,
scaffold_assign, atom_filter, selection_bbox, belt_rider, overhang_hover_picker, assembly_lasso,
coloring_modes, assembly_layout, ndc, flex_tethers, cluster_entries, empty_space_menu, slice_plane,
plate_view, kinematics_ticker.

## Smaller leftovers (after the tiers above)

Slice-plane wiring (`// ── Slice plane`, much already in `slice_plane.js`), Plates-and-tubes wiring
(most in `plate_view.js`), context-menu blocks (scaffold/overhang/blunt — `~3548–3817`), Create Near/Far
Ends (`~14139–14539`, ~400 ln — pairs with `project_near_far_ends`), Photo-mode/export-repr wiring
(`~12214–12545`). Pick these up opportunistically once the tiers drain.
