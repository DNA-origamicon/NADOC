# main.js carve-up map — stateful-subsystem extraction backlog

**Purpose.** main.js is one large `async function main()` closure (~9.2k lines as of 2026-06-05, down
from ~16.5k). The pure-helper well is drained (see `main_js_extraction_log.md`) and — as of #61 — every
Tier 1–5 *stateful subsystem* (panels, dialogs, menus, event-handler clusters) is extracted too. The loop
is **near-complete**: the remaining mass is the lifecycle spine + thin per-action wiring that's correctly
inline, plus a couple of deliberately-deferred coupled regions. See the handoff for the STOP rationale.

> **⚠ THIS MAP IS SEQUENCING-ONLY. Its LOC counts, line numbers, and "what it is" descriptions are NOT
> authoritative.** They are a one-time snapshot that has drifted under continuous refactoring and has been
> wrong about a region's *scope or cohesion* at least five times (#20 banner-overshoot, #39/#40 stale
> "giant keydown handler", #41 + #42 "this is one subsystem" when it was 5 adjacency-lumped blocks, the
> already-extracted library panel). **Trust only two things here:** (a) the `// ──` **banner text** as a
> locator, and (b) the **tier ordering** as a rough priority. Everything else — line numbers, LOC
> estimates, dep lists, "it's basically X" — is a *hint to verify*, never a fact to act on. Before
> claiming any region: READ it, find where the *cohesive* block actually ends (the map groups by banner
> adjacency, which ≠ cohesion), and re-derive its real size / deps / risk. If the "region" turns out to be
> several lumped blocks, extract the ONE cohesive sub-block and re-home the rest as separate entries. Fix
> the entry you touched on your way out (mark it `[~]`, correct the description) so the next session pays
> less of this tax than you did.

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

**Line numbers are decorative** — they were a 2026-06-03 snapshot (main.js was 15,614 LOC then; it's
~10.9k now) and every extraction shifts them. **Always locate a region by its `// ──` banner text**
(`grep -n "// ──" main.js`), never by the line number printed here.

**Dependency surface + LOC + "what it is"** below are rough pre-read guesses — RE-DERIVE by reading the
region when you claim it (see the ⚠ callout above). The map's only reliable jobs are sequencing, module
naming, and coarse risk tiering — not exact deps, sizes, or scope.

**Don't:** parallelize edits to main.js (worktrees collide on the shared import block + closure —
serial is correct for one god-file). Don't touch `_PHASE_*`, backend, or rendering invariants.

---

## Next-session handoff

_Living pointer — each session overwrites this (step 7). Last updated 2026-06-05. **STRATEGY SHIFT: stop nibbling cheap
pure cores — take the HARDEST regions head-on, in larger multi-commit campaigns, hardest-first.** The pure-core /
narrow-sub-block well is effectively dry. What remains is four big coupled stateful regions; another ~50-ln pure peel
leaves the real structural debt (the coupled assembly-transform subsystem) exactly as tangled. #72 (atomistic colour
core → `computeAtomStrandColors`, −61 ln, main.js 9006) was the LAST cheap cut — see the log row for its detail._

**Why hardest-first now.** Every remaining frontier item is HARD (gesture-bound and/or shared-state coupled), and the
map's end-state ("the closure holds zero cohesive logic clusters") is gated *entirely* on these four. Do each as a
deliberate campaign, not a one-commit nibble: (1) map the coupling with `rg` first; (2) build/extend the gesture gate
ONCE up front; (3) split the lift across commits (the COMMIT rule already allows >~250 ln across commits); (4) lift
verbatim. Budget a whole session per campaign — these are not "keep it cheap" sessions.

