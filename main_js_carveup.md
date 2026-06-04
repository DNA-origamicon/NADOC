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

- [~] **Help / Hotkeys modal** — banner `// ── Help / Hotkeys modal` (~13187, 6 ln). **RESOLVED
  2026-06-03: NOT a factory target — leave inline.** Re-read confirmed the modal itself is 6 lines of
  `.classList` toggles (markup lives in index.html); extracting it would add a module for zero payoff.
  The remaining mass under this banner is two *separate* regions, re-homed below — don't treat them as
  "the help modal":
    - Help-menu **debug toggles** (OH-roots / domain-ends / linker-debug / FJC-sim, incl. the
      `_logOvhgMapReport` cross-validation dump) → folded into Tier 6 as **Help-menu debug toggles**.
    - The **Create Seam** handler (HC/SQ scaffold-crossover lookup tables + Hamiltonian path) → a
      standalone region under "Smaller leftovers" (pairs with `scaffold_coverage.js`). Do NOT fold it
      into any help-modal extraction.
- [x] **Strand length histogram** — banner `// ── Strand length histogram` (~12614–12813, ~200 ln) →
  `ui/strand_length_histogram.js`. Deps: store (currentGeometry/Design), DOM canvas, api (delete-by-bin
  context menu). Has a pure core (bin counts) — extract + test that. Risk: LOW-MED.
  **DONE** (extraction #20, commit pending) — factory `initStrandLengthHistogram` + pure
  `computeStrandLengthBins`; −192 ln off closure; 13 vitest (6 pure + 7 jsdom factory); smoke 21/21 +
  real-app expand exercise. 2D-canvas hit-testing covered by jsdom click test (no scene_harness needed).
- [x] **Overhang sequences panel** — banner `// ── Overhang sequences panel` (~2488–2715, ~227 ln) →
  `ui/overhang_sequences_panel.js`. Deps: store, api, DOM, selectionManager. Risk: MED.
  **DONE** (extraction #21, commit pending) — factory `initOverhangSequencesPanel` + pure
  `liveOverhangs` (ghost-strand filter) & `selectedStrandIds`; −224 ln off closure; 20 vitest (9 pure +
  11 jsdom factory: collapse/expand/empty/slider/Gen-visibility/Set-patch/Bind-toggle/row-select/
  highlight/design-rebuild); smoke 21/21 + real-app expand+slider+collapse exercise (zero console errors).
  `showToast` imported directly (not a dep). Gotcha: hingeV4's 36 *file-level* overhangs don't
  materialize at runtime (`design.overhangs`=0 after load) — NS_trans_fix (51) is the design with real
  runtime overhangs. 2D/DOM panel → no scene_harness needed.
- [x] **Strand groups panel** — banner `// ── Strand groups panel` (~2493–2687, ~194 ln) →
  `ui/strand_groups_panel.js`. Deps: store (strandGroups), selectionManager, DOM rebuild + subscribe. Risk: MED.
  **DONE** (extraction #22, commit pending) — factory `initStrandGroupsPanel` + 4 pure cores
  (`effectiveStrandColors` / `groupStrandsByColor` / `trimGroupsRemovingStrands` /
  `selectableGroupStrandIds`); −192 ln off closure; 20 vitest (12 pure + 8 jsdom factory:
  no-DOM no-op/expand-rebuild/collapse-suppress/row-multiselect/New-seed/New-trims-old/From-colors-bucket/
  delete); smoke 21/21 + real-app exercise (New×2 + inline rename ✎→✓ + From-colors + delete + collapse,
  zero console errors). `pushGroupUndo`/`buildStapleColorMap`/`hexFromInt`/`showToast` imported directly
  (not deps). Dead `pushGroupUndo` import removed from main.js. Pure-DOM panel → no scene_harness gesture
  needed (the harness load was only to dismiss welcome for the exercise).
- [~] **Library panel (welcome screen)** — banner `// ── Library panel (welcome screen)` (~8877).
  **MOSTLY ALREADY DONE (corrected 2026-06-03):** the panel itself was extracted to `ui/library_panel.js`
  long ago (`initLibraryPanel`, May 17) — the carve-up entry was stale. What lives under the banner now
  is NOT the panel; it's three pieces:
    - `_pickLattice` (the New-Part lattice-type modal) → **DONE** `ui/lattice_picker.js` `pickLattice()`
      (extraction #23, commit pending; 7 jsdom tests; −50 ln off closure).
    - `_openPartFromServer` / `_openAssemblyFromServer` (file-open orchestration) — **DEFER to Tier 5**:
      heavily coupled to closure lifecycle (`_flAppendLog`/`_flSetProgress`/`_flShowError`/`_enterAssemblyMode`/
      `_assemblyLoadOnProgress`/`_assemblyLoadSettle`/`_setWorkspacePath`/`_revealWorkspaceForEmptyPart`…).
      These belong with **File open / save** (Tier 5), not a clean standalone lift.
    - the `initLibraryPanel({…})` call + inline `onNewPart`/`onNewAssembly` callbacks — thin wiring, leave in place.
- [x] **Fluorescence + FRET checker** — banner `// ── Fluorescence + FRET Checker` (~13056–13135,
  ~80 ln) → `scene/fret_checker.js` (named `scene/`, NOT the map's `ui/fret_panel.js` — there's no panel
  DOM, it's a glow/menu-toggle controller; co-located with `scene/fret_util.js`). Deps: designRenderer,
  store, `_setMenuToggle`. Risk: LOW-MED.
  **DONE** (extraction #24, commit pending) — factory `initFretChecker` + pure `buildFretLookups`
  (lookup-table build); `FRET_PAIRS`/`FRET_QUENCHED_SCALE` moved into the module. −72 ln off closure.
  9 vitest (3 pure + 6 jsdom factory: no-glow-before-toggle / fluorescence-on-glows-emitters-only /
  fluorescence-off-clears / FRET-quench-scale / refreshIfFret-only-when-on / geometry-reload-rebuild).
  Render-loop coupling (`if (_fretOn) _refreshGlowModes()` every frame) → exposed `refreshIfFret()`.
  Left the unrelated `menu-view-joints` handler in main.js. Removed now-dead `fretQuenchedDonors` +
  `FLUORO_EMISSION_COLORS` imports from main.js. smoke 21/21 + real-app exercise (toggle both modes +
  600ms render-loop ticks, zero console errors — **glow not visually confirmed**: scaffold-only part has
  no fluorophores; glow LOGIC is unit-tested, visual path needs a fluorophore design).

## Tier 2 — import / export menus (mechanical, repetitive)

Many sibling handlers that each wire a menu item → api call → download/import. Extract as one factory
per direction with a handler table.

- [x] **Export menu** — banners `// ── Export Sequences (CSV)` … `// ── Export GROMACS …`
  (~12391–12609, ~218 ln) → `ui/export_menu.js`. Deps: store, api (`showToast`/`docHeaders`/
  `getStapleColorOrder` imported directly, not deps). Each export is independent → easy to test the
  wiring table. Risk: LOW-MED (no canvas).
  **DONE** (extraction #25, commit pending) — factory `initExportMenu({store, api})` + module fns
  `exportErrorMessage` (pure) / `triggerDownload` / `showNamdPromptModal`. −215 ln off closure. 16 vitest
  (2 pure exportErrorMessage + triggerDownload + 2 showNamdPromptModal + 11 factory: no-DOM no-op /
  CSV-success / no-design-guard / failed-export-msg / xlsx-color-order / PDB+PSF download URLs / STL
  success / 3MF-coloring-detail / GROMACS-stub-toast / dismiss-clears-class / NAMD-download+modal).
  smoke 21/21 + real-app exercise (load scaffolded part → CSV download + PDB download + GROMACS toast,
  zero console errors). Removed now-unused `getStapleColorOrder` from main.js's spreadsheet import.
  GROMACS export stays stubbed (poller removed 2026-05-17); `label`/`dlBtn` kept dead for the re-impl.
- [x] **Import menu + callbacks** — banners `// ── Import helpers` … `// ── Import PDB` + library import
  callbacks (~12162–12388, ~227 ln) → `ui/import_menu.js`. Deps: store, api, workspace, libraryPanel +
  8 lifecycle callbacks (`resetForNewDesign`/`show`+`hideWelcome`/`renderRecentMenu`/`setWorkspacePath`/
  `setFileName`/`setSyncStatus`/`saveAs`/`setFileHandle`). Risk: MED-HIGH (more coupling than Export).
  **DONE** (extraction #26, commit pending) — factory `initImportMenu(deps)` + pure
  `sanitizeImportName` / `importedClusterOverhangExtras`; returns
  `{importCadnanoWithAutodetection, importScadnanoWithAutodetection, runPdbImport}`. −210 ln off closure.
  12 vitest (3 sanitize + 2 extras + 7 factory/runPdbImport: returns-callbacks/no-DOM, PDB-menu→modal
  wiring, runPdbImport null/needs-decision/dna/protein/both). smoke 21/21 + real-app exercise
  (library-panel caDNAno button → lazy `_importMenu` wrapper → file input; PDB menu → modal; zero console
  errors). **Wiring gotcha:** the two autodetection callbacks are consumed at the `initLibraryPanel` call
  ~3000 ln earlier (was function-hoisting); replaced with lazy `() => _importMenu?.…()` wrappers (mirrors
  the existing `onOpenPart` arrow pattern) + a `let _importMenu = null` declared before that init.
  Removed now-dead `openImportPdbModal` import from main.js. `showToast`/`openFileBrowser`/
  `openImportPdbModal` imported directly in the module. The file-input flows can't be jsdom-driven (no
  user file) → covered by verbatim move + app exercise, not vitest.

## Tier 3 — assembly interaction (big, higher coupling — gesture-e2e REQUIRED)

The largest single blocks and the most coupling into assembly state. Each needs a gesture e2e
(scene_harness) + smoke. Split the giant ones; don't extract 900 lines in one commit.

- [~] **Assembly canvas pointer handler** — banner `// ── Assembly canvas pointer handler` +
  `// ── PartGroup click-through` (~10838–11174 now, ~340 ln) → `scene/assembly_pointer.js`. Deps:
  assemblyRenderer, camera, store, group helpers, lasso. Contains `_onAssemblyClick`. GESTURE E2E.
  Risk: HIGH. **Split:** (a) joint-ring pick, (b) instance select, (c) group click-through.
  - **(c) group click-through — DONE** (extraction #27, commit pending): pure decision
    `resolveGroupClickThrough({assembly,hitInstanceId,activeGroupId,groupDiveStack})→{action,patch}`
    added to existing `scene/assembly_groups_util.js` (co-located with `findOwningGroupId`, now no
    longer imported in main.js). 7 vitest. The scene pick + `setState` stay inline (verbatim patches).
    Pure → vitest+smoke gate (no gesture e2e: behavior-identical wiring). −10 ln off closure.
  - **(a) dedup — DONE** (extraction #28, commit pending): part-joint drag `worldDelta` now reuses the
    tested `rotationDeltaMatrix` (gear_math) instead of an inline `T·R·T⁻¹` copy. −7 ln.
  - **Assembly-gesture harness — DONE (2026-06-04, prerequisite for the lift).** `e2e/assembly_select.spec.js`
    (2 tests, stable) + harness helpers + dev hooks now drive the assembly canvas pointer handlers through
    the real raycast and assert on selection state. This is the **(b) gesture gate**. Build notes + the 5
    hard-won gotchas (v2 wire format, file-source-not-inline, broken auto-fit → deterministic framing,
    thin-rod pixel precision, MOVE-mode occlusion) are in `main_js_extraction_log.md`.
  - (a) ring-drag SHELL + (b) instance select: still inline, but now UNBLOCKED to lift. Verbatim-move
    `_onAssemblyClick` (b) / `_onAssemblyPointerDown` + drag handlers (a) into `scene/assembly_pointer.js`
    with get/set shims for the shared mutable state (`_selectedAssemblyCluster`, `_assemblySelectedPartJoint`,
    `_assemblyRightDownAt`, `_assemblyPendingPartJoints` Map, read-only `_translateRotateActive`), gated by
    `assembly_select.spec.js` + smoke. Do the lift in ≥2 commits (b first — it's covered by the spec; then a).
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
- [ ] **Help-menu debug toggles** — under banner `// ── Help / Hotkeys modal` (~13195–13271, ~76 ln) →
  `scene/debug/help_menu_toggles.js`. The OH-roots / domain-ends / linker-anchor / FJC-sim menu wiring
  plus `_logOvhgMapReport` (the 4-map cross-validation console dump). Deps: designRenderer (glow),
  `_applyOhRootsGlow`/`_applyDomainEndsGlow`, linkerAnchorDebug, the `_ovhg*Map` lookup tables. Risk:
  LOW-MED (the report reads several closure maps — pass them in or keep the report a thin closure shim).
  Re-homed here from the mis-scoped Tier-1 "Help / Hotkeys modal" entry.

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

**Create Seam handler** — `menu-create-seam` click handler under the `// ── Help / Hotkeys modal`
banner (~13273 onward, ~250 ln). HC/SQ scaffold-crossover lookup tables + bow-direction sets + a
Hamiltonian-path seam build → `scene/create_seam.js` (pairs with `scaffold_coverage.js`'s
`findHamiltonianPath`; see `project_create_seam`). Has a pure core (the lookup-table-driven crossover
resolution). Risk: MED. Re-homed from the mis-scoped "Help / Hotkeys modal" entry.
