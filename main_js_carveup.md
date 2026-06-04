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
7. **Before finishing, overwrite the `## Next-session handoff` block below** with a short addendum (≤8
   lines): the single recommended next region (+ one-line why), the fixture to load, the gesture gate to
   build first, the split plan, and any gotcha this batch uncovered. It's a *living pointer* — replace it,
   don't append. A cold next session reads it first and starts there without re-deriving the priority.

**Line numbers drift** as the file shrinks — they are a 2026-06-03 snapshot at main.js = 15,614 LOC.
**Anchor by the `// ──` banner text** (stable) when locating a region, not the line number.

**Dependency surface** below is a rough pre-read estimate — VERIFY by reading the region when you
claim it. The map's job is sequencing + module naming + risk tiering, not exact deps.

**Don't:** parallelize edits to main.js (worktrees collide on the shared import block + closure —
serial is correct for one god-file). Don't touch `_PHASE_*`, backend, or rendering invariants.

---

## Next-session handoff

_Living pointer — each session overwrites this (step 7). Last updated 2026-06-04, after extraction #41 (View tool buttons → `ui/view_tool_buttons.js`, −113 ln)._

**View tool buttons DONE (#41, −113 ln).** The handoff's "View menu toggles + selection/tool filters →
one `ui/view_toggles.js`, ~365 ln, MED" premise was MIS-SCOPED — it's ~5 adjacency-lumped blocks, not one
subsystem (see the Tier-4 entry's breakdown). Extracted only the cleanly-cohesive `.vt-btn` row; `_setMenuToggle`
is a 43-use shared util and the Selection-Filter block is welded to the drill-lock machine owned by region
~717 — both logged as separate future lifts, NOT this region. Shared `_undefinedHighlightOn` (a `let`
declared ~250 ln *after* the factory init) reached via get/set shim arrows — TDZ-safe because they're only
invoked from deferred click handlers (same as the inline code).

**Next best (clean, well-bounded): Tier 4 — Coloring / orbit / tools submenus** — banners `// ── Tools menu
(Bend / Twist)` (~5337) … `// ── Coloring submenu` (~5407–5618) → `ui/view_menus.js` (pairs with existing
`scene/coloring_modes.js`). Deps: store, designRenderer, DOM. The Coloring submenu (Strand/Base/Cluster/
Overhang/CPK) is the meaty cohesive sub-block. Risk MED. jsdom-testable, no GPU gesture. **VERIFY spans
first** (#39/#40/#41 each taught this lesson — the map's "what it is" descriptions drift).
- Alternative if you want a token-cheap warm-up: Tier 6 dev-only (`devtools_helpers` ~412 / `terminus_audit`
  ~210 / `help_menu_toggles` ~76). Or the small independent blocks left in the View-toggles region
  (Tool Filter toggles ~45 ln; the pill-state subscriber + 3 visibility helpers).

- **Lower-risk warm-ups (Tier 6 dev-only, gated by `?debug`/DEV, LOW risk, token-cheap):**
  `devtools_helpers` (~412 ln, `window.__*`) / `extension_arc_debug` (~424 ln) / `terminus_audit` (~210 ln) /
  `help_menu_toggles` (~76 ln). Or Tier 4 **Coloring/orbit/tools submenus** (~280 ln → `ui/view_menus.js`).
- **Still-in-main, deliberately deferred:** FK propagation (`_applyFKLive`); Polymerize-region sub-part
  `scene/joint_pick.js` (`_onToolPickPointerDown` + cluster raycaster — HARD, gesture-bound).
- **Gotcha banked this batch:** when extracting many `registerShortcut` calls, the document `keydown`
  listener can move into the factory cleanly (commit 2) — but it's then the SINGLE point of failure for ALL
  shortcuts, and `just smoke` won't catch a missing listener (its Ctrl+K/Escape go through `initCommandPalette`,
  not this registry). The app exercise MUST press one of THIS module's keys (e.g. `` ` `` → debug menu pill)
  to prove the listener attached. Other `registerShortcut` call sites elsewhere in main.js are NOT part of
  the region — scope by line range, not by symbol.

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

- [x] **Assembly canvas pointer handler** — banner `// ── Assembly canvas pointer handler` +
  `// ── PartGroup click-through` (~10838–11174 now, ~340 ln) → `scene/assembly_pointer.js`. Deps:
  assemblyRenderer, camera, store, group helpers, lasso. Contains `_onAssemblyClick`. GESTURE E2E.
  Risk: HIGH. **Split:** (a) joint-ring pick, (b) instance select, (c) group click-through.
  **DONE 2026-06-04** — all of (a)/(b)/(c) lifted; the whole pointer/drag region now lives in the
  factory. (a) ring-drag was the last piece: extractions #30 (drag handlers + state, commit 7c466b4)
  + #31 (`_onAssemblyPointerDown`, commit 012d4ce). −315 ln off closure across both. Gate: vitest 383
  + assembly_joint_drag.spec.js + assembly_select.spec.js 3/3 + smoke 21/21.
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
  - **(a) ring-drag gate — DONE (2026-06-04).** `e2e/assembly_joint_drag.spec.js` drives the part-joint
    cluster drag and asserts a recorded rotation (covers #28's `rotationDeltaMatrix`). Writing it uncovered
    + FIXED a real bug: assembly per-instance designs weren't enriched with world joint axes, so the drag
    threw (`joint.axis_origin` undefined). See log.
  - **(b) instance select — DONE** (extraction #29, commit pending): `_onAssemblyClick` + its single-use
    helper `_toggleAssemblyOverhangSelection` lifted to `scene/assembly_pointer.js` factory
    `initAssemblyPointer({…})→{onAssemblyClick}`. Shared mutable state passed as get/set shims
    (`_assemblyPtrDownAt` get+set; `_translateRotateActive` get; `_selectedAssemblyCluster` /
    `_assemblySelectedPartJoint` set); `clusterPanel` (wired ~200 ln later) as a lazy getter. main.js keeps
    the `const _onAssemblyClick = _assemblyPointer.onAssemblyClick` name so the two listener (de)register
    sites are untouched. −122 ln off closure. 11 jsdom factory tests (non-left/belt/no-ptrdown/drag/
    new-select+gizmo/empty-clears/reclick-cluster/overhang-toggle/group-click-through/gizmo-leave/
    gizmo-commit-elsewhere). Gate: vitest 372 + `assembly_select.spec.js` 2/2 (real raycast = the app
    exercise) + smoke 21/21. Removed now-dead `resolveGroupClickThrough` import from main.js (only the
    module uses it). No TDZ: no top-level `await` precedes the const, so it's defined before any deferred
    `_enterAssemblyMode`.
  - **(a) ring-drag SHELL — DONE 2026-06-04** (extractions #30 + #31). Step 1 (#30, commit 7c466b4):
    moved the drag handlers (`_updateFreeDragPosition`/`_updatePartJointDrag`/`_onAssemblyDragMove`/
    `_onAssemblyDragUp`) + their drag state (`_partJointDrag`/`_freeDrag`/`_pendingFreeDrag`) into the
    factory as module-internal state; exposed `beginPartJointDrag` / `cancelDrag` so the still-inline
    pointer-down could arm a drag and the exit-cleanup could tear one down. Step 2 (#31, commit 012d4ce):
    moved `_onAssemblyPointerDown` itself in (now `onAssemblyPointerDown`), `beginPartJointDrag` became an
    internal call. `_partJointDrag`/`_freeDrag`/`_pendingFreeDrag` are NOT shims — only these handlers
    touched them, so they're owned by the module; the only external toucher (assembly-exit cleanup) calls
    `cancelDrag()`. Shims used: get/set `_assemblySelectedPartJoint`, get `_selectedAssemblyCluster`,
    set `_assemblyRightDownAt`, set `_assemblyPtrDownAt`, get `_translateRotateActive`.
- [~] **Polymerize / kinematics / joint-pick cluster** — banners `// ── Polymerize along a belt` …
  `// ── Joint arrow pick handler` (~7775–8108 now, drifted from ~8187) → MULTIPLE modules
  (`scene/kinematics_ticker.js` already exists — move ticker wiring there;
  `scene/joint_pick.js`; polymerize → its own). Deps: assemblyRenderer, assemblyJointRenderer, api,
  store. Risk: HIGH. **Must split into ≥3 commits.**
  - **(belt polymerize) — DONE** (extraction #32, this batch): `_beltCtxForRider`/`_beltFillInfo`/
    `_polymerizeBelt` → `scene/belt_polymerize.js` factory `initBeltPolymerize` + pure
    `buildBeltPolymerizeCopies` (the count-1 evenly-spaced copy-transform builder). Confirmed WANTED —
    wired into the real belt-path panel (`getBeltFillCount`/`onPolymerizeBelt` deps at the
    `initPolymerizePanel` call), not just dbg hooks. Lazy `let _beltPolymerize` mirrors #26's `_importMenu`
    (deps consumed ~1000 ln before the factory init). −34 ln off closure; removed now-dead
    `beltRiderCtx`/`beltRiderFill`/`beltFrameAt` imports. 10 vitest (5 pure copy-builder + 5 factory:
    no-ctx-null / fill-passes-bbox / no-ctx-error-toast-no-api / success-posts-copies / null-response-fail).
    Gate: vitest 393 + smoke 21/21. Belt-polymerize gesture not hand-exercised (needs a built belt
    assembly) — verbatim move + unit-tested + smoke boot gate, per #24's accepted caveat.
  - **(kinematics-ticker wiring) — DONE** (extraction #33, this batch): moved the 17-line
    `nadocGearDebug` dump into `scene/kinematics_ticker.js` as a `gearDebug()` method (it pokes the
    ticker's internal `debugState` + gear graph, so it belongs in the module). main.js keeps
    `window.nadocGearDebug = () => kinematicsTicker.gearDebug()` + the visibilitychange-flush listener +
    the `__NADOC_KINEMATICS__` handle as thin DOM/window lifecycle wiring (DOM-listener registration is
    an app-composition concern, not the module's — left at main-loop altitude on purpose). Also
    **de-interleaved the banner**: the `_syncAssemblyBluntEnds` + cluster-pick helpers were wrongly under
    the "Kinematics ticker" banner; they now have their own `// ── Assembly blunt-end sync + cluster pick
    helpers` banner. 3 vitest (first coverage for this module: empty-dump / joint-summary-subset /
    log-tag+return). Gate: vitest 396 + smoke 21/21.
  - **Remaining sub-parts (NOT done):** `scene/joint_pick.js` (`_onToolPickPointerDown`
    + `_pickActiveClusterEntry` + cluster raycaster — HARD, gesture-bound to clusterGizmo/jointRenderer).
    NOTE: the region as read is interleaved with `assemblyContextMenu` / `_defineAssemblyMate` /
    `_activateTranslateRotateTool` (a giant fn) — those are NOT part of this region; scope each sub-part
    to its cohesive block. The blunt-end-sync + cluster-pick block now has its own banner (above).
- [x] **Rigid-body group gizmo + PartGroup gizmo** — banners `// ── Rigid-body group gizmo attachment`
  + `// ── PartGroup gizmo` → `scene/group_gizmo.js` (factory `initGroupGizmo` + pure `revoluteCommitValue`).
  **DONE in 3 commits (2026-06-04):** (a) #35 `374721b` pure commit-value; (b)+engine #36 `20c3347`
  gear-live revolute-drag engine + `attachGroupGizmo`; (c) #37 `ea1fd12` `attachGroupGizmoForGroup` +
  group transform-context. −346 ln off the closure total; 20 vitest (7 pure + 13 factory). Shared helpers
  (`createAssemblyTransformContext`/`applyAssemblyPrimaryLive`/`queueAssemblyPrimaryCommit`/pending Maps)
  stay in main.js as injected deps. **FK propagation (`_applyFKLive`) deliberately left separate.**
  Finding: the demanded group-drag gesture e2e was unnecessary — captured-callback factory tests beat a
  flaky TransformControls-handle drag (see log). Flagged a latent #34 bug in assembly-exit cleanup.
- [x] **Multi-select visual feedback (purple union BoxHelper)** — banner `// ── Multi-select visual
  feedback` → `scene/assembly_multi_box.js` (NOT the map's `multi_select_box.js`; named for the assembly
  scope). Deps: scene, store, assemblyRenderer. Pure core lifted into existing `selection_bbox.js`. Risk: MED.
  **DONE** (extraction #34, this batch) — the banner's "~192 ln" was overshoot: the cohesive block is the
  single `_updateAssemblyMultiBox` fn (~46 ln). Factory `initAssemblyMultiBox({scene,store,assemblyRenderer})
  →{update,dispose}` + pure `instanceUnionBox(centers, wanted)` added to `selection_bbox.js`. −37 ln off
  main.js. 14 vitest (5 pure union-box: union/ignore-unwanted/skip-sizeless/null-no-match/null-all-sizeless +
  9 jsdom factory: empty/single-suppress/≥2-draws-purple/single-member-group-draws/transitive-group-fold/
  dispose-prior-no-dupe/drop-below-2-clears/dispose). Hoisting gotcha (call sites at the 'assembly' subscriber
  + group-gizmo drag PRECEDE the old fn def): init moved to a `const` right before the `subscribeSlice('assembly')`
  registration (scene/store/assemblyRenderer all available there) — no lazy-let needed. Gate: vitest 409 +
  smoke 21/21. **Live purple-box gesture NOT hand-exercised** (needs a built ≥2-part assembly + Ctrl-lasso
  multi-select) — verbatim move + unit-tested + smoke boot gate, per #32/#24's accepted caveat.
- [x] **Coalesced assembly part-refresh** — banner `// ── Coalesced assembly part-refresh`
  (~9332–9429, ~98 ln — the "~200 ln" estimate overshot again) → `scene/assembly_refresh.js`.
  **DONE** (extraction #38, this batch) — factory `initAssemblyRefresh({store, api, assemblyRenderer,
  assemblyJointRenderer, syncLog, setSyncStatus, syncAssemblyBluntEnds, selfSavedPaths, getClusterPanel})
  →{requestRefresh, flush, dispose}`. −83 ln off the closure. No pure core (the debounce IS the behavior).
  10 vitest with **fake timers** (`vi.useFakeTimers` + `advanceTimersByTimeAsync`): inactive-no-op /
  no-id-no-op / burst→one-refresh / last-id-wins / full-pipeline+shared-source-sync / empty-assembly-bails /
  mid-flight-queues-one-followup (via a deferred-promise in-flight hold) / dispose-cancels / flush-runs-now /
  throw-recovers-latch. Gate: vitest 439 + smoke 21/21. **Placement:** real `const` init placed right before
  `_handleLibraryEvent` (both callers — SSE @9308, broadcast @13342 — fire async post-init, so no lazy-let
  needed; `selfSavedPaths`/syncLog/etc. all defined earlier). `clusterPanel` (wired ~1000 ln later) via lazy
  `getClusterPanel: () => clusterPanel`. dispose/flush are additive API (unused by main.js — a pending timer
  surviving assembly-exit still no-ops via the `assemblyActive` guard, so exit behavior is verbatim-preserved;
  NOT wired into exit cleanup to keep the lift verbatim). **Live coalesced-refresh gesture NOT hand-exercised**
  (needs a built multi-part assembly + a part-editor save burst) — fake-timer units cover the exact
  debounce/coalesce contract, per #34/#32/#24's accepted caveat. **Tier 3 is now fully drained.**

## Tier 4 — menus / toggles / shortcuts (many small handlers)

- [x] **Keyboard shortcuts** — banner `// ── Keyboard shortcuts` (~6207–6731, ~525 ln) →
  `ui/keyboard_shortcuts.js` `initKeyboardShortcuts({deps})`. **DONE in 2 commits (2026-06-04).**
  **Map premise was STALE:** the "ONE giant keydown handler / factor to a key→action table" was already
  done — the region was 21 individual `registerShortcut({...})` calls into `input/shortcuts.js`'s registry
  + a single `document.addEventListener('keydown', dispatchKeyEvent)`. So the real work was the *factory
  lift* (drain the closure), not table extraction. Wide-but-shallow: ~33 deps, but handlers move verbatim.
  - **#39 `c4c5039` (Group 1):** view/tool toggles + number hotkeys (u/k/Tab/q/Shift+D/v/1–6/`/f/m/b/c/o)
    → factory; G2 stays inline. Added `clearShortcuts()` to `input/shortcuts.js` for test isolation
    (registry is a module singleton). 13 vitest.
  - **#40 `a519334` (Group 2 — COMPLETES region):** Ctrl-modifier file/edit (Ctrl+O/S/Shift+S, Ctrl+Z/Y/
    Shift+Z) + Delete + Escape folded in; the document `keydown` listener now attaches from the factory;
    dropped now-unused `dispatchKeyEvent` import (registerShortcut stays — 4 OTHER call sites at 8735/9180/
    11029/11513 are NOT part of this region). 9 more vitest (22 total).
  - main.js **−492 ln** total. Live-mutable closure state (part-edit ctx, assembly ws path, oo-edit id set,
    translate/rotate flag) injected as getters; all else as stable fn/module refs. Gate: vitest 461 +
    smoke 21/21 + 2 running-app exercises (factory-attached listener toggles the debug pill; Ctrl+Z+Escape
    fire clean). **Lesson (re-confirmed): the carve-up banner premises drift — the infra under this banner
    had already been refactored once; READ before trusting the "what it is" description, not just the LOC.**
- [~] **View menu toggles + selection/tool filters** — banners `// ── View menu toggle pill state` …
  `// ── View tool buttons` (~5724–6088, ~365 ln). **PREMISE WAS STALE / MIS-SCOPED (verified 2026-06-04):
  this is NOT one cohesive subsystem** — it's ~5 adjacency-lumped blocks, several entangled with state
  owned by *other* regions. Do NOT force the whole thing into one `ui/view_toggles.js`. Breakdown:
    - **View tool buttons** (`.vt-btn` row: length heatmap / seq / undef / grid / overhang names / expanded
      / deform / unfold / cadnano2d) → **DONE** `ui/view_tool_buttons.js` (extraction #41, commit pending;
      −113 ln; 13 vitest; smoke 21/21 + real-app vt-button exercise). Self-contained; shared
      `_undefinedHighlightOn` reached via get/set shims.
    - **`_setMenuToggle`** (the menu-pill toggler defined at the top of the region) is a **43-use shared
      util**, NOT a feature factory member — if extracted at all it belongs in its own `ui/menu_toggle.js`
      shared-util lift (mechanical 43-site import swap), separate from this region.
    - **Selection Filter toggles** (`#select-filter .sf-btn`) is entangled with the **drill-lock state
      machine** (`_manualFilters`/`_isManualSelect`/`_reflectDrillLevel`/`_resetToAutoBaseline`) owned by the
      `// ── Selection-filter mode` region (~717) — extract those together, not here.
    - The **View-menu pill-state subscriber** + 3 visibility helpers (`_syncAssemblyMenuVisibility` /
      `_syncImportMenuVisibility` / `_syncDeformMenuEnabled`), the **Tool Filter toggles** block, the
      **deform→selectableTypes save/restore** subscriber, and **Browser tab title** are each small
      independent blocks — pick off opportunistically, do not bundle.
- [ ] **Coloring / orbit / tools submenus** — banners `// ── Tools menu (Bend / Twist)` (~5337) …
  `// ── Orbit mode submenu` (~5395) … `// ── Coloring submenu` (~5407–5618, ~280 ln) → `ui/view_menus.js`
  (pairs with existing `scene/coloring_modes.js`). Deps: store, designRenderer, DOM. Risk: MED.

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