**▶ THE KEYSTONE — assembly transform subsystem. DO THIS FIRST; it unblocks the other three.** The shared transform
engine — `_createAssemblyTransformContext` (~6785) / `_applyAssemblyPrimaryLive` / `_queueAssemblyPrimaryCommit` /
`_commitAssemblyPending` + the file-wide `_assemblyPendingTransforms` Maps, plus `_applyFKLive` (~6848) /
`_applyClusterMateFKLive` / `_analyzeMotionConstraints` (~6996) / `_setMotionChip` (~7083). Banners `// ── Rigid-body
group gizmo attachment` (~6773) / `// ── Forward kinematics` (~6840) / `// ── Motion-constraint analyzer` (~6996),
~400 ln. **These are the closure state that group_gizmo (#36/#37, ALREADY injects them as deps), the Move/Rotate `_mr*`
shell, AND the Translate/Rotate tool all share.** While they live in the closure, none of the three consumers can be
lifted cleanly. Extract → `scene/assembly_transform.js` factory exposing the context/live/commit API + owning the
pending Maps; the consumers then take it as a dep (group_gizmo already does — swap its injected fns for the module's).
Multi-commit split: **(a)** pending Maps + context/live/commit core; **(b)** FK propagation
(`_applyFKLive`/`_applyClusterMateFKLive` — was the standing "deferred" item, now part of this campaign); **(c)**
motion-constraint analyzer + status chip. Gate: the panel-input commit path (below) + `assembly_move_tool.spec.js`.
Re-derive exact spans with `rg` — the #36/#37 log already lists which helpers group_gizmo injects.

**Then, in dependency order (each easier once the keystone is a module — no more shared-state-via-closure):**
1. **Translate/Rotate tool + the `_mr*` panel shell** — banner `// ── Joint arrow pick handler` (~5252) through the
   cluster/instance gizmo attach (~6770), the BIGGEST single block (~700 ln + the `_mr*` shell). `_activateTranslateRotateTool`
   …`_cancelTranslateRotateTool` + `_onToolPickPointerDown` + the cluster raycaster (→ `scene/joint_pick.js`) + the `_mr*`
   shell it owns (`_mrSetTransformValues`/`_mrSetClusterOptions`/`_mrCommitInputs`/… + `_translateRotateActive`,
   read/written from 20+ sites). **Co-extract the shell here** — it's the natural pairing (Move/Rotate's flex sub-block
   already left in #71). Gesture-bound, assembly+design dual-mode. Much easier AFTER the keystone.
2. **Representation switcher** (~320 ln) — banners `// ── Unified representation radio` (~7851) + `_setRepresentation` +
   `// ── Function-key bindings: F1…F7` + the option sliders. Central mode-switch touching every renderer + the Coloring
   submenu (`_setColoringMode`'s 7 callers live here). Map the renderer fan-out; multi-commit.
3. **Atomistic/surface controllers (remainder)** — `_applyAtomisticMode`/`_applySurfaceMode`/`_refetchAtomistic`/
   `_ensureAtomData` + region overlays (~1893–2418). Pure colour cores already drained (#72). Interleaved with renderer
   construction — first separate the controller fns from the init wiring, then lift the controllers as a factory.

**Gesture gate is UNBLOCKED (commit 8e050e4) — build on it, don't re-derive.** Drive transform commits via the
Move/Rotate panel numeric inputs (`change` → `_mrCommitInputs` → `_queueAssemblyPrimaryCommit` → the SAME
`_assemblyPendingTransforms` map the gizmo onCommit feeds), NEVER a TransformControls handle drag (#36/#37 — handles
unhittable at pixel precision). Observables: `__nadocTest.getAssemblyPendingTransforms()` / `activateAssemblyMoveTool()`;
harness `scene_harness.activateAssemblyMoveTool` / `moveActiveInstanceViaPanel`; spec `e2e/assembly_move_tool.spec.js`.

**Banked:** `just lint` is Python-only ruff (38 pre-existing backend-test errors, unrelated; no frontend eslint config)
→ frontend lint delta is 0 by construction. Plain `grep` on main.js silently returns nothing (binary heuristic) — always
`rg`. Factory-init placement patterns (#52 deps-below-banner, #26/#32 lazy-let) are in `.claude/rules/main-init.md`.

**Deprioritized — do NOT spend a hardest-first session on these:** Tier 5 file/save is FULLY DRAINED (#52/#59/#60); the
menu-bar leftover is thin per-action wiring. The micro-scraps (Orbit submenu ~10 ln, Browser tab title ~5 ln, Coloring
submenu ~20 ln w/ 7 `_setColoringMode` callers, deform→selectableTypes ~28 ln, Sequencing menu #67) are correctly
inline — six logged mis-scopes prove the map's adjacency ≠ cohesion; a `ui/menu_misc.js` junk drawer is the anti-pattern.

**The goal is NOT a LOC number.** main.js is the composition root: 146 imports + ~100 module constructions + the
lifecycle spine + thin per-action wiring are *irreducible* (~2,500–3,500 ln floor). **Target: "the closure holds zero
cohesive logic clusters."** The four campaigns above ARE the remaining clusters — clear them and that target is met;
LOC lands ~3,000 as a *result*. Genuinely-permanent inline: `_setMenuToggle` (43-use shared util — a mechanical
import-swap, not a feature factory) and the lifecycle spine (`_resetForNewDesign`/`_enterAssemblyMode`/`_exitAssemblyMode`).

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
    - The **Create Seam** handler (HC/SQ scaffold-crossover lookup tables + Hamiltonian path) → **DONE**
      `scene/create_seam.js` (extraction #43, −259 ln). See "Smaller leftovers" + the log.
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
    - **Selection Filter toggles** (`#select-filter .sf-btn`) + the **drill-lock state machine**
      (`_manualFilters`/`_isManualSelect`/`_reflectDrillLevel`/`_reflectLockOnButtons`/`_resetToAutoBaseline`,
      `// ── Selection-filter mode` ~727) → **DONE TOGETHER** `ui/selection_filter.js`
      `initSelectionFilter({store, getSelectionManager})` + pure `computeFilterToggle` (extraction #61,
      commit 5e41c6b; −116 ln; 17 vitest; smoke 23/23 + real-app pin/un-pin exercise). **Carve-up was wrong
      that this is HARD/gesture-bound:** the extracted surface is pure DOM+store — the bead-click drill lives
      in selectionManager, which CALLS this module's `reflectDrillLevel`, so there's no canvas gesture to
      harness. `isManualSelect`/`reflectDrillLevel` injected into initSelectionManager;
      `reflectLockOnButtons`/`resetToAutoBaseline` into initKeyboardShortcuts; `selectionManager` (created
      AFTER the factory) reached via lazy getter; `attachFilterButtons()` keeps subscription order.
    - **Tool Filter toggles** (`#view-tools .sf-btn[data-key]`: blunt/crossover/overhang locations +
      the toolFilters→renderer-visibility subscriber) → **DONE** `ui/tool_filter_toggles.js`
      `initToolFilterToggles` (extraction #49, commit e514895; −34 ln; 11 vitest; smoke 21/21 + real-app
      vt-filter-button exercise). Self-contained; `overhangHoverPicker` injected as a lazy getter
      (created later in init order); the `bluntEnds` reaction stays in main.js (assembly blunt-end sync).
    - **View-menu pill-state subscriber** + 3 visibility helpers (`_syncAssemblyMenuVisibility` /
      `_syncImportMenuVisibility` / `_syncDeformMenuEnabled`) → **DONE** `ui/view_menu_pills.js`
      `initViewMenuPills` (extraction #51, commit pending; −39 ln; 11 vitest; smoke 21/21 + real-app
      View→Sequences pill-flip exercise). `_setMenuToggle` stays in main.js (43-use shared util), injected
      as `setMenuToggle` dep; the 3 helpers had zero external callers → fully self-contained lift.
    - The **deform→selectableTypes save/restore** subscriber and **Browser tab title** are still small
      independent blocks — pick off opportunistically, do not bundle. NOTE: `_setMenuToggle` (the pill
      toggler, 43 uses) is a shared-util lift, not a feature factory member.
- [~] **Coloring / orbit / tools submenus** — banners `// ── Tools menu (Bend / Twist)` (~5337) …
  `// ── Orbit mode submenu` (~5395) … `// ── Coloring submenu` (~5407–5618). **PREMISE MIS-SCOPED AGAIN
  (verified 2026-06-04, #42 — 5th time):** this is NOT one cohesive `ui/view_menus.js` subsystem; the banner
  lumps many tiny adjacent handlers around ONE big cohesive block. Breakdown:
    - **Background settings modal** (the meaty cohesive block, ~160 ln: `_backgroundState` +
      `_applyBackgroundStyle`/`_formatAqueousBackground`/`_syncBackgroundModal`/`_buildBackgroundModalOnce` +
      colour/hex/image/fit listeners + `menu-view-background`/`background-modal-aqueous`) → **DONE**
      `ui/background_modal.js` factory `initBackgroundModal()` + pure `computeBackgroundStyle(state)`
      (extraction #42, commit pending; −160 ln; 12 vitest; smoke 21/21 + real-app open/colour/aqueous
      exercise). Fully self-contained — zero store/scene/camera/designRenderer; only DOM + `createModal`/
      `createButton`. The handoff called the *Coloring submenu* "the meaty cohesive sub-block" — wrong, it's
      ~20 ln. The Background modal was the real payoff.
    - **Coloring submenu** (`_setColoringMode` + 6 click handlers, ~20 ln) — small AND `_setColoringMode` has
      **6 external call sites** (2292, 8876, 10750, 10775, 10776) → extracting needs a returned fn + lazy
      getters at those sites (more coupling than its 20 ln implies). Pairs with `scene/coloring_modes.js`. LOW
      payoff; defer or bundle with a coloring-state lift.
    - **Loop/Skip + MD-Seg legends** → **DONE** `ui/view_legends.js` `initViewLegends` (extraction #50,
      commit pending; −76 ln; 8 vitest; smoke 21/21 + real-app View-menu toggle exercise). One cohesive region
      (matched legend pair, both hidden together by `_resetForNewDesign` → exposed as `reset()`).
    - **Orbit submenu** (`_setOrbitMode` + 2 handlers, ~10 ln, self-contained) / **Tools Bend/Twist**
      (`_clusterDeformGuard` + twist/bend menu + 2 overhangs-manager wirings + view-axes) / the assorted view
      toggles (slice/unfold/cadnano/deform/helix-labels/debug/sequences) — each small independent blocks;
      pick off opportunistically, do NOT bundle into one module. Deps: store, designRenderer, DOM. Risk: LOW-MED.

## Tier 5 — file / session infra (central — extract carefully, late)

These touch boot/lifecycle. High blast radius; do after the loop is well-grooved.

- [x] **File open / save + assembly save** — banners `// ── File open / save` +
  `// ── Assembly file save helpers` (~3583–3815, ~340 ln) → `ui/file_io.js`. Deps: api, store,
  file overlay, multi-doc. Risk: HIGH. **FULLY DRAINED across #52/#59/#60.**
  - **file-IO operations — DONE** (extraction #52, this batch): `getDesignContent` / `savePartToAssembly` /
    `saveToHandle` / `saveAs` / `saveAssemblyToHandle` / `saveAssemblyAs` → `ui/file_io.js`
    `initFileIo({deps})`. −119 ln. Dropped dead `_pickOpenFile`. 19 vitest + smoke 21/21 + real-app Save-As
    exercise. Mutable file/path state + setters + `_updateAssemblyTitle` + the lifecycle spine STAY in main.js
    (get/set shims). Factory init placed at the autosave region head (~7660) where its late deps exist.
  - **open-file orchestration — DONE** (extraction #59): `_openPartFromServer` / `_openAssemblyFromServer`
    → `ui/file_io.js` SECOND factory `initFileOpen({…})→{openPartFromServer, openAssemblyFromServer}`
    (commit 4ddc029; −97 ln; 10 vitest, 654 total; smoke 23/23 + library-row open exercise). Kept a separate
    factory from initFileIo (disjoint deps: file-load overlay helpers + spine + assembly-load stash setters).
    `_fileOpen` forward-declared at the file-state block, assigned after the assembly-load stash vars (~7420).
    Verbatim bodies; spine + overlay helpers + assembly state injected; the 2 stash vars
    (`_assemblyLoadOnProgress`/`_assemblyLoadSettle`, read by the assembly rebuild subscriber) set via setter shims.
  - **save dispatchers — DONE** (extraction #60): `_saveDispatch` / `_saveAsDispatch` / `_saveAssembly` /
    `_saveAssemblyAsGuarded` → `ui/file_io.js` THIRD factory `initFileSave({…})→{saveDispatch, saveAsDispatch,
    saveAssembly, saveAssemblyAsGuarded}` (commit b6ea41d; −24 net; 16 vitest, 670 total; smoke 23/23 +
    menu-Save app exercise). Thin dispatch layer OVER `_fileIo`; routes by `assemblyActive`. Init placed after
    the last dep (`_exportRepActive` ~8727), `_fileSave` forward-declared `let = null`; the 2 menu listeners +
    the keyboard-shortcuts `saveAssemblyAsGuarded` injection reference it via lazy arrows (user-action only).
    `selfSavedPaths` by reference, `_exportRepActive`/file-path state via getters. The spine
    (`_resetForNewDesign` / `_enterAssemblyMode` / `_exitAssemblyMode`) stays inline (20+ sites).
- [~] **Menu bar + multi-document spawn** — banners `// ── Menu bar` + `// ── Multi-document: New / Open`.
  **PARTIALLY DRAINED (2026-06-05). NOT one `ui/menu_bar.js` module** — it's the "every menu action" wiring
  region: mostly thin 1–3 ln handlers over already-extracted modules + spine, with a couple of genuinely
  cohesive non-trivial blocks. Breakdown:
    - **New Part modal** (`_buildNewDesignModalOnce`/`_openNewDesignModal`/`_onCreateClicked` + `menu-file-new`)
      → **DONE** `ui/new_design_modal.js` `initNewDesignModal` + pure `sanitizeWorkspaceStem` (extraction #57,
      commit f9e7641; −77 ln; 14 vitest; smoke "New Part dialog" suite = the app exercise). First spine-coupled
      modal — spine + spawn-guard injected, libraryPanel lazy.
    - **Multi-doc spawn** (`_spaceHasContent` + `_spawnDocTabIfBusy`) → **DONE** `app/doc_spawn.js` pure
      `spaceHasContent(state)` + factory `initDocSpawn({store, mintDocId})→{spaceHasContent, spawnDocTabIfBusy}`
      (extraction #58, commit 705f0a7; −20 net; 12 vitest; smoke 23/23). Verbatim move; all 3 call sites
      (file-new injected dep / file-new-assembly / file-open) sit after the `const _docSpawn` init → no
      hoisting/lazy needed. `mintDocId` import stays in main.js (still used inline by the file-open handler).
    - The **save dispatchers** (`_saveDispatch`/`_saveAsDispatch`/`_saveAssembly`/`_saveAssemblyAsGuarded`) →
      **DONE** `ui/file_io.js` `initFileSave` (extraction #60, commit b6ea41d) — see the Tier-5 "File open /
      save" entry. The `menu-file-save`/`menu-file-save-as` listeners now call `_fileSave.*` via lazy arrows.
    - The rest (assembly-menu handlers, edit undo/redo, upload/download) are thin wiring over panels/api — low
      payoff, leave inline or bundle opportunistically.
- [x] **Connection monitor / autosave / SSE** — banners `// ── Backend connection monitor` …
  `// ── Library SSE` → `app/lifecycle.js`. Risk: HIGH (lifecycle). **FULLY DRAINED across #53/#54/#55**
  (conn monitor → `initConnectionMonitor`; sync badge → `ui/sync_badge.js`; autosave + SSE →
  `initAutosaveSync`). See the three sub-part entries below.
  - **Backend connection monitor + restart recovery — DONE** (extraction #53, commit 2346daf):
    `_restartHandling` + `_recoverAfterRestart` + `connectionMonitor.start({onChange})` →
    `app/lifecycle.js` `initConnectionMonitor({api, store, assemblyRenderer, setSyncStatus, syncLog,
    setReloadingFromSSE})→{recoverAfterRestart}`. −49 ln. 12 vitest; smoke 23/23. Seeds the module.
    The only leaked flag (`_reloadingFromSSE`) is injected as a `setReloadingFromSSE` shim. The Ctrl+Shift+D
    sync-debug shortcut stays inline (debug-panel concern). Removed dead `connectionMonitor` import from main.js.
  - **Sync status badge + debug panel — DONE** (extraction #54, commit 680f84f): `_setSyncStatus`/`_syncLog`
    + their DOM refs + the `sync-debug-close` listener + show/hide/toggle → `ui/sync_badge.js`
    `initSyncBadge()→{setSyncStatus, syncLog, show/hide/toggleDebugPanel}`. **NOT** part of `app/lifecycle.js`
    — these are pure-DOM presentation primitives with zero flag coupling, so they live in `ui/`, and the
    lifecycle consumers (conn monitor, autosave subscribers, file_io, SSE, import_menu) call them as deps.
    The flag-reading `window.__nadocSyncDebug` helper + the Ctrl+Shift+D toggle stay inline; the helper drives
    the panel via `_syncBadge.show/hideDebugPanel()`. −22 ln. 10 vitest; smoke 23/23 + real-app Ctrl+Shift+D.
    **This pre-extracts the badge primitives the autosave/SSE batch would otherwise have had to own** — that
    batch now just injects `_syncBadge.*`.
  - **Auto-save subscribers + Library SSE handler — DONE** (extraction #55, commit 55e25a7 + docs): both
    `subscribeSlice` writers (design + assembly) + `_scheduleLibraryRefresh`/`_handleLibraryEvent` +
    `api.subscribeLibraryEvents` → `app/lifecycle.js` factory `initAutosaveSync(deps)→{selfSavedPaths,
    setReloadingFromSSE, getReloadingFromSSE, getSavingAssembly, markSameDocActivity, handleLibraryEvent}`.
    The factory OWNS the four flags (`_savingAssembly`/`_reloadingFromSSE`/`_selfSavedPaths`/
    `_lastSameDocActivityMs`) + the four debounce timers + `_RELOAD_SUPPRESS_MS`. **`_selfSavedPaths` exposed
    by reference** so the 3 distant mutation sites keep mutating the SAME Set; the broadcast +
    connection-monitor flag writes route through `setReloadingFromSSE`/`markSameDocActivity` shims on a lazy
    `let _lifecycleSync` ref (forward-declared above the conn-monitor + `__nadocSyncDebug` so both reference it
    lazily). `_fileIo`/`_syncBadge`/`libraryPanel` are deps; `_assemblyRefresh` injected lazily
    (`getAssemblyRefresh: () => _assemblyRefresh`, wired just below) and in turn takes
    `selfSavedPaths: _lifecycleSync.selfSavedPaths`. **Placement:** factory call at the original
    design-subscriber spot (after `_fileIo`, ~7596) so subscription registration order is preserved.
    −129 ln off main.js. 14 vitest (fake-timer debounce: transient-skip / SSE-suppressed / design-save+
    broadcast+self-mark+5s-clear / part-edit→savePartToAssembly-900ms / assembly-save+latch / no-path-skip;
    SSE handler: ignore-non-file / self-echo-skip / debounced-refresh / assembly→coalesced / design-external-
    reload+flag-toggle / same-doc-window-suppress). vitest 601 + smoke 23/23 + running-app
    `__nadocSyncDebug.status()` lazy-wiring check. **Live autosave write-back gesture NOT hand-exercised**
    (needs a workspace-backed file + edit burst) — fake-timer units cover the debounce contract + the smoke
    console-error/teardown gates fire the subscriber registration, per #53/#52's accepted caveat.
    **This drains the Connection monitor / autosave / SSE region entirely → app/lifecycle.js now holds
    initConnectionMonitor + initAutosaveSync.**

## Tier 6 — dev-only / debug (no user risk; extract anytime to de-bloat)

Gated by `?debug` / `import.meta.env.DEV`. Safe to move (smoke still applies); good "warm-up" targets
for a fresh session.

- [x] **Extension arc debug tools** — banner `// ── Extension arc debug tools (dev only)`.
  **DELETED 2026-06-04 (commit aacc2c2), not extracted.** User-confirmed dead. The DEV-gated block
  defined `__extDebug`/`__xbDebug`/`__arcDebug`/`__extDebugWatch` (snapshot/diff console tools, ~424 ln);
  zero code or e2e references. `unfold_view.js` read `__extDebugWatch` only to wrap a console.log around
  an `applyUnfoldOffsetsExtensions()` call that ran identically in the `else` branch → collapsed to the
  bare call (behavior-identical) + dropped a stale `__arcDebug` doc comment. −424 ln off the closure.
- [x] **Browser dev-tools debug helpers** — `window._nadocDebug`. **DONE 2026-06-04 (extraction #48, commit
  5cffd9f).** The ~230-ln IIFE lifted verbatim into `scene/debug/devtools_helpers.js` factory
  `initDevtoolsDebug({designRenderer, store, api, overhangLinkArcs, selectionManager, scene})`; main.js does
  `window._nadocDebug = initDevtoolsDebug({...})`. Global kept intact, so photo-mode's `.photoMaterials`/etc
  attachments (~10025) and the e2e specs that drive `.snapPos`/`.refetch`/`.overhangLinkArcs` still work.
  13 vitest. −230 ln off the closure. **Gate caveat:** the 3 named e2e specs (`relax_undo_bug` /
  `dsdna_linker_selection` / `representation_order_fkeys`) are RED on the pre-change baseline (pre-existing,
  unrelated breakage — confirmed by stash-and-rerun), so they can't gate this; validated instead by smoke
  21/21 (the console-error gate exercises `_nadocDebug` creation) + vitest 516 + the baseline-identical e2e.
- [x] **Label / terminus audit** — banner `// ── Label / terminus audit` (~6213, ~190 ln) →
  `window.nadocLabelAudit`. **DELETED 2026-06-04 (commit 02f63c7), not extracted.** User-confirmed dead;
  no code or e2e references the post-caDNAno label/terminus audit. −190 ln off the closure. (The adjacent
  `nadocAssemblyLabelTable` console helper at ~6194 was left in place — separate banner, not in scope.)
- [x] **Help-menu debug toggles** — under banner `// ── Help / Hotkeys modal`. **RESOLVED BY DELETION
  2026-06-04 (commits 52cc166 + d3f54cf), not a factory extraction.** Want-it gate: user keeps only **FJC
  sim** (the read-only FJC linker-config modal — left inline, a 4-line lazy-import handler, not a factory
  target). Deleted the other three as dead: **OH Roots** (glow + `_logOvhgMapReport` 4-map cross-validation
  dump + the `_xval_*` cross-validation maps that only fed it), **Domain Ends** (glow + `_buildDomainEndEntries`),
  **Linker Anchor Debug** (init + own subscriber + 4 gated rebuild calls + `scene/linker_anchor_debug.js`
  module). **Why deletion not extraction:** the region was NOT a standalone subsystem — `_ovhgRootMap` /
  `_buildOvhgMaps` feed the live **Overhang Orientation panel** (`_ooOpen`, junction bead positions) and the
  glow-active state was read by an always-on subscriber, so a factory would have meant get/set shims across
  three distant locations. Deleting the dead toggles instead *simplified* the surviving infra (`_buildOvhgMaps`
  now builds just the 4 live maps). −133 ln off the closure. Gate: vitest 503 + smoke 21/21 (×2).

---

## Already-extracted (for reference — do NOT re-propose)

See `main_js_extraction_log.md` for the full list. Modules under `scene/` and `ui/`: bundle_geometry,
rotation_math, measurement_tool, scaffold_coverage, strand_length, overhang_maps, gear_math,
assembly_diff, design_queries (+flexibleRunForBead), cluster_joint_math, aksel_format,
assembly_groups_util, color_util (+hexFromInt, atomColorsFromLetters, computeAtomStrandColors), fret_util, vec_math, motion_chip,
scaffold_assign, atom_filter, selection_bbox, belt_rider, overhang_hover_picker, assembly_lasso,
coloring_modes, assembly_layout, ndc, flex_tethers, cluster_entries, empty_space_menu, slice_plane,
plate_view, kinematics_ticker, file_io (initFileIo save-content ops + initFileOpen open-orchestration),
app/lifecycle (connection monitor + autosave/SSE),
scaffold_modal (Assign Scaffold dialog + `countScaffoldNt` in scaffold_assign),
new_design_modal (New Part dialog + `sanitizeWorkspaceStem`),
app/doc_spawn (Multi-document spawn + pure `spaceHasContent`),
overhang_orientation_panel (Overhang Orientation panel + pure `buildOverhangRotationOps`; owns overhangGizmo),
autoscaffold_picker (Autoscaffold picker dialog + pure `autoscaffoldModeConfig`),
autobreak_modal (Autobreak/Aksel routing dialog + pure `readAkselOptions`).

## Smaller leftovers (after the tiers above)

Slice-plane wiring (`// ── Slice plane`, much already in `slice_plane.js`), Plates-and-tubes wiring
(most in `plate_view.js`), context-menu blocks (scaffold/overhang/blunt — `~3548–3817`), Photo-mode/export-repr wiring
(`~12214–12545`). Pick these up opportunistically once the tiers drain.

**Create Seam handler** — `menu-create-seam` click handler. **DONE** (extraction #43, this batch) →
`scene/create_seam.js`: pure `computeSeamPlacements(design)` (full coverage→adjacency→Hamiltonian-path→
junction pipeline) + exported pure helpers `isForward`/`scaffoldXoverNeighbor`/`nickBpForStrand` (latter two
parameterized on `isHC`) + thin `initCreateSeam({store, api})`. −259 ln off the closure. 17 vitest; smoke
21/21 + doc-pinned 26hb click exercise (place-batch POST, 10 placements). Dropped dead `helixByGridPos`. The
exported helpers + constants outlived the **Create Near/Far Ends** handlers (deleted 2026-06-04 as
superseded primitive routing — see the handoff above); create_seam.js stands on its own.

---

## Tier 7 — re-discovered cohesive subsystems (deep function-scan, 2026-06-05)

**Why this tier exists.** Tiers 1–6 were built from the `// ──` banner list. A 2026-06-05 function-by-function
scan (`grep -nE "^  (async )?function _?[a-zA-Z]" main.js`) found ~168 functions still inside `main()`, of which
the clusters below are **cohesive logic subsystems the banner tiers never named** — together ~2,500–3,000 ln of
genuinely-extractable code. This is the real remaining backlog. The earlier "near-complete" handoff was wrong.

**Same ⚠ rules apply (doubly here — these were sized from banner arithmetic, not read):** the line spans are
banner-to-next-banner estimates, NOT verified cohesion. RE-READ each region, re-derive its real scope/deps/risk,
run the want-it gate, and fix the entry on your way out. Ordered cleanest→hardest within each risk band.

### Clean dialogs/panels (do first — mirror the #42/#56/#57 modal lifts)

- [x] **Routing-warning dialogs** — banners `// ── caDNAno routing-change warning dialog` (~3987) +
  `// ── Routing feature-override warning` (~4049). **DELETED 2026-06-05 (commit e947b42), not extracted.**
  Want-it gate: `_confirmCadnanoRoutingChange` + `_confirmFeatureOverride` were **dead code** — their two
  call sites (auto-merge / prebreak routing guards from 1462c06) were removed by the cadnano overhaul
  (a6df304), which left the function bodies orphaned. Zero callers in src/ or e2e/ since. User-confirmed
  delete (mirrors #44/#45/#46). −131 ln off the closure. (Note: these were raw-DOM modals — `document.createElement`,
  NOT `createModal`/`createButton` — the map's dep guess was wrong, but moot since deleted.)
- [x] **CG Relax (mrdna) panel** — banner `// ── CG Relax (mrdna)` (~4047–4141, ~97 ln). **DELETED
  2026-06-05 (commit 685c72e), not extracted.** Want-it gate (#62/#46 pattern): the IIFE referenced
  `cgrelax-*` DOM ids that were **never added to index.html in any commit** — added in 907769e, the panel
  has been unreachable its entire life (every `getElementById` → null; all click handlers guarded with
  `?.` so none attach). Only the inert `initMrdnaRelaxClient` construction + a no-op store subscriber ran.
  User-confirmed delete; backend `/ws/mrdna-relax` route + `physics/mrdna_relax_client.js` left intact for
  later re-wiring. **Now-orphaned (left, inert):** `store.js` `cgRelaxPositions`/`cgRelaxStats` fields +
  their entry in the `physics` slice Set — nothing reads or writes them now; harmless dead state, a future
  store-cleanup scrap (touching the slice Set risks subscription behavior → left out of this commit's scope).
  −97 ln. Gate: vitest 687 (unchanged) + smoke 23/23.
- [x] **Overhang Orientation panel** — the `_oo*` cluster (`_ooOpen`/`_ooClose`/`_ooApply`/`_ooPreview*`/
  `_ooStepAxis`…) + angle fields + rotate-only TransformControls gizmo + the structural-change auto-close
  subscriber → `ui/overhang_orientation_panel.js` factory `initOverhangOrientationPanel` + pure
  `buildOverhangRotationOps` (delta-compose op builder). **DONE 2026-06-05 (extraction #64, commit 009df61).**
  REACHABILITY GATE PASSED: markup IS in index.html (`#overhang-orient-panel` etc.) and the feature is
  wanted (right-click overhang → "Edit Orientation"; feature-log edit of `overhang_rotation`; keyboard
  Delete/Escape). Cohesive block was lines 5001–5257 (~256 ln, matched the ~258 estimate for once). −245 ln
  off the closure. **Plain `const _orientPanel`** at the original spot (NOT lazy-let): all 4 external call
  sites — `_onEditFeature` (~1390), the context menu (~2898), and the keyboard_shortcuts deps
  `ooClose`/`getOoActiveIds` (~4748/4756) — fire post-boot, so they reference the const after its line runs
  (TDZ-safe, mirrors #34/#38/#50). `overhangGizmo` is fully internal to the panel (no external refs) →
  constructed inside the factory. `_ovhgRootMap` is mutable (rebuilt ~1822) → passed as `getOvhgRootMap`
  getter. `ovhgDomainIds`/`isExtrudeOverhang`/`initOverhangGizmo` imported directly in the module (removed
  now-dead from main.js — the `initOverhangGizmo` import line + 2 names off the design_queries destructure).
  15 vitest (5 pure: identity/compose-90°-Z/skip-missing/empty/null-design; 10 jsdom factory: open-single-
  label+attach / id-fallback+multi-count / close-hides+detach+clears / dirty-close-refetches-geometry /
  Apply-composes-ops+closes / Reset-zeroes-all / step-button-accumulates / Apply-no-active-no-op / auto-
  close-on-set-change / no-close-on-rotation-patch). Gate: vitest 702 + smoke 23/23 + real-app exercise
  (loaded NS_trans_fix = 50 overhangs → factory+subscriber+gizmo construct, zero console errors). **Live
  right-click→Edit-Orientation gesture NOT hand-driven** (needs picking one of 50 overhang beads) — the
  open/apply/reset/step/auto-close logic is covered by the 10 jsdom factory tests driving the REAL factory,
  per the #34/#32/#24 accepted caveat.
- [x] **Autoscaffold picker** — banner `// ── Routing: Autoscaffold (seamed / seamless picker)`. **DONE
  2026-06-05 (extraction #65, commit 20f6d0f)** → `ui/autoscaffold_picker.js` factory `initAutoscaffoldPicker
  ({store, api, setRoutingCheck})` + pure `autoscaffoldModeConfig` (radio value → progress copy + api method +
  fail label; lookup table verbatim-equivalent to the original if/else chain, unknown→seamed). **Re-derived
  scope: the map's "~212 ln" was the whole banner-to-next-banner span, NOT one cohesive block** — it's the
  picker IIFE (the cohesive ~67 ln, extracted) PLUS three unrelated handlers re-homed below: Auto Crossover
  (~9 ln, thin), Full Autostaple (~13 ln, thin), and the **Autobreak/Aksel modal IIFE** (~119 ln, cohesive →
  its own entry below). NO scaffold-router interleave (the map's MED-risk guess was wrong; it's a plain
  store+api+DOM dialog). −64 ln off main.js (9781→9717). REACHABILITY GATE PASSED (`#autoscaffold-modal` markup
  + `menu-routing-scaffold-ends` wired in index.html). `_showProgress`/`_hideProgress` were just aliases of
  `showOpProgress`/`hideOpProgress` → imported directly in the module; `_setRoutingCheck` (mutates closure
  `_routingChecks`) injected as `setRoutingCheck`. Plain `const`-import call at the original banner spot (deps
  all defined far above; no boot path calls a method synchronously). 10 vitest (3 pure + 7 jsdom factory:
  no-DOM / menu-guard+open / Run-no-design-guard / Run-dispatches+progress+routing-check / default-seamed /
  fail-toast / Cancel+backdrop-close). Gate: vitest 712 + smoke 23/23 + real-app exercise (scaffolded part →
  menu→modal→Run seamed→routing-check toggles on, zero console errors).
- [x] **Autobreak / Aksel modal** — the second IIFE under the Autoscaffold banner (`_runAutoBreak3d`/
  `_scoreAksel3d`/`_previewAksel3d`/`_readAkselOptions`/`_setAkselReport`/`_buildOnce` + indeterminate-progress
  animation + `menu-routing-autobreak`). **DONE 2026-06-05 (extraction #66, commit 2f816db)** →
  `ui/autobreak_modal.js` factory `initAutobreakModal({store, api})` + pure `readAkselOptions(raw)` (raw input
  strings → clamped backend opts; verbatim-equivalent to the original `_readAkselOptions` DOM reader: missing/
  non-finite → 21/60/3/0). Cohesive block was 4074–4192 (~119 ln, matched the estimate). −117 ln off main.js
  (9717→9600). REACHABILITY GATE PASSED (`#menu-routing-autobreak` + `#autobreak-modal-body` markup live in
  index.html; core routing feature, hotkey `3`). **Deps were only `store`+`api`** — `_showProgress`/`_hideProgress`
  were aliases of `showOpProgress`/`hideOpProgress` (imported directly, like #65); `showToast`/`createModal`/
  `createButton`/`formatScoreSummary`/`formatGraphSummary` imported directly too. Removed now-dead `aksel_format`
  import from main.js. Plain `const`-call at the original banner spot (deps far above; only the click listener
  attaches synchronously). 13 vitest (4 pure: defaults/parse/empty-fallback/mixed-clamp + 9 jsdom factory:
  no-throw/design-guard/build-open-once/Score-dispatch+report/Score-fail-report/Preview-progress+dispatch/
  Run-basic→addAutoBreak+close/Run-aksel→addAutoRouteAksel+toast/Run-fail-toast). Gate: vitest 725 + smoke 23/23
  + real-app hotkey-3 exercise (modal opens → Run Autobreak dispatches, zero console errors).
- [~] **Sequencing menu** — banner `// ── Sequencing` (~4077–4170), ~95 ln. **ASSESSED #67 (2026-06-05): LEAVE
  INLINE — it's a scrap.** The cohesive block (after the already-extracted `initScaffoldModal` #56) is 4 independent
  menu handlers (assign-staples / generate-overhangs / update-routing=Add-Loops/Skips / clear-all-loop-skips) +
  1 subscriber that enables/disables the update-routing button. Each handler is pure pass-through: guard → showProgress
  → `await api.X()` → toast. NO shared state, NO pure core, NO cohesive logic cluster — extracting to a factory of 4
  thin api-call handlers would be the pass-through-indirection anti-pattern the handoff warns against. The ONLY
  duplicated logic is the 3-line `hasCrossovers` computation (handler @~4124 + subscriber @~4166) — a candidate
  micro-dedup as `designHasCrossovers(design)` in `scene/design_queries.js` if ever touched, not worth a dedicated
  batch. Correctly inline; do not bundle.
- [x] **Highlight Undefined Bases** — banner `// ── Highlight Undefined Bases toggle` → `scene/undefined_highlight.js`.
  **DONE** (extraction #67, commit 7f8be3e) — pure `computeUndefinedEntries(design, backboneEntries)` (loop/skip-aware
  N detection + null-strand flag) + factory `initUndefinedHighlight({store, designRenderer, setMenuToggle})→
  {isOn,setOn,refresh}` owning the flag + menu button + design-change subscriber; −69 ln. The ownership transfer
  was clean: the two cross-region consumers (view_tool_buttons #41, scaffold_modal #56) now reach the shared flag
  via lazy arrows (`() => _undefinedHighlight.isOn()/refresh()/setOn(v)`), replacing the old get/set shims + direct
  fn ref — all TDZ-safe (user-action only). 15 vitest (8 pure + 7 jsdom factory); smoke 23/23; real-app vt-btn +
  menu-pill toggle exercise, zero console errors. **MED-risk "coordinate with #41's shims" overstated — the shims
  just became `_undefinedHighlight.*` arrows, a 1:1 swap.**
- [x] **Assembly context/linker menu + config animation** — FULLY RESOLVED (config anim #68 + router #69).
  RE-DERIVED #68 (2026-06-05): the "region" is THREE non-contiguous pieces, NOT one block — `_showAssemblyLinkerMenu` + `_onAssemblyContextMenu` (the
  right-click router) sit ~150 ln ABOVE `_animateAssemblyConfiguration`, separated by the clusterPanel +
  joints-panel inits. **Config animation EXTRACTED (#68, commit df158db)** → `scene/assembly_config_animator.js`
  (`initAssemblyConfigAnimator` + pure `easeInOutQuad`/`buildConfigAnimItems`), −42 ln, 13 tests. The map's
  "config-anim touches camera" was WRONG — it only drives `assemblyRenderer.setLiveTransform` +
  `assemblyJointRenderer.setLiveJointTransform` (no camera). **Re-homed leftover (the actual MED-HARD part):**
  the assembly right-click **context-menu router** (`_showAssemblyLinkerMenu` + `_onAssemblyContextMenu`, ~7374–7446,
  ~73 ln) — see its own entry below. The linker-menu is clean (store/api/createContextMenu/showToast) but the
  router has ~13 deps incl. mutable state (`_assemblyRightDownAt`, `_assemblySelectedPartJoint`) ALREADY shared
  with `initAssemblyPointer` (#? assembly_pointer.js) via get/set shims — extract it WITH or INTO assembly_pointer,
  not standalone.
- [x] **Assembly right-click context-menu router** — **DONE #69 (commit cc2d610, 2026-06-05):** folded
  `_showAssemblyLinkerMenu` + `_onAssemblyContextMenu` INTO `scene/assembly_pointer.js` as sub-part (c)
  (`onAssemblyContextMenu` + `showAssemblyLinkerMenu` internal fns; `onAssemblyContextMenu` added to the
  returned API; `const _onAssemblyContextMenu = _assemblyPointer.onAssemblyContextMenu` near the existing
  `_onAssemblyClick`/`_onAssemblyPointerDown` assigns, ~7290, so the deferred `contextmenu` listener at ~6700
  resolves it fine). 4 new deps (`assemblyContextMenu`, `overhangLocations`, `attachPartToBelt`,
  `getAssemblyRightDownAt`) + a `getAssemblyRightDownAt` shim alongside the existing `setAssemblyRightDownAt`;
  `createContextMenu` import MOVED into the module (was dead in main.js after, deleted). VERBATIM move,
  −72 ln (main.js 9489 → 9417). The folding-in (vs standalone) was right — reuses the pointer module's
  existing `_assemblyRightDownAt`/`_assemblySelectedPartJoint` shims, zero duplication. 9 new vitest branch
  tests (pan-suppress / overhang-bail / linker-relax+disabled / belt-attach / part-select / pending-commit /
  empty) via `vi.mock('../ui/primitives/context_menu.js')` to capture menu items + invoke onClick; vitest 762
  (+9); smoke 23/23. Live right-click NOT hand-driven (assembly+linker/belt multi-step setup) — accepted
  caveat per #64/#68, covered by the 9 branch tests + smoke assembly-exit listener teardown.

### HARD — gesture-bound or shared-state coupled (build the gate / map the coupling first)

- [~] **Move/Rotate right-sidebar panel** — banner `// ── Move/Rotate right-sidebar panel` (~4832).
  **PARTIAL: flexible-relax sub-block EXTRACTED → `scene/flex_relax.js` (#71, commit 9c18c3d), −147 ln**
  (`_flexGates`/`_flexConnections`/`_refreshFlexGates`/`_buildSsdnaPayload`/`_clusterBeadCount`/`_buildRelaxPayload`/
  `_relaxFlexible`; `_mrSetPivotOptions` now calls `_flexRelax.hasGate`). **STILL INLINE — the `_mr*` panel SHELL**
  (`_mrSetTransformValues`/`_mrSetClusterOptions`/`_mrSetPivotOptions`/`_mrSetSelectedPivot`/`_mrSyncClusterDropdown`/
  `_mrShowJointMode`/`_mrCommitInputs`/`_refreshClusterPivotForAttach` + the input/dropdown listeners + `_mrAssemblyCtx`).
  Risk on the shell: **HARD/lifecycle-spine** — the `_mr*` fns + `_translateRotateActive` are read/written from 20+
  sites and share `_createAssemblyTransformContext`/`_applyAssemblyPrimaryLive` with the group gizmo (#36/#37) + the
  Translate/Rotate tool. **Likely best LEFT inline** (STOP-criterion) unless co-extracted WITH the Translate/Rotate tool.
- [ ] **Representation switcher (hardest-first item 2)** — banners `// ── Unified representation radio` (~7851) +
  `_setRepresentation` + `// ── Function-key bindings: F1…F7` + `// ── Representation option sliders`, ~320 ln. Plus
  `_updateReprRadio`/`_syncAssemblyReprMenu`/`_cycleColoringForRepr`/`_updateColoringMenuAvailability`/`_reprOptionSliders`.
  Risk: **HARD** — `_setRepresentation` is a central mode-switch touching every renderer + the Coloring submenu
  (`_setColoringMode`'s 7 callers live here). Map the renderer fan-out carefully; multi-commit. (Re-verify line numbers
  with `rg` — these drifted −61 after #72.)
- [~] **Atomistic / surface display controllers (hardest-first item 3)** — `_applyAtomisticMode`/`_refetchAtomistic`/`_getAtom*`/
  `_ensureAtomData`/`_applySurfaceMode`/region overlays, scattered ~1893–2418 (interleaved with renderer init
  banners ~1846/1957/2342). Risk: **HARD** — interleaved with renderer construction; re-derive the function set
  vs the init wiring before lifting. **PURE CORE DRAINED (#72, commit a630efd):** `_getAtomStrandColors`'s
  colour-mapping body → `computeAtomStrandColors(state, staplePalette)` in `scene/color_util.js` (+`ATOM_STAPLE_PALETTE`);
  −61 ln; 9 vitest. `_getAtomBaseColors` left inline (already a 3-line pure-delegating wrapper over the
  extracted `atomColorsFromLetters` — not worth a module). The remaining controllers are the HARD stateful
  renderer-wiring (`_applyAtomisticMode`/`_applySurfaceMode`/`_refetchAtomistic`/`_ensureAtomData` + the region
  overlays), still interleaved with renderer construction.
- [ ] **Translate/Rotate tool + `_mr*` panel shell (hardest-first item 1, AFTER the keystone).**
  `_activateTranslateRotateTool` … `_cancelTranslateRotateTool` + the joint-arrow pick handler, banner
  `// ── Joint arrow pick handler` (~5252) through the cluster/instance gizmo attach (~6770), ~700 ln + the `_mr*` shell.
  `_onToolPickPointerDown` + cluster raycaster (the carve-up's `scene/joint_pick.js`) + the `_mr*` shell it owns
  (`_mrSetTransformValues`/`_mrCommitInputs`/… + `_translateRotateActive`, 20+ sites). Risk: **HARD** — gesture-bound
  (canvas pointer pick), assembly+design dual-mode. Gate is UNBLOCKED (commit 8e050e4 — drive via panel inputs, NOT
  handle drags; see the handoff). Much easier once the keystone engine is a module (no more shared-state-via-closure).
- [ ] **▶ KEYSTONE — Assembly transform/commit/FK + motion constraints (DO THIS FIRST per the handoff).** Banners
  `// ── Rigid-body group gizmo attachment` (~6773, attach itself partly in group_gizmo.js already) + `// ── Forward
  kinematics` (~6840) + `// ── Motion-constraint analyzer` (~6996) + status chip (~7083), ~400 ln.
  `_createAssemblyTransformContext` (~6785) / `_applyAssemblyPrimaryLive` / `_queueAssemblyPrimaryCommit` /
  `_commitAssemblyPending` + the file-wide `_assemblyPendingTransforms` Maps / `_applyFKLive` (~6848) /
  `_applyClusterMateFKLive` / `_analyzeMotionConstraints` / `_setMotionChip`. Risk: **HARD** — these are the SHARED
  transform engine that group_gizmo (#36/#37, **already injects them as deps**), the Move/Rotate `_mr*` shell, AND the
  Translate/Rotate tool all share via the closure. **REVISED ORDERING (was "extract only after consumers stable" — that
  was backwards):** extract the engine FIRST → `scene/assembly_transform.js` factory (owns the pending Maps, exposes
  context/live/commit). Once it's a module the three consumers stop sharing closure state and each becomes independently
  liftable. Multi-commit: (a) pending Maps + context/live/commit core; (b) FK propagation (no longer "deferred" — part of
  this campaign); (c) motion-constraint analyzer + chip. See the handoff for the full plan + gesture gate.
