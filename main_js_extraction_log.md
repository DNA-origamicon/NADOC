# main.js extraction log

Tracks the incremental decomposition of `frontend/src/main.js` (one ~16.5k-line `async function main()`
closure) via the **streamlined extraction loop** in `.claude/rules/main-init.md`. One row per extraction,
one commit per extraction.

**Why this exists:** the heavyweight `refactor_prompts/` ceremony stalled (sprint May 9–10, file
unchanged by Jun 2) because every frontend extraction cost a manual app-exercise to verify. The fast
vitest loop makes each step cheap; this log measures whether that's actually true, so we can make a
GO/NO-GO call on scaling before grinding through the whole file.

## Baselines (fill at start)

- `frontend/src/main.js` total LOC: 16530 (Jun 2 2026)
- vitest spec count: 4 (`src/**/*.test.js`); none cover main.js
- Backend test count: 1786

## Metrics per extraction

| # | Date | Tier | What (fn/cluster → module) | Wall-clock | main.js LOC Δ | vitest tests added | edits-to-green | manual app min | regression caught by |
|---|------|------|----------------------------|-----------|---------------|--------------------|----------------|----------------|----------------------|
| 1 | 2026-06-03 | EASY | `bundleAxisRange/bundleMaxOffset/bundleMidOffset` → `scene/bundle_geometry.js` | ~15 min | −16 (top-level; closure body unchanged) | 9 (3 fns → ratio 3.0) | 1 (green first run) | 0 (pure; console-error gate auto) | none — clean |
| 2 | 2026-06-03 | MEDIUM | `quatToEulerDeg/eulerDegToQuat/extractJointAngleDeg` → `scene/rotation_math.js` | ~12 min | −22 (inside closure — real shrink) | 8 (3 fns → ratio 2.7) | 1 (green first run) | 0 (pure; console-error gate auto) | none — manual-confirmed by user |
| 3 | 2026-06-03 | HARD | measurement tool (state + `_measClear/_measShow` + ctrl-bead subscription) → `scene/measurement_tool.js` (factory) | ~20 min | −32 (inside closure) | 7 (factory: show/clear/subscription/dispose) | 1 (green first run) | 0 — interactive gesture now automated (see below) | none in vitest + smoke 21/21 + gesture e2e 3/3 |
| 4 | 2026-06-03 | MEDIUM (dedup) | `intersectCoverage` (×3) + `findHamiltonianPath` (×2) → `scene/scaffold_coverage.js` | ~15 min | **−74 (inside closure; 5 copies → 1)** | 9 (intersect + Hamiltonian-path validity/null/startFrom) | 1 (green first run) | 0 (pure verbatim; identical names → 0 call-site edits) | none — vitest + boot gate; verbatim so router behavior preserved |
| 5 | 2026-06-03 | MEDIUM (dedup) | `_strandLength`/`_strandLen`/`_strandNt` → `scene/strand_length.js` (1 canonical + design wrapper + no-skip variant) | ~12 min | −29 (inside closure; 3 impls → 1 source) | 11 (no-skip / loop-skip / design-form equivalence / reversed / empty) | 1 (green first run) | 0 (verified `_strandLength`≡`_strandLen` loop-skip logic) | none — vitest + boot gate |
| 6 | 2026-06-03 | MEDIUM | 6 overhang-resolver builders (`buildSpecMap`/`…DomainMap…`/`…JunctionMap…`/`buildRootMap`) → `scene/overhang_maps.js` | ~18 min | **−86 (inside closure)** | 12 (each builder: resolve + skip/empty paths) | 1 (green first run) | 0 — boot gate loads a real design WITH overhangs, so `_buildOvhgMaps` runs all 6 → genuine integration check | none — vitest + boot gate (pipeline exercised on 26hb) |
| 7 | 2026-06-03 | MEDIUM | 5 revolute/gear math fns (`signedAngleFromWorldDelta`/`movingSideSignForRevolute`/`clampJointValue`/`gearEndpointSide`/`rotationDeltaMatrix`) → `scene/gear_math.js` | ~15 min | −42 (inside closure) | 12 (clamp/sign/endpoint/rotation-matrix/world-delta-angle) | 1 (green first run) | 0 (verbatim; gear paths are assembly-mode, not boot-exercised, but unit-tested + identical call args) | none — vitest + boot gate |
| 8 | 2026-06-03 | MEDIUM | 5 assembly snapshot-diff fns (`matrixFromInstance`/`sameInstanceTransform`/`assemblyTransformOnlyChange`/`summarizeConstraint`/`constraintRelevantChanged`) → `scene/assembly_diff.js` | ~16 min | −83 (inside closure) | 13 (matrix/equality/fast-path incl. visible-toggle + linker-topology + repr branches; DOF chips; constraint-change) | 1 (green first run) | 0 (verbatim; impure subscribers `_effectiveInstanceMatrix`/`_collectGroupMemberInstanceIds` stay) | none — vitest + boot gate |
| 9 | 2026-06-03 | MEDIUM | 5 pure design-graph lookups (`surfaceSegments`/`isExtrudeOverhang`/`ovhgDomainIds`/`flexAnchorKey`/`connIdForBead`) → `scene/design_queries.js` | ~20 min | −51 (inside closure; incl. dropping dead `_ovhgDomainBpRange`) | 11 | 1 (green first run) | 0 (verbatim) | none — vitest 125 + boot gate (after config fix) |
| 10 | 2026-06-03 | MEDIUM | `clusterTransformAfterJointDelta` → `scene/cluster_joint_math.js` | ~12 min | −21 (inside closure) | 3 (property: world-rotation-about-joint composition; zero-delta identity; field spread) | 1 (green first run) | 0 (verbatim) | none — vitest 128 |
| 11 | 2026-06-03 | MEDIUM | `formatScoreSummary` + `formatGraphSummary` → `scene/aksel_format.js` | ~8 min | −20 (inside closure) | 4 (populated + defaulted/n-a branches, each fn) | 1 (green first run) | 0 (verbatim) | none — vitest 132 |
| 12 | 2026-06-03 | MEDIUM | `computeGroupHiddenInstanceIds` → `scene/assembly_groups_util.js` | ~8 min | −18 (inside closure) | 6 (empty / hidden / visible-ignored / subgroup recursion / hidden-parent-wins / dangling subgroup) | 1 (green first run) | 0 (verbatim) | none — vitest 138 |
| 13 | 2026-06-03 | MEDIUM | `heatmapHex` (+ co-located `HEATMAP_MIN/MAX` consts) → `scene/color_util.js` | ~8 min | −10 (inside closure) | 4 (range; blue/red clamps; midpoint distinct) | 1 (green first run) | 0 (borderline → co-located the 2 consts, which only this fn used) | none — vitest 142 |
| 14 | 2026-06-03 | MEDIUM | `fretQuenchedDonors` → `scene/fret_util.js` (donor/r0 maps parameterized) | ~10 min | −16 (inside closure) | 5 (within/beyond r0; non-donor/no-mod ignored; lone donor; missing r0) | 1 (green first run) | 0 (borderline → parameterized the 2 maps; they stay in main.js, populated there) | none — vitest 147 |
| 15 | 2026-06-03 | MEDIUM (discovered) | `vecClose` → `scene/vec_math.js` | ~8 min | −2 (inside closure) | 5 (identical/eps/custom-eps/length-mismatch/empty) | 1 (green first run) | 0 (pure array math; first discovered-not-mapped extraction) | none — vitest 152 |

_(Between #15 and #16, several interactive batches ran post-autonomous-loop and were committed but NOT tabulated here: `ndc`/`flex_tethers`/`cluster_entries`/`empty_space_menu` (+ feature work on `assembly_lasso` Ctrl-click/Esc) and the dead `_onAssemblyClick`-branch removal. They took vitest 152→231. The rows below resume tabulation.)_

| 16 | 2026-06-03 | EASY (discovered) | `flexibleRunForBead` → `scene/design_queries.js` | ~10 min | −33 (top-level pure helper) | 5 (run/boundary/2× fallback/reverse-domain) | 1 | 0 (pure) | none — vitest 16/file |
| 17 | 2026-06-03 | EASY (dedup) | `hexFromInt` (2 inline copies) → `scene/color_util.js` | ~8 min | −5 net | 3 (format/zero-pad/mask negatives) | 1 | 0 (pure; masked impl == slice impl for valid colours) | none |
| 18 | 2026-06-03 | EASY (parameterize) | `atomColorsFromLetters` + `BASE_HEX` → `scene/color_util.js` (wrapper keeps store read) | ~7 min | −7 | 2 (keyed mapping / empty input) | 1 | 0 (pure core; store stays in wrapper) | none |
| 19 | 2026-06-03 | HARD (stateful) | loop-strand popup → `scene/loop_popup.js` factory `initLoopPopup` + pure `bestLoopNick` | ~35 min | −82 | 10 (4 nick-math + 6 factory: mount/show/suppress/non-loop/Nick/Leave) | 2 (jsdom didn't reflect `display` from cssText → explicit set) | manual: deferred (needs a circular-staple design) — caught by vitest+smoke | none — vitest 251, smoke 21/21 |
| — | 2026-06-03 | FEATURE REMOVAL | **#19 reverted**: loop_popup.js + test + `_ctrlHeld` deleted per user — the auto-nick "Nick here" popup was unwanted (its context menu was buried; users linearize circular staples manually). Warning highlight (loopStrandIds → red in 3D/cadnano) KEPT untouched. | ~10 min | −13 (popup wiring + _ctrlHeld) | −10 (test file deleted) | — | — | none — vitest 241, smoke 21/21 |
| 20 | 2026-06-03 | STATEFUL (Tier 1) | Strand length histogram IIFE → `ui/strand_length_histogram.js` factory `initStrandLengthHistogram` + pure `computeStrandLengthBins` | ~30 min | **−192 (inside closure; first stateful-subsystem extraction of the new tier)** | 13 (6 pure: status/binning/out-of-range/boundary/summary; 7 jsdom factory: no-DOM no-op/expand/collapse/bar-click-selects/subscription redraw-on-expand + no-redraw-when-collapsed) | 1 (green first run) | ~3 (real-app expand exercise via throwaway spec, then deleted) | none — vitest 253, smoke 21/21, real-app panel-expand zero-console-errors |
| 21 | 2026-06-03 | STATEFUL (Tier 1) | Overhang sequences panel IIFE → `ui/overhang_sequences_panel.js` factory `initOverhangSequencesPanel` + pure `liveOverhangs` / `selectedStrandIds` | ~40 min | **−224 (inside closure)** | 20 (9 pure: live/ghost/no-strand filter + 3-source selection union/dedupe; 11 jsdom factory: no-DOM no-op/collapse/expand/empty/slider→setScale/Gen-visibility/Set-patch-trim-upper/Bind-toggle/row-select/highlight-on-selection/design-rebuild) | 1 (green first run) | ~5 (app exercise via loadScaffoldedPart: expand+slider+collapse, then deleted) | none — vitest 273, smoke 21/21, real-app expand zero-console-errors |
| 22 | 2026-06-03 | STATEFUL (Tier 1) | Strand groups panel IIFE → `ui/strand_groups_panel.js` factory `initStrandGroupsPanel` + 4 pure cores (`effectiveStrandColors`/`groupStrandsByColor`/`trimGroupsRemovingStrands`/`selectableGroupStrandIds`) | ~35 min | **−192 (inside closure)** | 20 (12 pure: color-merge/override-precedence/color-bucketing+resolution-order/scaffold-exclude/trim-identity+removal/selectable-filter; 8 jsdom factory: no-DOM no-op/expand-rebuild/collapse-suppress/row-multiselect-live/New-seed/New-trims-old-group/From-colors-bucket/delete) | 2 (hexFromInt returns `#`-prefixed key → fixed 2 pure-test expectations) | ~4 (app exercise via loadScaffoldedPart: New×2 + inline rename + From-colors + delete + collapse, then deleted) | none — vitest 298, smoke 21/21, real-app zero-console-errors |
| 23 | 2026-06-03 | STATEFUL (dialog) | `_pickLattice` (New-Part lattice-type modal) → `ui/lattice_picker.js` `pickLattice()` | ~25 min | −50 (inside closure) | 7 (jsdom: mount+default-checked / Create→HONEYCOMB / select-Square→SQUARE / Cancel→null / Enter-accepts / Escape→null / border-highlight-on-change) | 2 (jsdom normalizes `cssText` so a `[style*=…]` selector is brittle → switched to `[tabindex]` box + parent overlay) | ~3 (real New-Part flow: library→file-browser Save→picker→Square→Create, then deleted) | none — vitest 305, smoke 21/21, real-app zero-console-errors. **Finding: `ui/library_panel.js` panel itself was already extracted (May 17); banner remainder is file-open orchestration → deferred to Tier 5.** |
| 24 | 2026-06-03 | STATEFUL (Tier 1) | Fluorescence + FRET Checker block → `scene/fret_checker.js` factory `initFretChecker` + pure `buildFretLookups` (FRET_PAIRS/FRET_QUENCHED_SCALE moved in) | ~30 min | −72 (inside closure) | 9 (3 pure: empty/null + donor-grouping+r0-keying + shipped-table shape; 6 jsdom factory: no-glow-pre-toggle / fluorescence-glows-emitters-only(quencher filtered) / fluorescence-off-clears / FRET-quench-scale-3 / refreshIfFret-gated-on-fretOn / geometry-reload-rebuild-when-on-not-off) | 2 (test entries needed THREE.Vector3 pos for `.distanceTo`, not arrays) | ~3 (real-app: toggle both View-menu modes + 600ms render-loop ticks, then deleted — glow not visually confirmed, no fluorophore design) | none — vitest 314, smoke 21/21, real-app zero-console-errors. Render-loop coupling solved with `refreshIfFret()`. Named `scene/` not map's `ui/fret_panel.js` (no panel DOM). |
| 25 | 2026-06-04 | STATEFUL (Tier 2) | Export menu (File→Export submenu) → `ui/export_menu.js` factory `initExportMenu({store, api})` + module fns `exportErrorMessage` (pure) / `triggerDownload` / `showNamdPromptModal` | ~35 min | **−215 (inside closure; first Tier-2 region)** | 16 (2 pure exportErrorMessage + triggerDownload + 2 showNamdPromptModal jsdom + 11 factory: no-DOM no-op / CSV-success / no-design-guard / failed-export-msg / xlsx-color-order-forward / PDB+PSF download-URLs / STL-success-toasts / 3MF-coloring-detail / GROMACS-stub-toast / dismiss-clears-class / NAMD-download+modal) | 1 (green first run) | ~4 (real-app: load scaffolded part → CSV download + PDB download + GROMACS toast via throwaway spec, then deleted) | none — vitest 342, smoke 21/21, real-app zero-console-errors. `showToast`/`docHeaders`/`getStapleColorOrder` imported directly (not deps); removed now-unused `getStapleColorOrder` from main.js spreadsheet import. GROMACS stays stubbed. |
| 26 | 2026-06-04 | STATEFUL (Tier 2) | Import menu + library callbacks (File→Import) → `ui/import_menu.js` factory `initImportMenu(deps)` + pure `sanitizeImportName` / `importedClusterOverhangExtras`; returns `{importCadnano/Scadnano…WithAutodetection, runPdbImport}` | ~50 min | **−210 (inside closure)** | 12 (3 sanitize + 2 extras + 7 factory: returns-callbacks/no-DOM no-op, PDB-menu→modal-wiring, runPdbImport null/needs-decision/dna+warnings/protein/both) | 1 (green first run) | ~6 (real-app throwaway: library-panel caDNAno button → lazy wrapper → filechooser; PDB menu → modal; then deleted) | none — vitest 354, smoke 21/21, real-app zero-console-errors. **Higher coupling than #25**: 13-dep factory (store/api/workspace/libraryPanel + 8 lifecycle callbacks incl. a `setFileHandle` for the mutable `_fileHandle` write). **Cross-file wiring gotcha:** the 2 autodetection callbacks were consumed at `initLibraryPanel` ~3000 ln earlier via function-hoisting → replaced with lazy `() => _importMenu?.…()` arrows + a `let _importMenu` declared before that init (mirrors existing `onOpenPart` arrow). Removed now-dead `openImportPdbModal` import from main.js. File-input flows (cadnano/scadnano) not jsdom-testable → verbatim + app exercise. |

| 27 | 2026-06-04 | STATEFUL (Tier 3) | Assembly pointer sub-part **(c) PartGroup click-through** → pure `resolveGroupClickThrough` in existing `scene/assembly_groups_util.js` | ~25 min | −10 (inside closure) | 7 (no-hit/ungrouped→none; first-click→selectGroup full-reset patch; switch-active-group→selectGroup; member-of-active→enterGroup pushes dive stack; existing-stack append; no-mutate-input) | 1 (green first run) | 0 (pure decision; scene pick + setState stay inline = verbatim patches; live group-click gesture unchanged) | none — vitest 361, smoke 21/21 |

| 28 | 2026-06-04 | DEDUP (Tier 3 sub-part a) | Part-joint drag `worldDelta` (inline `T(origin)·R·T(-origin)` in `_updatePartJointDrag`) → reuse existing tested `rotationDeltaMatrix` (gear_math, #7) | ~20 min | −7 (inside closure; 1 copy collapsed into the gear path's helper) | 0 new (reuses #7's 3 tests; mathematically identical) | 1 (green first run) | 0 (verbatim-equivalent matrix; smoke 21/21) | none — vitest 361, smoke 21/21 |
| 29 | 2026-06-04 | STATEFUL (Tier 3 sub-part b) | Assembly click handler `_onAssemblyClick` + single-use `_toggleAssemblyOverhangSelection` → `scene/assembly_pointer.js` factory `initAssemblyPointer({…})→{onAssemblyClick}` | ~55 min | **−122 (inside closure; broke the (a)/(b) coupling wall)** | 11 jsdom factory (non-left/belt-clears/no-ptrdown/drag-not-click/new-select+gizmo/empty-clears/reclick-picks-cluster/overhang-toggle/group-click-through-selectGroup/gizmo-leaves-active-body/gizmo-commits-elsewhere) | 1 (green first run) | 0 — `assembly_select.spec.js` (real raycast) IS the app exercise | none — vitest 372, `assembly_select.spec.js` 2/2, smoke 21/21 |
| 30 | 2026-06-04 | STATEFUL (Tier 3 sub-part a, step 1) | Assembly drag handlers `_updateFreeDragPosition`/`_updatePartJointDrag`/`_onAssemblyDragMove`/`_onAssemblyDragUp` + drag state (`_partJointDrag`/`_freeDrag`/`_pendingFreeDrag`) → `initAssemblyPointer` (module-internal state) + `beginPartJointDrag`/`cancelDrag` API | ~45 min | **−160 (inside closure)** | 5 jsdom (beginPartJointDrag-arms-listeners / dragUp-records-pending+re-enables-controls / dragUp-near-zero-no-record / cancelDrag-noop-when-idle / dragMove-noop-when-idle) | 1 (green first run) | 0 — `assembly_joint_drag.spec.js` (real pointer-down→drag→up) IS the app exercise | none — vitest 377, joint_drag+select 3/3, smoke 21/21. Removed orphaned `clusterTransformAfterJointDelta` import. |
| 31 | 2026-06-04 | STATEFUL (Tier 3 sub-part a, step 2 — COMPLETES the region) | `_onAssemblyPointerDown` → `initAssemblyPointer` `onAssemblyPointerDown`; `beginPartJointDrag` now an internal call | ~40 min | **−155 (inside closure)** | 6 jsdom (belt-bails / Priority-1-ring-drag / empty-records-ptrdown / lasso-consumes / right-down-records / active-part-joint-records+stopPropagation) | 1 (green first run) | 0 — `assembly_joint_drag.spec.js` drives the real pointer-down Priority-2b arm | none — vitest 383, joint_drag+select 3/3, smoke 21/21. Removed orphaned `makeRefVec`/`ringPlaneHit`/`angleInRing` imports (kept `computeRevoluteTransform`). |
| 32 | 2026-06-04 | STATEFUL (Tier 3 — Polymerize region, belt sub-part) | belt-polymerize helpers (`_beltCtxForRider`/`_beltFillInfo`/`_polymerizeBelt`) → `scene/belt_polymerize.js` factory `initBeltPolymerize` + pure `buildBeltPolymerizeCopies` | ~30 min | −34 (inside closure; +3 dead belt imports removed) | 10 (5 pure copy-builder: arc-spacing/world-pos/count-clamp/floor/wrap + 5 factory: no-ctx-null/fill-passes-bbox/no-ctx-error-toast-no-api/success-posts-copies/null-fail) | 1 (green first run) | belt gesture not hand-run (needs built belt assembly) — verbatim move + smoke boot gate (#24 caveat) | none — vitest 393, smoke 21/21. Confirmed WANTED (belt-path panel deps, not dbg-only). Lazy `let _beltPolymerize` mirrors #26's `_importMenu` (deps consumed ~1000 ln before factory init). |
| 33 | 2026-06-04 | DEBUG (Tier 3 — Polymerize region, kinematics-ticker wiring) | inline `window.nadocGearDebug` dump → `gearDebug()` method on existing `scene/kinematics_ticker.js`; main.js keeps the visibilitychange-flush + `__NADOC_KINEMATICS__` handle as thin DOM/window wiring; **de-interleaved** the mislabeled "Kinematics ticker" banner (blunt-end-sync + cluster-pick block now its own banner) | ~20 min | −19 (inside closure) | 3 (module's FIRST unit coverage: empty-dump shape / joint-summary-field-subset / log-tag+identical-return) | 1 (green first run) | 0 — debug-only console helper; verbatim dump move + smoke boot gate | none — vitest 396, smoke 21/21. Design call: DOM-listener registration stays at main-loop altitude (app-composition concern); the *data dump* moved into the module because it reads the ticker's internal `debugState`/gear graph. `kinematicsTicker.debugState?.() ?? null` → internal `debugState()` (always defined → behavior-identical). |
| 34 | 2026-06-04 | STATEFUL (Tier 3 — Multi-select visual feedback) | `_updateAssemblyMultiBox` (purple union BoxHelper) → `scene/assembly_multi_box.js` factory `initAssemblyMultiBox({scene,store,assemblyRenderer})→{update,dispose}` + pure `instanceUnionBox(centers,wanted)` added to existing `scene/selection_bbox.js` | ~30 min | −37 (inside closure; banner "~192 ln" was overshoot — cohesive block is one ~46 ln fn) | 14 (5 pure union-box: union-half-extents/ignore-unwanted/skip-sizeless/null-no-match/null-all-sizeless + 9 jsdom factory: empty-no-draw/single-multiselect-suppressed/≥2-draws-purple-Box3Helper/single-member-active-group-draws/transitive-subgroup-fold/dispose-prior-no-dupe/drop-below-2-clears/dispose-removes) | 1 (green first run) | 0 — see caveat | none — vitest 409, smoke 21/21. **Hoisting gotcha:** the two `.update()` call sites (the `subscribeSlice('assembly')` subscriber @~9770 + the group-gizmo onDrag RAF @~10270) PRECEDE the old `function _updateAssemblyMultiBox` def @~10600 (worked via hoisting). A `const` factory isn't hoisted → moved the init to right before the `subscribeSlice('assembly')` registration (scene/store/assemblyRenderer all defined by then) — cleaner than the #26/#32 lazy-let since a single contiguous earlier spot dominates both call sites. Pure core paired into `selection_bbox.js` (already the selection-AABB home) rather than a new module. **Live purple-box gesture NOT hand-exercised** (needs a built ≥2-part assembly + Ctrl-lasso multi-select; no such fixture) — verbatim move + unit-tested + smoke boot gate, per #32/#24's accepted caveat. |

| 35 | 2026-06-04 | STATEFUL (Tier 3 — Group gizmo region, sub-part a) | pure `revoluteCommitValue` (revolute gizmo-drag commit math) from `_revoluteGizmoCommitValue` → new `scene/group_gizmo.js` (seeds the module); main.js wrapper keeps the store-read + accumulator-clear | ~20 min | −5 (inside closure) | 7 (non-revolute→null / no-angle→null / wrong-joint→null / forward-side adds+endpoint-b / backward sideSign subtracts+endpoint-a / missing seed value→0 / clamp-to-limits) | 1 (green first run) | 0 — pure core; smoke run anyway given the region is the file's central transform hub | none — vitest 416, smoke 21/21. **De-risking first cut into the highest-coupling region.** (b)/(c) stateful gizmo-attach lifts NOT attempted — the gesture gate the handoff called "off-the-shelf" is **not** (no load-`.nass` harness helper, no group-select dev hook). Logged + handoff rewritten. |

| 36 | 2026-06-04 | STATEFUL (Tier 3 — Group gizmo region, sub-part b + shared engine) | gear-live revolute-drag engine (`applyGearLiveForRevoluteDrag` + `_applyGearLiveJointValue` + `_revoluteGizmoAngle` accumulator + revolute commit wrapper) **and** `attachGroupGizmo` (single-instance) → `initGroupGizmo` factory in `scene/group_gizmo.js` | ~55 min | **−208 (inside closure)** | 9 (factory: no-ctx chip+no-attach / anchored-detach / free-attach-at-centroid / revolute-attach-at-origin+rotate-constraint / onLive applies primary + pushes Move/Rotate / onCommit-non-revolute-queues; engine: gear-coupling drives child + commits angle / resetAngle / non-revolute no-op) | 1 (green first run) | 0 — `assembly_select` + `assembly_joint_drag` (real raycast) exercise the (b) attach path via the subscriber | none — vitest 425, smoke 21/21, assembly specs 3/3. Shared helpers stay in main.js as injected deps (`createAssemblyTransformContext`/`applyAssemblyPrimaryLive`/`queueAssemblyPrimaryCommit` — also used by Move/Rotate fields; pending-transform Maps — file-wide). Removed now-dead gear_math (whole line), `computeRevoluteTransform`, `beltCouplingRelations` imports. The still-in-main (c) path calls the engine via the factory API until lifted. |
| 37 | 2026-06-04 | STATEFUL (Tier 3 — Group gizmo region, sub-part c — COMPLETES region) | `_createGroupTransformContext` + `_attachGroupGizmoForGroup` (whole-group rigid-body drag) + live-box coalescing flag → `initGroupGizmo` factory | ~35 min | **−133 (inside closure)** | 4 (factory: empty-group detach+chip / onLive moves EVERY member as rigid body + refits multi-box (rAF stubbed sync) / free-group onCommit→transformGroup / revolute-group onCommit→patchAssemblyJoint) | 1 (green first run) | 0 — see caveat | none — vitest 429, smoke 21/21, assembly specs 3/3. Two new deps: `effectiveInstanceMatrix` + `updateAssemblyMultiBox` (lazy `() => _assemblyMultiBox.update()`, since the multi-box is built ~1900 ln AFTER the factory init). Removed now-dead `summarizeConstraint` import. **Whole-group TransformControls-handle drag NOT mouse-driven in e2e** (handles are impractical to hit at integer pixel precision) — per the #34/#32 caveat, covered by verbatim move + the captured-onLive/onCommit factory tests + smoke. **The gesture gate the prior handoff demanded turned out unnecessary for a verbatim lift**: capturing the callbacks the mock `instanceGizmo.attach` receives and invoking them is a stronger, deterministic check than a flaky 3D-handle drag. **Region done bar FK propagation (`_applyFKLive`, left separate by design).** |

| 38 | 2026-06-04 | STATEFUL (Tier 3 — Coalesced assembly part-refresh — COMPLETES Tier 3) | `_scheduleAssemblyPartRefresh` + `_runCoalescedAssemblyRefresh` + `_refreshAssemblyPartInstance` + 5 `_asmRefresh*` state vars → `scene/assembly_refresh.js` factory `initAssemblyRefresh(deps)→{requestRefresh, flush, dispose}` | ~30 min | **−83 (inside closure; banner "~200 ln" overshot — cohesive block is ~98 ln)** | 10 (fake-timer factory: inactive-no-op / no-id-no-op / burst→one-refresh / last-id-wins / full-pipeline+shared-source-sync(2 instances, 3rd different-path skipped) / empty-assembly-bails / mid-flight-queues-one-followup / dispose-cancels / flush-runs-now / throw-recovers-latch) | 1 (green first run) | 0 — see caveat | none — vitest 439, smoke 21/21. **No pure core** (debounce IS the behavior). First fake-timer specs in the suite: `vi.useFakeTimers()` + `await vi.advanceTimersByTimeAsync(250)`; a `deferred()` promise holds the refresh in-flight to hit the mid-flight-coalesce branch. **Placement:** real `const` init before `_handleLibraryEvent` def — both callers (SSE @9308, broadcast @13342) fire async post-init, so no lazy-let; only `clusterPanel` (wired ~1000 ln later) needs a lazy `getClusterPanel` getter. `selfSavedPaths` passed by reference (Set). dispose/flush additive (unused by main.js; exit cleanup NOT wired to dispose — a pending timer surviving exit still no-ops via the `assemblyActive` guard, so exit behavior is verbatim). **Live coalesced-refresh gesture NOT hand-exercised** (needs a built multi-part assembly + part-editor save burst) — fake-timer units cover the exact debounce/coalesce contract, per #34/#32/#24 caveat. Updated 2 stale comments in main.js (`_refreshAssemblyPartInstance` → `_assemblyRefresh`). |

| 39 | 2026-06-04 | STATEFUL (Tier 4 — Keyboard shortcuts, Group 1) | view/tool toggles + number hotkeys (u/k/Tab/q/Shift+D/v/1–6/`/f/m/b/c/o) `registerShortcut` calls → `ui/keyboard_shortcuts.js` factory `initKeyboardShortcuts({deps})` | ~40 min | **−~210 (inside closure)** | 13 (jsdom synthetic-keydown via real `dispatchKeyEvent`: u/k toggle, blockedInInput, Tab cycle+wrap+blockedWhen, q gating, v pose-count, Shift+D dump, number-hotkey click+disabled, ` debug pill+store, f frame, m show/clear/unfold-suppress, b/c/o toolFilters+noRepeat) | 1 (green first run) | ~3 (real-app: ` toggles debug menu pill; f/q/b fire clean, then deleted) | none — vitest 452, smoke 21/21. **Map premise STALE:** region was already per-shortcut `registerShortcut()` into `input/shortcuts.js`, not a monolithic handler → real work is the factory lift, not table extraction. Added `clearShortcuts()` to shortcuts.js for test isolation (registry is a module singleton). Test events are PLAIN objects (`{key,ctrlKey,…,target:{tagName},preventDefault}`) — a real off-document `KeyboardEvent` has `target:null` and throws in the matcher. `_TAB_LOCKS`/`_LOCK_LABEL` moved into the module. Live `_translateRotateActive` via `() => …` getter (mirrors the existing inline `blockedWhen` arrow). |
| 40 | 2026-06-04 | STATEFUL (Tier 4 — Keyboard shortcuts, Group 2 — COMPLETES region) | Ctrl-modifier file/edit (Ctrl+O/S/Shift+S, Ctrl+Z/Y/Shift+Z) + Delete + Escape + the document `keydown` listener → `initKeyboardShortcuts` | ~35 min | **−~282 (inside closure; region total −492)** | 9 (Ctrl+O click, Ctrl+S 3-way route, Ctrl+S saveAs(path), Ctrl+Shift+S, Ctrl+Z undo/blocked/group-undo/assembly, Ctrl+Y/Shift+Z redo, Delete multi-oh/strand/no-op, Escape priority chain) | 1 (green first run) | ~2 (real-app: factory-attached listener toggles debug pill; Ctrl+Z+Escape clean, then deleted) | none — vitest 461, smoke 21/21. Listener now attaches from the factory; dropped now-unused `dispatchKeyEvent` import (registerShortcut stays — 4 OTHER call sites at 8735/9180/11029/11513 are out of scope). Mutable closure state via getters: `getPartEditContext`/`getAssemblyWorkspacePath`/`getOoActiveIds`/`isTranslateRotateActive`. **Gate gotcha:** `just smoke`'s Ctrl+K/Escape go through `initCommandPalette`, NOT this registry — so smoke can't prove the (now single-point-of-failure) listener attached; the app exercise MUST press one of THIS module's keys (` → debug pill). |
| 41 | 2026-06-04 | STATEFUL (Tier 4 — View tool buttons) | the `.vt-btn` right-panel row (length heatmap / sequences / undefined-bases / grid / overhang names / expanded / deform / unfold / cadnano2d) + its local length-heatmap & grid state → `ui/view_tool_buttons.js` factory `initViewToolButtons(deps)` + pure `buildLengthHeatmapColors(strands)` | ~35 min | **−113 (inside closure)** | 13 (3 pure: scaffold-skip+short→blue/long→red keying / null+empty / domainless→blue-floor; 10 jsdom factory: grid-added-to-scene+API / no-DOM no-throw / lengthHeatmap colours-then-reverts+legend / sequences store+pill / undefinedBases on-refresh→off-clear / grid visibility-on-button / overhangNames store+pill / expanded+deform+unfold+cadnano delegate / store-change re-syncs active classes / design-change re-applies heatmap when on not off) | 1 (green first run) | ~1 (real-app throwaway: load scaffolded part → click all vt-btns, legend+grid classes assert, zero console errors, then deleted) | none — vitest 474, smoke 21/21. **Mis-scoped parent region** (see note below). `_setMenuToggle` (43 uses) injected, NOT moved (shared util). Shared `_undefinedHighlightOn` (a `let` declared ~250 ln *below* the init point) reached via get/set shim arrows — TDZ-safe because invoked only from deferred click handlers. `_refreshUndefinedHighlight`/`_setMenuToggle`/`_toggle{Deform,Unfold,Cadnano}` are hoisted fn decls → injected directly. Pure core `buildLengthHeatmapColors` imports heatmapHex+strandDomainNt; removed both now-dead from main.js's imports. |

| 42 | 2026-06-04 | STATEFUL (Tier 4 — Background settings modal) | Background modal block (`_backgroundState` + `_applyBackgroundStyle`/`_formatAqueousBackground`/`_syncBackgroundModal`/`_buildBackgroundModalOnce` + colour/hex/image/fit listeners + `menu-view-background`/`background-modal-aqueous`) → `ui/background_modal.js` factory `initBackgroundModal()` + pure `computeBackgroundStyle(state)` | ~30 min | **−160 (inside closure)** | 12 (5 pure computeBackgroundStyle: solid-colour→size-null + image-cover + stretch→100%100% + image-without-url-falls-to-colour + aqueous-gradient/teal; 7 jsdom factory: default-style-on-init / colour-input→container+hex-mirror / hex-valid-only / aqueous-button→gradient / image-fit-reapplies-only-in-image-mode / menu-lazy-builds-modal-once+open / Reset-button-restores-defaults) | 1 (green first run) | ~1 (real-app throwaway: open modal → set colour → apply aqueous, container style + zero console errors, then deleted) | none — vitest 486, smoke 21/21, real-app zero-console-errors. **Cleanest factory in a while: zero store/scene/camera/designRenderer coupling** — only DOM + `createModal`/`createButton` (imported directly, not deps). Pure core preserves the verbatim quirk that solid-colour mode leaves `backgroundSize` untouched (`backgroundSize: null` → factory skips the assign). createModal/createButton stay imported in main.js (still used by the New-Part modal ~4294). **Mis-scope (5th time):** the carve-up's "Coloring submenu is the meaty sub-block" was wrong — Coloring is ~20 ln with 6 external `_setColoringMode` callers; the Background modal was the real ~160 ln cohesive payoff under that banner. jsdom `<select>` with no `<option>` ignores `.value` → the image-fit test appends an option first. |

| 43 | 2026-06-04 | STATEFUL (Tier 1 leftover — Create Seam) | `menu-create-seam` click handler → `scene/create_seam.js`: pure `computeSeamPlacements(design)` + exported `isForward`/`scaffoldXoverNeighbor`/`nickBpForStrand` (parameterized on `isHC`) + thin `initCreateSeam({store, api})` | ~70 min | **−259 (inside closure; biggest single-region drain so far)** | 17 (2 isForward + 4 scaffoldXoverNeighbor HC/SQ/wrap/null + 3 nickBpForStrand bow-right/HC + 5 computeSeamPlacements: null→[]/`<4`-helices→[]/4-col-SQ→2-placements-exact-bp-34/35/staple-ignored + 3 factory: no-design/no-placement/posts-batch) | 2 (1 SQ bow-right oracle wrong — mod 2 ∉ SQ set, used mod 3) | ~10 (doc-pinned 26hb click exercise: real menu click → place-batch POST 10 placements, 0 console errors) | none — vitest 503, smoke 21/21, doc-pinned click exercise green |
| 44 | 2026-06-04 | DELETE (Tier 6 — dead debug) | `window.nadocLabelAudit` (terminus audit console helper) → **deleted, not extracted** (commit 02f63c7) | ~10 min | **−190 (inside closure; deletion)** | 0 (deletion — no test surface) | 1 (vitest green, no spec referenced it) | 0 (dev-only console fn; smoke boot gate) | none — vitest 503, smoke 21/21. User-confirmed dead via want-it gate; zero src/e2e refs. |
| 45 | 2026-06-04 | DELETE (Tier 6 — dead debug) | `__extDebug`/`__xbDebug`/`__arcDebug` DEV block (ext-arc snapshot/diff) → **deleted, not extracted** (commit aacc2c2) + collapsed orphaned `__extDebugWatch` log-wrapper in `unfold_view.js` to bare `applyUnfoldOffsetsExtensions()` | ~15 min | **−424 (inside closure; deletion)** | 0 (deletion) | 1 (green first run) | 0 (dev-only; unfold collapse behavior-identical, smoke boot gate) | none — vitest 503, smoke 21/21. User-confirmed dead; zero src/e2e refs. unfold_view both branches called the same fn → collapse is verbatim-equivalent. |
| 46 | 2026-06-04 | DELETE (Tier 6 — Help-menu debug toggles, OH Roots + Domain Ends) | OH Roots glow + `_logOvhgMapReport` + Domain Ends glow + the report-only `_xval_*` maps → **deleted** (commit 52cc166); `_buildOvhgMaps` simplified to the 4 live maps | ~25 min | **−~120 (inside closure; deletion)** | 0 (deletion) | 1 (green first run) | 0 (smoke boots a design → fires `_buildOvhgMaps` subscriber feeding the OO panel, zero errors) | none — vitest 503, smoke 21/21. Want-it gate (user kept only FJC sim). `_ovhgRootMap` still feeds the live Overhang Orientation panel — that path unchanged; deletion *simplified* shared infra rather than coupling a factory to it. |
| 47 | 2026-06-04 | DELETE (Tier 6 — Help-menu debug toggles, Linker Anchor Debug) | `initLinkerAnchorDebug` overlay: init + own subscriber + 4 gated rebuild calls + handler + `scene/linker_anchor_debug.js` module → **deleted** (commit d3f54cf) | ~15 min | **−~13 (inside closure; deletion) + module file** | 0 (deletion) | 1 (green first run) | 0 (smoke exercises the design-rebuild overlay paths the 4 calls lived in) | none — vitest 503, smoke 21/21. All 4 `if (isVisible()) rebuild()` calls were no-ops once the toggle was gone (isVisible only true via the deleted toggle). No other importers of the module. |
| 48 | 2026-06-04 | STATEFUL (Tier 6 — devtools_helpers, COMPLETES Tier 6) | `window._nadocDebug` IIFE (posTrace/snapPos/diffPos/storeTrace/subTrace/linkers/forceRebuild/refetch/help + test handles) → `scene/debug/devtools_helpers.js` factory `initDevtoolsDebug({designRenderer, store, api, overhangLinkArcs, selectionManager, scene})` (commit 5cffd9f) | ~45 min | **−230 (inside closure)** | 13 (diffPos pure: threshold/missing-in-B/custom + snapPos __-skip + linkers no-design/orphan/clean + refetch ordering + forceRebuild fresh-ref/no-geom-warn + storeTrace patch+restore + posTrace wrap+restore + factory shape) | 2 (storeTrace/posTrace restore a `.bind()` copy not the literal ref — fixed the 2 oracles to assert functional restoration, not `toBe`) | 0 — see caveat | none — vitest 516, smoke 21/21. Verbatim IIFE→factory; `window._nadocDebug` global kept intact so photo-mode `.photoMaterials` attach (~10025) + e2e `.snapPos`/`.refetch`/`.overhangLinkArcs` unaffected. **e2e-gate caveat below.** |
| 49 | 2026-06-04 | STATEFUL (Tier 4 — Tool Filter toggles) | `#view-tools .sf-btn[data-key]` button row (blunt/crossover/overhang locations) + toolFilters→renderer-visibility subscriber → `ui/tool_filter_toggles.js` factory `initToolFilterToggles(deps)` (commit e514895) | ~25 min | **−34 (inside closure)** | 11 jsdom factory (no-DOM no-op / button-flip / .active-reflect / unchanged-ref early-return / crossover-on→rebuild+unfold-reapply / crossover-on→cadnano-reapply / crossover-off-no-rebuild / overhang-on→rebuild / overhang-off+assembly→hover-reset / overhang-off-no-assembly→no-reset / extensionLocations→setExtensionsVisible) | 1 (green first run) | ~2 (real-app throwaway: load scaffolded part → click xloc/ovhg buttons → .active toggles + overlays rebuild, zero console errors, then deleted) | none — vitest 527, smoke 21/21. **`overhangHoverPicker` injected as a lazy getter** — it's created at ~8942, far AFTER the call site (~5343); a direct pass would capture `undefined`. The `bluntEnds` button is in this block but its reaction lives in the assembly blunt-end-sync region (~6606); button only does `setState({toolFilters})` so moving just the button is verbatim. No `_setMenuToggle` dependency (this block toggles `.active`, not menu pills). |

| 50 | 2026-06-04 | STATEFUL (Tier 4 — View legends) | Loop/Skip + MD-Segmentation legend overlays + their View-menu toggle handlers → `ui/view_legends.js` factory `initViewLegends({store, loopSkipHighlight, mdSegmentation, setMenuToggle})→{reset, loopSkipLegend, mdSegLegend}` | ~30 min | **−76 (inside closure)** | 8 jsdom factory (construct: 2 hidden legends appended + distinct content + md-detail slot / no-menu no-throw; loop-skip on: show+setVisible+pill+rebuild-with-geometry / off: hide+no-rebuild; md-seg on: show+pill+detail-line / off: hide+detail-untouched / on-no-design: show+skip-detail; reset: hides both+clears both pills+mdSegmentation.hide) | 2 (reset-test setup bug: `makeLoopSkip(true)` made the first click *close* it → fixed to false so click opens) | ~1 (real-app throwaway: load scaffolded part → View-menu toggle both legends on/off, MD detail populates, zero console errors, then deleted) | none — vitest 535, smoke 21/21, real-app zero-console-errors. **One cohesive region** (matched legend pair: both toggle a highlight/overlay module + show/hide a legend; `_resetForNewDesign` hid both via a 5-line block → exposed as `reset()`, called verbatim from main.js). No pure core (all DOM/state). `computeSegments` imported directly (pure, co-located) → not a dep; dropped its now-dead `_computeMdSegments` import alias from main.js. Plain `const` at the original block line (~5160) — TDZ-safe because every `_resetForNewDesign()` caller is deferred (mirrors #38). `setMenuToggle` (`_setMenuToggle`, a hoisted fn decl ~100 ln below) passed directly. |

| 51 | 2026-06-04 | STATEFUL (Tier 4 — View-menu pill state) | pill-state `store.subscribe` + 3 visibility helpers (`_syncAssemblyMenuVisibility`/`_syncImportMenuVisibility`/`_syncDeformMenuEnabled`) + initial sync call → `ui/view_menu_pills.js` factory `initViewMenuPills({store, setMenuToggle})` | ~25 min | **−39 (inside closure)** | 11 jsdom factory (initial-import-sync design→hidden / no-design→shown / assembly-on swaps Tools↔Assembly+hides view-toggles+re-syncs-import / assembly-off restores / currentDesign re-syncs / unfold pills+greys-deform / cadnano pills+greys-deform / deform un-greys when both off / 4 store-pills call setMenuToggle id+val / unfold-deactivate-resets-mode-indicator / unrelated-field no-op) | 1 (green first run) | ~1 (real-app throwaway: load scaffolded part → View→Sequences click flips is-on on/off, zero console errors, then deleted) | none — vitest 546, smoke 21/21, real-app zero-console-errors. **`_setMenuToggle` (43 uses) stays in main.js, injected as `setMenuToggle` dep** (NOT moved — physically inside the region but a shared util). The 3 helpers had ZERO external callers (grep-verified) → fully self-contained. Factory call placed at the subscriber's original line → subscription registration order preserved. No optional chaining in `_syncAssemblyMenuVisibility` → test mounts all 5 menu ids or it throws. Per "do not bundle" guidance, left Browser tab title + deform→selectableTypes as separate future picks. |

| 52 | 2026-06-04 | STATEFUL (Tier 5 — File open / save, file-IO ops sub-part) | file-IO operations (`_getDesignContent`/`_savePartToAssembly`/`_saveToHandle`/`_saveAs`/`_saveAssemblyToHandle`/`_saveAssemblyAs`) → `ui/file_io.js` factory `initFileIo({deps})`; dropped dead `_pickOpenFile` | ~50 min | **−119 (inside closure; first Tier-5 region)** | 19 jsdom factory (getDesignContent ok/non-ok; saveToHandle write/read-fail/write-throw; saveAs no-design/cancel/success-sets-state/stem-from-path/fail-red; saveAssemblyToHandle write/read-fail; saveAssemblyAs success/cancel/name-fallback; savePartToAssembly no-ctx/patch+broadcast+green/non-silent-mode-label/patch-fail-red) | 1 (green first run) | ~3 (real-app throwaway: load part → menu Save As → `_fileIo.saveAs` opens file-browser modal, zero console errors, then deleted) | none — vitest 565, smoke 21/21, real-app Save-As zero-console-errors. **First Tier-5 lift.** Wide-but-shallow (16 deps incl. 3 setters + 3 getters + 3 state-write shims), every op moved verbatim. **Placement gotcha (banked):** `initFileIo` needs late deps (`_setSyncStatus`/`_syncLog`/`libraryPanel` declared ~7500-7600), so the `const _fileIo` init lives at the autosave-region head (~7660), NOT at the "File open / save" banner (~3580). Verified no boot path *calls* a `_fileIo.*` method synchronously during `main()` — every call site (menu dispatchers, command palette, import menu, autosave subscriber) runs lazily/post-init. Command-palette ref (captured BEFORE init @~5360) → lazy `(opts) => _fileIo.savePartToAssembly(opts)`; import-menu ref (AFTER init @~9710) → direct `_fileIo.saveAs`. **Kept `_updateAssemblyTitle` in main.js** (3 lines, invoked by the boot-callable spine `_enterAssemblyMode`) → injected as a dep, dodging a TDZ/boot-order hazard. Mutable file/path state (6 vars) + setters + lifecycle spine (`_resetForNewDesign`/`_enterAssemblyMode`/`_exitAssemblyMode`) stay inline. `openFileBrowser`/`showToast`/`nadocBroadcast`/`docHeaders` imported directly in the module (not deps). Real Save-As dialog can't be jsdom-driven (file-browser modal) → the success path is unit-tested, the wiring/boot-order is e2e-tested (the throwaway proves `_fileIo.saveAs` runs through the real late-init binding). |

| 53 | 2026-06-04 | STATEFUL (Tier 5 — Connection monitor / autosave / SSE, connection-monitor sub-part) | backend connection monitor + restart recovery (`_restartHandling` + `_recoverAfterRestart` + `connectionMonitor.start({onChange})`) → new `app/lifecycle.js` factory `initConnectionMonitor(deps)→{recoverAfterRestart}` | ~35 min | **−49 (inside closure; +1/−1 import swap)** | 12 (factory shape+start-registers-onChange; onChange disconnected→red / reconnected→green / restarted→recover-then-green / re-entrancy-guard-via-deferred-getDesign; recoverAfterRestart: assembly-mode-rebuild-ignores-design_loaded / design_loaded-passive-repull-wrapped-in-flag / flag-cleared-on-throw / no-cache-noop / cache+confirm-imports / cache+decline-noop / watermark-reset-first) | 1 (green first run) | 0 — see caveat | none — vitest 577, smoke 23/23. **Seeds `app/lifecycle.js`** (first cut; autosave + SSE fold in later as ONE flag-owning batch). Split from the region the carve-up bills as one `app/lifecycle.js` because the autosave/SSE flags (`_reloadingFromSSE`/`_savingAssembly`/`_selfSavedPaths`/`_lastSameDocActivityMs`) are written in 3 sites OUTSIDE the region (save dispatch ~3995, ~6836, broadcast handler ~10625-10682) → a wide get/set-shim job; the connection monitor leaks only ONE flag (`_reloadingFromSSE`) and owns its own `_restartHandling`. `connectionMonitor` is the imported `shared/connection_monitor.js` poller → imported directly in the module (not a dep); removed its now-dead namespace import from main.js. Ctrl+Shift+D sync-debug shortcut left inline (debug-panel concern). **Restart-recovery gesture NOT hand-exercised** (needs a live backend kill+restart mid-session) — branches unit-tested via mocked deps, boot/start path covered by smoke, per #38/#32/#24 caveat. |

**Connection monitor — TDZ-safe forward flag ref; cohesive sub-block of a flag-tangled region (#53, 2026-06-04).**
First cut into the connection/autosave/SSE region → seeded `app/lifecycle.js`. The carve-up bills the whole region
as one `app/lifecycle.js`, but the autosave + SSE blocks share four loop-prevention flags that are *also* written
from 3 distant sites (save-dispatch ~3995, a part-save echo ~6836, the cross-tab broadcast handler ~10625-10682),
so lifting them means the module must own the flags and expose get/setters (+ the `_selfSavedPaths` Set by
reference) — a wide-shim batch best done all-at-once (splitting the flags risks save-loop / stale-clobber bugs).
The connection monitor, by contrast, is cleanly separable: it owns `_restartHandling` and leaks only ONE flag
(`_reloadingFromSSE`, set true/false around the passive design re-pull). **Placement lesson (refines #52's):** a
setter shim `(v) => { _reloadingFromSSE = v }` that closes over a `let` declared ~80 ln BELOW the factory call is
TDZ-safe *as long as the shim body runs only post-boot* — creating the arrow doesn't access the binding, and the
only caller (`recoverAfterRestart`) fires on a real restart event, long after boot reaches the declaration. So unlike
#52's `_fileIo` (whose deps were *read* to construct the factory, forcing the const past its banner), this factory
sits at its natural banner spot despite the forward flag ref. Grep-confirmed no synchronous caller of the shim before
committing. `connectionMonitor.start` is the imported `shared/connection_monitor.js` poller (also used by the cadnano
editor) → imported directly in the module, not injected.

**File-IO ops — first Tier-5 lift; late-dep placement is the whole game (#52, 2026-06-04).** The "File open /
save" region mixes two things by adjacency: cohesive **file-IO operations** (read/write the design/assembly,
Save As via the file browser, part-edit save-back) and the **lifecycle spine** (`_resetForNewDesign` /
`_enterAssemblyMode` / `_exitAssemblyMode`) which is called from 20+ sites and is NOT file-IO. Only the ops
lifted. The single hard part was placement: unlike every prior region, the ops' deps are declared LATER in
`main()` than the region itself (`_setSyncStatus`/`_syncLog` ~7500, `libraryPanel` ~7600 vs the banner ~3580).
A factory `const` isn't hoisted, so it can't sit at the banner. Resolution: place `const _fileIo = initFileIo({...})`
at the head of the autosave region (~7660, after the late deps), and confirm by grep that NO call site *executes*
a `_fileIo.*` method during boot — they're all either function-bodies that run on user action (menu dispatchers)
or object-property refs captured for later invocation (command palette / import menu). A ref captured before the
init point needs a lazy wrapper (`(opts) => _fileIo.x(opts)`); one captured after can be direct. Also: when a
spine fn (boot-callable) calls a candidate op, keep the small op inline and inject it (here `_updateAssemblyTitle`,
called by `_enterAssemblyMode`) — that severs the boot-order hazard entirely. Dropped dead `_pickOpenFile`
(0 callers; the cadnano editor has its own copy — `grep -rn pickOpenFile src` confirmed).

**Create Seam — pure-core-heavy lift + multi-doc app-exercise gotcha (#43, 2026-06-04).** The biggest single
region drained (−259 ln). Almost all of it is a PURE core (`computeSeamPlacements`: coverage map → merge
intervals → global adjacency via the HC/SQ scaffold-crossover lookup tables → connected components →
Hamiltonian path (single-sig) or arm/core bridge-chain (dumbbell multi-sig) → one Holliday junction per merged
intersection interval, nearest-to-midpoint consecutive bp pair). Only `store.getState()`, a `console.warn`, and
`api.placeCrossoverBatch` are impure → `initCreateSeam` is ~6 lines. The two closure-captured helpers
(`scaffoldXoverNeighbor`/`nickBpForStrand`) were parameterized on `isHC` to make them pure+exported (they derive
`period`/`xoverMap`/`bowRightSet` internally). Dropped dead local `helixByGridPos` (built, never read — #9/#1
dead-code precedent). **The Near/Far Ends handlers each redefine their OWN verbatim copies of these 4 constants +
3 helpers** — they are NOT folded in (separate region, one-region-per-commit), but the now-exported helpers set
up that dedup for the future Near/Far Ends lift.
**Two app-exercise gotchas cost most of the wall-clock (bank these):**
1. **Multi-doc no-op:** the obvious throwaway (`request.post('/api/design/load')` default-doc → `page.goto('/')`)
   leaves the TAB's `store.currentDesign === null` (the tab adopts its own random doc), so the click handler
   returns early and fires no POST — looks like a broken lift but is the multi-doc trap. The smoke
   console-error gate gets away with it (it renders from the geometry round-trip), but a handler that reads
   `store.currentDesign` does not. Fix = the harness's doc-pin: `?doc=<DOC>` on goto + `X-NADOC-Doc:<DOC>` on
   the load + a `BroadcastChannel('nadoc-design')` `design-changed` nudge with `docId:<DOC>`. After that the
   real click fired the place-batch POST with exactly 10 placements on 26hb.
2. **GET `/api/design` wrapper:** the response is `{design, validation, nucleotides?, ...}` — the design object
   is under `.design`. Feeding the raw response to `computeSeamPlacements` throws `design.strands is not
   iterable`. (26hb_platform_v3 yields 10 placements; 18hb 12; U6hb 4 — all real-data probes.)
The SQ bow-right oracle bit once: `SQ_SCAF_BOW_RIGHT = {0,3,5,8,...}` does NOT contain mod 2 (I assumed it
did); switched the test to mod 3. Verify oracle values against the actual lookup SETS, not by analogy to HC.

**View-toggles region was MIS-SCOPED (#41, 2026-06-04).** The carve-up lumped 5+ unrelated blocks under one
"View menu toggles + selection/tool filters" entry by file adjacency: (1) the view-menu pill-state subscriber
+ 3 visibility helpers, (2) Browser tab title, (3) Tool Filter toggles, (4) deform→selectableTypes
save/restore, (5) Selection Filter toggles, (6) the `.vt-btn` View tool buttons. Only (6) is a cohesive,
cleanly-liftable subsystem — extracted it. The two traps the LOC-only premise hid: **`_setMenuToggle` has 43
call sites** (a shared menu-pill util — moving it is a 43-import-swap, a *separate* shared-util lift, not part
of any feature factory), and the **Selection Filter toggles** block is welded to the drill-lock state machine
(`_manualFilters`/`_isManualSelect`/`_reflectDrillLevel`/`_resetToAutoBaseline`) that lives in the
`Selection-filter mode` region (~717) — those must move together. Logged both as future targets in the
carve-up; left the parent entry `[~]`. **Lesson (4th time): verify the region is ONE subsystem, not just
count its lines — the map groups by `// ──` adjacency, which ≠ cohesion.**

**Keyboard-shortcuts region — stale-premise + wide-shallow lift (#39/#40, 2026-06-04).** The carve-up map
billed this as "ONE giant keydown handler; factor to a key→action table." That refactor had ALREADY happened
(the region was 21 `registerShortcut({...})` calls into `input/shortcuts.js`'s registry + one document
listener). So the only remaining win was draining the closure via a factory — wide (~33 injected deps) but
shallow (every handler moved verbatim; risk is wiring breadth, not coupling depth). Split into 2 commits:
Group 1 (view/tool toggles, listener stays inline) then Group 2 (file/edit + Delete/Escape, listener moves
into the factory). Lessons banked: (1) **verify the banner's "what it is," not just its LOC** — premises drift
as the file is refactored over time; (2) jsdom keyboard tests use a **plain fake event object**, not
`new KeyboardEvent` (off-document → `target:null` → throws in the matcher); (3) a module-singleton registry
needs an exported `clearShortcuts()` for `beforeEach` isolation; (4) when the document listener moves into a
factory it becomes the single failure point for ALL shortcuts and `just smoke` won't catch a missing one —
the app exercise must press a key THIS module owns.

**Group-gizmo region — gesture-gate reality + coupling map (#35, 2026-06-04).** The carve-up handoff
claimed the group-drag gesture gate was "off-the-shelf" (a built grouped assembly + e2e). **It is not.**
`scene_harness.js` only *builds* fresh assemblies (`loadAssemblyWithParts`); Belt_test1.nass is a
*file-source* assembly (2 groups / 10 instances_v2 / 8 joints / gear_relations + belt_paths) that must be
OPENED, and there is **no load-existing-`.nass` harness helper** and **no group-select dev hook**. So the
gate's two prerequisites (load-saved-`.nass` + enter-assembly, and a `__nadocTest` hook that sets
`activeGroupId` to fire `_attachGroupGizmoForGroup`) must be built BEFORE `e2e/group_gizmo.spec.js` can
exist. Per the loop's "build the gesture gate first" rule for HARD canvas-gesture regions, the stateful
gizmo-attach lifts (b)/(c) were NOT forced. Banked only the safe pure de-risk (a).
**Coupling map (verified by grepping every symbol in the region):** `_attachGroupGizmo` /
`_attachGroupGizmoForGroup` pull on `_createAssemblyTransformContext` / `_createGroupTransformContext`,
`_analyzeMotionConstraints`, `summarizeConstraint`, `_setMotionChip`, `instanceGizmo`, `assemblyRenderer` /
`assemblyJointRenderer`, `_assemblyMultiBox`, `_mrAssemblyCtx`, and `_applyAssemblyPrimaryLive` /
`_queueAssemblyPrimaryCommit` (the last two **shared** with the Move/Rotate fields at ~7653/7655 → can't
just move them). The pending-state Maps (`_assemblyPendingTransforms` / `_assemblyPendingPartJoints`) are
touched in ~10 file-wide sites (dev hooks @13631, exit-cleanup @9631, keyboard-commit @8456) → stay in
main.js, pass by reference. **Self-contained sub-cluster found:** the gear-live revolute-drag engine
(`_applyGearLiveForRevoluteDrag` + `_applyGearLiveJointValue` + the `_revoluteGizmoAngle` accumulator + its
2 resets) is called ONLY by the two attach fns — a clean factory candidate that owns the angle state and
drains ~140 ln, doable BEFORE the gate via the #32/#24 verbatim+unit+smoke caveat. That's the recommended
next extraction (see carve-up handoff).

**Assembly-gesture harness (2026-06-04) — prerequisite for the (a)/(b) lift.** Built the missing
gate the coupling-wall note called for: a Playwright harness that drives the assembly canvas pointer
handlers through the REAL raycast and asserts on exposed state (mirrors the design-view bead harness).
Shipped:
- **Dev hooks** (`main.js`, `import.meta.env.DEV` only, no prod behavior change): `pickAssemblyInstanceAt`
  (occlusion-correct identity oracle via `assemblyRenderer.pickInstance`), `getActiveInstanceId` /
  `getActiveGroupId` / `isAssemblyActive` (state oracles), `enterAssemblyMode` (the `'a'` toggle was
  REMOVED — real entry is open/create a .nass; the hook mirrors that: `api.getAssembly()` → currentAssembly,
  then `_enterAssemblyMode()` attaches the handlers), `frameAssemblyForTest` (deterministic camera framing —
  see gotchas).
- **Harness helpers** (`e2e/helpers/scene_harness.js`): `loadAssemblyWithParts` (build a rendered N-part
  assembly), `assemblyInstanceCandidates` (fine grid-scan of the pick oracle), `selectAssemblyInstance`
  (ring-search exact pickable pixel → click → assert), `clickEmptyAssemblySpace`, `frameAssembly`.
- **Spec** `e2e/assembly_select.spec.js`: canvas-click selects a part; empty click clears; click switches
  between parts. 2/2, stable under `--repeat-each=2` (4/4). This is the **(b) instance-select gesture gate**.

**Hard-won gotchas (the reason this took a full batch — bank these for the next attempt):**
1. **Wire format:** doc-scoped `/assembly` returns `.nass v2` (`instances_v2` + deduped `sources`), NOT
   `instances`. `assembly_gizmo.spec.js` reads `.instances` (legacy default-doc) and is stale.
2. **Inline sources don't render** a freshly-built design's geometry on either renderer path (flaky/empty).
   Use a **file source**: `POST /design/save {path:'workspace/__e2e__*.nadoc'}` then
   `source:{type:'file', path:'__e2e__*.nadoc'}` (resolves against the workspace dir) — the server geometry
   pipeline is reliable. Force `?shared=0` (per-instance renderer) so inline/file builds into a pickable cache.
3. **Auto-fit is broken for these instances** — the renderer's bounding box is empty (so `getInstanceCenters`
   is empty AND auto-fit can't frame), and it fires LATE, drifting the camera off the parts. Frame
   deterministically from the **rendered geometry** (`Box3().setFromObject` on `userData.assemblyInstance`
   groups), view the **broad face** (camera along the smallest bbox axis — parts are thin ribbons, edge-on
   views graze past), and converge on a STABLE framing (two consecutive scans see clickable parts).
4. **Thin-rod pixel precision:** parts render as ~2 nm rods; the pre-checked pick pixel must EQUAL the
   clicked integer pixel (Playwright rounds), so a float candidate misses by 1px. Ring-search for an exact
   integer pixel where `pickInstance` resolves the target id, then click THAT pixel. (The bead-harness
   "retry on miss" lesson, applied to instances.)
5. **MOVE-mode occlusion:** selecting a part auto-arms the translate gizmo; clear (empty click, also exits
   MOVE) before selecting another so the gizmo doesn't sit over the next target.

**Next:** with this gate green, verbatim-lift (b) instance-select (and then (a) ring-drag) from
`_onAssemblyClick`/`_onAssemblyPointerDown` into `scene/assembly_pointer.js`, running `assembly_select.spec.js`
+ smoke as the gate. The shared mutable state still needs get/set shims (see the coupling-wall note below).

**Part-joint drag gesture test + bug fix (2026-06-04) — covers #28.** Added
`e2e/assembly_joint_drag.spec.js` (the (a) ring-drag gate): builds a part with a cluster + revolute
cluster-joint + `allow_part_joints`, arms the selected cluster (`selectAssemblyClusterForTest` hook),
does a real pointer-down→drag→up on the part, and asserts a non-zero pending part-joint rotation
(`getAssemblyPendingPartJoints` hook). This exercises `_updatePartJointDrag` → the `rotationDeltaMatrix`
dedup (#28), which had no automated coverage. Stable under `--repeat-each=2`.
- **Bug the test uncovered + FIXED:** the assembly part-joint cluster-drag (`_onAssemblyPointerDown`
  Priority 2b / sibling) reads `joint.axis_origin`/`axis_direction`, but a `ClusterJoint` stores only
  `local_axis_origin`/`local_axis_direction`. The world axes are derived by `_inject_joint_world_axes`,
  which ran ONLY on the design-view GET (`crud.py:1356`), never on the assembly per-instance design — so
  `getInstanceDesign().cluster_joints[*].axis_origin` was `undefined` and `new THREE.Vector3(...undefined)`
  threw on pointer-down (selecting+dragging a cluster to rotate it about its joint was broken for any part
  with a cluster joint). Fix: call `_inject_joint_world_axes(design_dict)` in `get_instance_geometry` +
  the seek path (`backend/api/assembly.py`), mirroring the design view. The injected axes are design-world
  (= instance-local), which is exactly what the handler then maps through `instMat`. Pre-existing bug, not
  from the refactor. Backend suite: 0 new failures vs HEAD (the 2 router/staple failures pre-exist;
  `teeth_closing_zig` is order-flaky, passes in isolation).

**Tier-3 (a)/(b) COUPLING WALL (#28, 2026-06-04):** investigated factory-lifting the stateful shells of (a) joint-ring pick (`_onAssemblyPointerDown` + `_updatePartJointDrag`/`_onAssemblyDragMove`/`_onAssemblyDragUp`) and (b) instance select (`_onAssemblyClick` tail). **Not safely extractable in one batch.** The handlers share SEVEN mutable closure vars, several read/written by *sibling* handlers outside the region: `_partJointDrag`/`_freeDrag`/`_pendingFreeDrag`/`_assemblyPtrDownAt` (local to the cluster) but `_assemblyRightDownAt` (also contextmenu), `_assemblySelectedPartJoint` (also cluster-context), `_selectedAssemblyCluster` (also panel-selection @9866 + cluster-context @11249/11264), `_assemblyPendingPartJoints` (Map shared with commit), and `_translateRotateActive` (read here, owned/written by the translate-rotate tool in ~25 sites). A factory would need ~25 deps + get/set shims for 4 cross-handler vars — that rewiring is NOT verbatim (real semantic change) and there is **no assembly-drag gesture e2e harness** (scene_harness is design-view bead-picking only; validating part-joint rotation / free-drag / cluster re-click needs a built multi-part *mated* assembly fixture). Per the loop's "too coupled → log and stop, don't force" rule, lifted only the safe pure dedup (#28) and stopped. The pure cores beyond it are trivial (a 1-line world-entry map, duplicated twice) — not worth a module. **To finish (a)/(b): build an assembly-gesture harness first (prerequisite), then verbatim-lift the shells with get/set shims.** Flagged to user.

**Coupling wall — (b) resolved (#29, 2026-06-04).** With the `assembly_select.spec.js` gate in place, the
(b) instance-select shell lifted cleanly after all: `_onAssemblyClick` only *reads* `_translateRotateActive`,
only *writes* `_selectedAssemblyCluster` / `_assemblySelectedPartJoint`, and get+sets `_assemblyPtrDownAt` —
so 5 get/set shims (not the feared ~25 deps) plus a `getClusterPanel` lazy getter covered it. The 16 plain
deps are all defined before the factory-init point. Key insight: the (b) handler's slice of the shared state
is far smaller than the union the wall note tallied (that union spanned (a)'s drag handlers too). Only **(a)**
remains — `_onAssemblyPointerDown` + drag-move/up, which genuinely owns `_partJointDrag` and writes the
state (b) only reads; its gate is `assembly_joint_drag.spec.js` (already built, #28). (b)'s shims are now in
main.js ready to reuse for (a).

**Coupling wall — (a) resolved (#30+#31, 2026-06-04) — REGION COMPLETE.** The wall note's scariest item
(`_translateRotateActive` "owned/written by the translate-rotate tool in ~25 sites") turned out to be a
*read-only* dependency in the pointer handler — one get shim, not a re-plumb of all 25 writers. The other
feared cross-handler vars resolved the same way the (b) ones did: pointer-down only *reads*
`_selectedAssemblyCluster`, get+sets `_assemblySelectedPartJoint`, and *sets* `_assemblyPtrDownAt` /
`_assemblyRightDownAt`. The genuinely-local drag state (`_partJointDrag`/`_freeDrag`/`_pendingFreeDrag`)
needed NO shims at all — a grep confirmed only the 5 drag/pointer handlers + the assembly-exit cleanup ever
touched it, so it became module-internal and the cleanup became one `cancelDrag()` call. The Map
(`_assemblyPendingPartJoints`, shared with commit + a dev hook) passed by reference — both sides mutate the
same instance. **Two-commit split** (drag handlers first with a temporary `beginPartJointDrag` seam, then
pointer-down) kept each step verbatim-equivalent + independently green. `beginPartJointDrag` stayed exported
as the drag-commit unit-test seam (the real arming path needs a successful `ringPlaneHit`, which a jsdom
mock camera can't produce — so the commit-side observable is unit-tested, the arm side is e2e-tested).
Lesson confirmed (3rd time now): the wall note's dep tallies counted the *union* across sibling handlers and
badly over-estimated each individual handler's actual slice — read the specific handler's reads/writes, not
the var's global footprint.

**Tier-3 note (#27):** first cut into the HIGHEST-coupling region (Assembly canvas pointer handler, ~340 ln across `_onAssemblyPointerDown` + `_onAssemblyClick` + drag-move/up). Only sub-part (c) is cleanly pure — it's a store-state decision given the picked instance. Lifted it to the module where `findOwningGroupId` already lives (which is now no longer imported in main.js). (a) joint-ring pick and (b) instance select remain — both entangled with `_partJointDrag`/drag-move-up/`ringPlaneHit`/`instanceGizmo`/`_commitAssemblyPending` and need the gesture e2e (built grouped assembly) when (b) lands. Lesson: in a HIGH-coupling handler, the pure *decision* branches lift out cleanly first and de-risk the stateful remainder.

## Teardown gate (2026-06-04) — closed the one structural blind spot

The console-error gate boots + renders but never TEARS DOWN, so a broken disposal escaped it — that's
exactly how #34's `_assemblyMultiBox = null`-on-a-`const` `TypeError` shipped and threw on every assembly
exit. Closed the gap by putting both teardown paths in `just smoke`:
- **Design close-session** → new `Teardown gate` leg in `smoke.spec.js`: `loadScaffoldedPart` (so the tab
  actually holds a design — a bare `goto` boots to an empty random-doc welcome and would take close-session's
  no-design short path), then File→Close Session → asserts welcome + WORKSPACE + zero console/page errors.
  Exercises `_closeSession` → `_resetForNewDesign` (disposes ~20 scene modules: photo/cadnano/deform/slice/
  blunt-ends/legends/representation-reset/store-clear).
- **Assembly-mode exit** → `just smoke` now ALSO runs the existing `assembly_exit_cleanup.spec.js` (the #34
  regression guard) instead of leaving it out-of-gate to bit-rot (#48). Reused the standalone (building a
  2-part assembly is heavier + uses the scene_harness assembly builder) rather than duplicating it into
  smoke.spec.js.

**Audit of impacted sections (which extracted teardown APIs the gate now covers):**
- `viewLegends.reset()` (#50) — called in `_resetForNewDesign` → **now gate-covered** (was unit-test only).
- `_assemblyMultiBox.dispose()` (#34) — called in the assembly-exit subscriber → **now gate-covered**; the
  escape that motivated this is permanently guarded.
- `_assemblyRefresh.dispose()/flush()` (#38) — STILL unit-test only: additive, never wired into exit cleanup.
  A pending timer surviving exit no-ops via the `assemblyActive` guard, so it's not a correctness risk — left
  as-is (don't wire it just to test it; that would change exit behavior).
- **#34-class scan clean:** grepped every extracted factory `const` for a `= null` reassignment — only
  `let _beltPolymerize = null` (a lazy-init declaration, not a teardown) matches. No factory `const` is poked
  by a teardown site. Green smoke through these paths now proves it: a lurking const-reassignment/raw-object
  poke in `_resetForNewDesign`/`_exitAssemblyMode` would surface as a red gate.

**Known still-uncovered teardown (acceptable):** the COMBINED assembly-then-design close-session path
(`_closeSession`'s `assemblyActive` branch: save → `_exitAssemblyMode` → `_resetForNewDesign` → `api.closeSession`)
is only covered piecewise (exit via the hook; design-reset via the new leg), not as one sequence. Low risk —
both halves are individually green. Fold into the gate if a regression ever surfaces there.

**Metric definitions** — `wall-clock`: rough session minutes (target EASY <15, MEDIUM <30, HARD <90).
`main.js LOC Δ`: lines removed from `main()` body (imports stay, so total drops less). `tests added /
pure fns`: must be ≥1.0. `edits-to-green`: vitest runs until pass (lower = pattern internalized).
`manual app min`: minutes of running-app exercise still needed (target →0 for EASY/MEDIUM). `caught by`:
vitest / smoke / manual / **escaped-to-user** (the failure we most want to avoid).

## Decision rule (after the 3 pilots)

- EASY+MEDIUM each <30 min, **0** escapes, ~0 manual min → pure-extraction loop works; **scale it**.
  Next batch: overhang map-builders (main.js:2009–2123), overhang query helpers (8170–8196),
  camera-framing core (4954–5011).
- HARD's regressions caught by vitest-core + smoke with bounded manual exercise → stateful tier safe to
  scale with the smoke gate.
- HARD **escaped** a regression despite smoke → smoke alone insufficient for stateful clusters; add
  targeted jsdom interaction tests (Tier 1.5) before scaling HARD extractions.

## MEDIUM extraction backlog (mapped 2026-06-03)

Pure functions trapped inside the `main()` closure, found by a purity scan (reference only
params/locals/THREE/Math/imports — no scene/store/designRenderer/DOM/api). Grouped into cohesive
target modules, highest leverage first. **Key finding: real triplication** — several helpers are
defined 2–3× verbatim, so extracting collapses copies AND drains the closure.

| Order | Target module | Functions | Why / leverage |
|---|---|---|---|
| 1 | `scene/scaffold_coverage.js` | `intersectCoverage` (×3 verbatim), `findHamiltonianPath` (×2 verbatim) | ✅ DONE (extraction #4, −74 lines). Collapsed 5 copies; used by Create Seam / Near-Ends / Far-Ends. |
| 2 | `scene/overhang_maps.js` | `_buildSpecMap`, `_buildDomainMapFromDesign`, `_buildDomainMapFromGeom`, `_buildJunctionMapFromXovers`, `_buildJunctionMapFromDomains`, `_buildRootMap` | ✅ DONE (extraction #6, −86). Orchestrator `_buildOvhgMaps` (impure) stays; boot gate exercises the pipeline on a real overhang design. |
| 3 | `scene/strand_length.js` | `_strandLength`, `_strandLen`, `_strandNt` | ✅ DONE (extraction #5, −29). Verified `_strandLength`≡`_strandLen`; kept `_strandNt` as the distinct no-skip variant. `_geomCentroid` deliberately NOT bundled (unrelated centroid helper — avoided scope creep). |
| 4 | `scene/gear_math.js` | `_signedAngleFromWorldDelta`, `_rotationDeltaMatrix`, `_clampJointValue` (7 callers), `_movingSideSignForRevolute`, `_gearEndpointSide` | ✅ DONE (extraction #7, −42). `_applyGearLive*`/`_applyFKLive` (touch assemblyRenderer) stay; imports makeRefVec from assembly_revolute_math.js. |
| 5 | `scene/assembly_diff.js` | `_matrixFromInstance`, `_sameInstanceTransform`, `_assemblyTransformOnlyChange`, `_constraintRelevantChanged`, `_summarizeConstraint` | ✅ DONE (extraction #8, −83). Impure subscribers (`_effectiveInstanceMatrix`, `_collectGroupMemberInstanceIds`) stay. |
| 6 | `scene/design_queries.js` | `isExtrudeOverhang`, `ovhgDomainIds`, `flexAnchorKey`, `connIdForBead`, `surfaceSegments` | ✅ DONE (extraction #9, −51). **Excluded `_clusterBeadCount`** — agent mis-flagged it CLEAR but it calls `designRenderer.getBackboneEntries()` (impure, stays). **Dropped `_ovhgDomainBpRange`** — dead (0 callers). |

Singletons (do one when convenient): ~~`_clusterTransformAfterJointDelta`~~ ✅ #10 (cluster_joint_math), the
`_format*` report helpers (aksel_format), ~~`_computeGroupHiddenInstanceIds`~~ ✅ #12 (assembly_groups_util),
`_heatmapHex`/`_fretQuenchedDonors` (BORDERLINE — each reads 2 constant lookup maps; pass them in
or co-locate the maps with the function).

**Excluded (look pure, aren't):** `_applyFKLive` / `_applyGearLive*` (assemblyRenderer), `_filterAtomData`
(`_atomDataCache`), `_rebakeHelixAxesForClusterDelta` (`store`), `_effectiveInstanceMatrix`
(`_assemblyPendingTransforms`), `_buildSsdnaPayload` / `_ooPreviewFromFields` (store/DOM).

Recommended next: **group 1** (max dedup + lines, zero risk), then 3 (dedup), then 2/4/5/6 in any order.

## Notes / lessons per extraction

**#1 (EASY, bundle trio):** Smooth — verbatim move + import-back + 9 vitest tests, green on first run, app boots clean.
- **Key lesson:** these were already at *module top level* (outside the `main()` closure), so the extraction shrank main.js by 16 lines but reduced the closure body by **0**. EASY top-level extractions are good for establishing the loop and growing the test tier, but the closure-shrink goal needs MEDIUM (inside-closure) extractions. Adjust expectations: don't judge progress on EASY by closure-line reduction.
- `bundleMaxOffset` had 0 callers (dead) — extracted + exported anyway to keep the API; flagged in the module for later removal.
- `_flexibleRunForBead` (the 4th candidate originally grouped here) was **deferred** — it's thematically a flexible-segment helper, not bundle-axis math. It's the natural next EASY extraction into its own module.
- Frontend has no JS linter (`just lint` is Python-only), so the lint-delta gate is N/A for `.js` extractions; vitest + console-error gate are the real gates.

**#2 (MEDIUM, rotation-math trio):** Confirmed the loop's value — the three Euler/quat/joint-angle helpers were *inside* the `main()` closure but captured nothing from it (THREE + Math only), so the lift was clean: verbatim move, rename 7 call sites (3 names), one import. **−22 lines off the closure body** — the first real closure shrink, vs EASY's 0. 8 vitest tests green on first run; app boots clean.
- The math paths (Move/Rotate fields, cluster gizmo) aren't hit on plain design load, so the console-error gate doesn't exercise them — but the move was verbatim (identical call args), and unit tests cover the math, so per the streamlined rule a pure extraction needs no manual app exercise here.
- Takeaway for scaling: MEDIUM "pure-but-trapped-in-closure" extractions are the high-value target — same near-zero risk as EASY, but they actually drain the closure. The bottleneck is finding pure functions amid the closure; a grep for inside-`main()` functions that reference only THREE/Math/args would surface the next batch.

**#3 (HARD, measurement tool):** The stateful-cluster case. Extracted state + clear + show + the ctrl-bead subscription into a factory `initMeasurementTool({ scene, selectionManager, onSelectionHudChange })` returning `{ show, clear, isActive, dispose }` — the same DI shape as `initEndExtrudeArrows`. −32 lines off the closure. The `_updateSelectionHud` coupling became an injected callback (the subscription always calls it; relies on hoisting since the factory is invoked above the HUD's definition). Factory-style vitest (mock scene/selectionManager, jsdom DOM) — 7 tests green first run.
- **The decisive HARD lesson (answers the plan's open question):** vitest covers the module's logic and `just smoke` (21/21) covers boot + a real-design render, but **neither exercises the interactive gesture** (Alt/Ctrl-pick two beads → press M → line + readout appears → clears). That path is only reachable through real selection + keypress. So for stateful tools, vitest + smoke is *necessary but not sufficient*; the interactive path needs either a dedicated Playwright interaction test or a manual USER TODO. The move here was verbatim (identical call args at the 3 sites), which is why the risk is still low — but "verbatim + unit-tested + boots clean" is the ceiling of automated confidence for this tier.
- **Decision-rule verdict:** EASY/MEDIUM → scale freely (zero manual, zero escapes). HARD → safe to scale *with the verbatim discipline + smoke*, but each stateful extraction should ship with either a Playwright interaction test for its gesture or a logged USER TODO. Worth building one reusable measurement-gesture e2e as the template before doing many HARD extractions.

### Gesture e2e template (resolves the HARD-tier "interactive path" gap)
The measurement gesture is now covered by `frontend/e2e/measurement_tool.spec.js` — it
drives the real Alt-click → `M` path and asserts the readout + scene line, then toggle-off
(3/3 stable). It's the **reusable template** for verifying any stateful tool's gesture.

Run it for the measurement tool with: `cd frontend && npx playwright test measurement_tool.spec.js`.
(Not in `just smoke` — that stays the fast generic boot/console gate; gesture specs are
per-tool and run on demand for HARD extractions.)

**Building it surfaced the four real obstacles to GPU-gesture e2e in this app** (each baked
into the template as a comment so the next one is quick):
1. **Multi-doc:** a tab with no `?doc` adopts a sticky *random* doc id, so `page.request`
   (default doc) hits a different document than the tab. Pin `?doc=<DOC>` + stamp
   `X-NADOC-Doc:<DOC>` on builds, and emit the rebuild nudge with the matching `docId`
   (the `design-changed` receiver scopes by `isSameDoc`).
2. **No auto-render on boot:** plain `goto` shows the welcome screen and never loads the
   server design — you must go through a real load path (here: File>New + API build + a
   doc-scoped BroadcastChannel nudge). `auto-scaffold` 422s on a lone helix → fall back to
   `scaffold-domain-paint`.
3. **LOD + panel occlusion:** beads must be at full scale (zoom in past cylinder-LOD), and
   the side panels overlay the full-width canvas — beads projecting under `#left/right-panel`
   or `#menu-bar` aren't clickable (the event goes to the panel). Filter those out.
4. **Miss-clears:** an Alt-click that misses a bead calls `_clearCtrlBeads()` (resets to 0),
   so you can't assume two clicks = two beads — click central beads and re-pick until the
   count actually reaches 2. Match the measurement line by its colour (0x00e5ff), not just
   `renderOrder 999` (other overlays share it).

New reusable dev-only test hooks on `window.__nadocTest` (main.js): `getBackboneBeadScreenPositions(maxN)`
and `getCtrlBeadCount()`.

## Strategy shift (2026-06-03): pure helpers → stateful subsystems

The pure-helper well is drained. main.js is still ~15.6k lines because the mass lives in stateful
subsystems (panels/dialogs/menus/handler-clusters). Further decomposition now targets those, factory-
extracted (`initX({deps})→{api}`) with gesture-e2e + smoke for interactive ones. The prioritized
backlog — region → target module, est. size, dependency surface, risk tier, gesture-gate flag — lives
in **`main_js_carveup.md`**. Each session claims ONE region from there. Run each batch in a FRESH
session (token cost scales with conversation length; the log + carve-up map + main-init.md carry all
the state a cold session needs).

## Test infrastructure (2026-06-04) — shared helpers + scaffolding skill

The per-region test boilerplate (mock store, DOM mount, mock deps) was being
hand-copied each extraction. Factored out so future regions are cheaper, and so
the generate-vs-judge boundary is explicit:

- **`frontend/src/test-helpers/mock_store.js`** — `createMockStore(initialState)`:
  getState / setState-that-notifies / subscribe (returns unsubscribe) / `_emit`.
  Replaces the ~15-line hand-rolled store in every factory test.
- **`frontend/src/test-helpers/factory_dom.js`** — `mountIds(spec)` (array→`<div>`,
  or `{id: tag}`) + `clearDom()`. `getElementById` ignores nesting, so a flat
  by-id set is enough to wire a factory.
- **`frontend/e2e/helpers/scene_harness.js` → `trackConsoleErrors(page)`** — the
  three-line console/pageerror collector every throwaway app-exercise spec used.
- **`frontend/scripts/scaffold-tests.mjs`** — reads an extracted module, emits a
  `.test.js` skeleton (helper imports, `mountIds` stub from its `getElementById`
  ids, `makeDeps()` `vi.fn()` stubs from `dep.method()` / direct-fn call sites,
  empty `describe`/`it` with TODOs). Regex, no AST — a starting point to edit.
- **Skill `extract-tests`** (`.claude/skills/extract-tests/SKILL.md`) — wraps the
  above into the loop step 4.

**The bright line (load-bearing):** these generate test *structure*, never the
*oracle*. Assertions stay human-authored — an LLM writing assertions from the same
reading of the code under test produces tautological tests that pass and pin
nothing, silently. The reusable pattern is **propose → validate against an
authoritative oracle (`just test-frontend` + `just smoke` + verbatim-move) →
retry**; that same harness shape is the intended foundation for later
validator-gated generation (e.g. text→design gated on topology/three-layer
validators). Keep generate and validate separate; never let the generator judge.

Retrofitted #21/#22/#24 factory tests onto the helpers (vitest 314→326, all green;
+12 from the two helper specs). The generated skeleton runs green as-is before any
assertions are filled (verified end-to-end).

## Difficulties ledger (for later attempts / the autonomous loop)

Append-only. Record candidates that turned out NOT to be clean pure extractions, plus any
gotcha worth remembering. The autonomous extraction loop writes here when it skips something.

- **jsdom does NOT reflect `style.display` set via a multi-prop `cssText`** (factory tier).
  Building `overlay.style.cssText = 'display:none;position:fixed;...'` leaves `overlay.style.display`
  as `''` under vitest/jsdom, so initial-hidden assertions fail. Fix: set `overlay.style.display`
  explicitly after the `cssText` line (harmless in the browser, makes the hidden state robust + the
  intent explicit). Hit during the loop_popup (#19) factory extraction.
- **`_clusterBeadCount` — NOT pure (skip).** The purity-scan agent flagged it CLEAR, but it
  calls `designRenderer.getBackboneEntries()`. Left in main.js (group 6). Lesson: re-verify the
  agent's "CLEAR" rating by reading the body before extracting — the scan over-trusts signatures.
- **`_ovhgDomainBpRange` — dead (0 callers).** Removed rather than carried into a module.
- **Playwright boot gate was unrunnable on this machine** until `playwright.config.js` cwd was
  fixed (it hardcoded `/home/jojo/Work/NADOC`). Now derived from the config file location, so
  `just smoke` / the console-error gate auto-start the servers anywhere. If the gate ever fails
  with `spawn /bin/sh ENOENT`, the servers are down AND the cwd is wrong again.
- **Test-design picking for overhang panels (#21):** a `.nadoc`'s *file-level* `overhangs` array is NOT
  the runtime `design.overhangs` — hingeV4 stores 36 file-level overhangs but loads with
  `design.overhangs`=0 (legacy/embedded representation that doesn't re-materialize). To exercise an
  overhang panel against real rows, use **`Examples/NS_trans_fix.nadoc`** (51 runtime overhangs after
  `/api/design/load`); verify with `GET /api/design` (stamp `X-NADOC-Doc`!) before relying on it.
  ALSO: the `?open=` boot path imports into the tab's OWN random doc, so a bare `fetch('/api/design')`
  in `page.evaluate` reads the *default* doc (empty) — the multi-doc trap again. For a reliable
  welcome-dismissing app exercise, prefer `scene_harness.loadScaffoldedPart` (File>New, pinned doc) over
  `?open` of a big legacy file (which intermittently re-shows welcome / stalls render under the test timeout).
- **2D sidebar-canvas gestures DON'T need scene_harness (#20).** The histogram's click/hover/right-click
  are plain 2D-canvas hit-tests (`getBoundingClientRect` + `_barData` rectangles), NOT WebGL raycasts.
  jsdom covers them directly: stub `getContext`/`getBoundingClientRect`, dispatch a `MouseEvent('click')`,
  assert `selectStrand`/`centerOnStrand` fired. Reserve `scene_harness` for WebGL-bead picking only. So a
  Tier-1 panel whose only "gesture" is a 2D canvas/DOM click is fully closeable with vitest + smoke + one
  app exercise — no Playwright gesture spec.
- **#20 banner-span trap (recurring):** the carve-up map's line spans are banner-to-banner and OVERSHOOT —
  the "Help / Hotkeys modal" entry's 346 ln is actually ~6 ln of modal wiring + unrelated debug toggles +
  the whole Create-Seam handler. ALWAYS read the region and find where the *cohesive* block ends before
  trusting the LOC estimate (the histogram IIFE, by contrast, was a clean self-contained `;(function…)()`).
- **Group-gizmo (b)/(c) — the gesture gate the handoff demanded was NOT needed (#36/#37, 2026-06-04).**
  The prior session's handoff said (b)/(c) were blocked on building `e2e/group_gizmo.spec.js` (load a
  grouped `.nass`, select a group, mouse-drag the gizmo). That gate is impractical AND unnecessary: the
  group gizmo is a `TransformControls` widget whose handles are tiny 3D objects you can't hit reliably at
  integer-pixel precision (the thin-rod lesson, worse). The behaviour (b)/(c) actually own is the
  `onLiveTransform` / `onCommit` **callbacks** passed to `instanceGizmo.attach`. A jsdom factory test with a
  mock `instanceGizmo` that *captures* those callbacks and invokes them drives the exact wiring
  deterministically — a stronger check than a flaky handle-drag. Lesson: for a verbatim lift of gizmo
  attach/commit logic, capture-and-invoke the callbacks; reserve real GPU gestures for raycast-pick paths
  (selection, ring-drag) where the click coordinate IS the thing under test. The `assembly_select` /
  `assembly_joint_drag` specs already exercise the (b) attach path through the subscriber, so they doubled
  as the real-app exercise. Don't build group_gizmo.spec.js.
- **LATENT BUG found adjacent — now FIXED (commit d5be41c, 2026-06-04).** `main.js` assembly-exit cleanup
  (the `subscribeSlice('assembly')` handler, ~line 9676) treated `_assemblyMultiBox` as a raw Three.js
  `BoxHelper`: `scene.remove(...); ...geometry?.dispose?.(); _assemblyMultiBox = null`. Since extraction #34
  made `_assemblyMultiBox` a `const` factory object (`{update, dispose}`), the `_assemblyMultiBox = null` line
  was an **assignment-to-const TypeError** that threw on EVERY assembly-mode exit (close session / open
  another doc while in assembly mode). No test hit the exit path, so it escaped. Fixed: replaced the inline
  teardown with the factory's `dispose()` (identical behavior, no reassignment). Added a dev-only
  `__nadocTest.exitAssemblyMode` hook + `e2e/assembly_exit_cleanup.spec.js` (first coverage of the exit
  tear-down; verified it fails pre-fix, passes post-fix). **Lesson: when an extraction converts a raw
  scene-object closure var into a `const` factory, grep every site that reassigned or poked `.geometry`/
  `.material`/`scene.remove` on it — those break silently if they're outside the boot/smoke path.**
  **UPDATE 2026-06-04: this exit path is now IN `just smoke`** — the assembly-exit teardown
  (`assembly_exit_cleanup.spec.js`) and the design close-session teardown (`smoke.spec.js` Teardown gate) both
  run in the commit gate, so a future #34-class teardown bug surfaces red instead of escaping. See the
  "Teardown gate" section above.
- **Dead-debug-helper deletion: grep `e2e` too, not just `src` (#44/#45, 2026-06-04).** The want-it gate
  flagged three Tier-6 dev-only console helpers as "dead" → 2 were (`nadocLabelAudit` #44, `__extDebug`-block
  #45, deleted), but the 3rd, **`_nadocDebug`, is NOT dead and was NOT deleted.** It has zero `src` callers
  (it's a `window.*` browser-console namespace) yet THREE e2e specs depend on its methods —
  `relax_undo_bug.spec.js` (`snapPos`), `dsdna_linker_selection.spec.js` (`overhangLinkArcs`),
  `representation_order_fkeys.spec.js` (`refetch`) — and photo-mode attaches `_nadocDebug.photoMaterials/…`
  at main.js ~10275. A `src`-only grep would have wrongly green-lit deleting it, breaking 3 specs. **Rule:
  before deleting any `window.*` debug global, `grep -rn <name> src e2e` — debug hooks live-wire the test
  suite without ever appearing in `src`.** Also: when deleting a debug *flag* (`__extDebugWatch`), check who
  *reads* it — `unfold_view.js` gated a console.log around a real `applyUnfoldOffsetsExtensions()` call that
  also ran in the `else`; the collapse to the bare call is behavior-identical (verify the non-debug path
  exists before removing the branch).
- **`_nadocDebug` "gate" specs are pre-existing RED — attribute failures by stash-and-rerun (#48, 2026-06-04).**
  The carve-up named `relax_undo_bug` / `dsdna_linker_selection` / `representation_order_fkeys` as the gate for
  the `_nadocDebug` extraction (they use `.snapPos`/`.overhangLinkArcs`/`.refetch`). All 6 of their cases FAIL on
  the pre-change baseline (verified: `git stash push -u` the extraction, rerun → identical failures; the relax
  one times out at the welcome-screen/load stage, *before* any `_nadocDebug` call). So they're red on master
  for unrelated reasons and **cannot gate a verbatim lift**. Validated the lift instead by (a) smoke 21/21 —
  its console-error gate boots the app and would catch a throw in `window._nadocDebug = initDevtoolsDebug(...)`;
  (b) vitest 516 (+13 factory tests); (c) baseline-identical e2e (proves no regression). **Lesson: when a
  named e2e gate is already failing, don't assume your change caused it — stash and rerun to get the baseline,
  and fall back to smoke + vitest + verbatim-move for confidence.** **RESOLVED 2026-06-04 (commits 0838849,
  933fd38):** all 3 specs repaired and green (7/7). They were stale on up to 4 axes, none related to
  `_nadocDebug`: (1) the New-Part dialog migrated to a `createModal` modal so the hardcoded
  `#new-design-create` button was gone; (2) the **multi-doc trap** — a bare `goto('/')` tab gets its OWN
  random doc id (`doc_id.js`), but the specs created/loaded designs via default-doc `page.request.post`, so the
  tab read an empty doc (fix: do it in-tab via `apiMod.loadDesign`/`createBundle`, which stamp `X-NADOC-Doc`);
  (3) **stale fixtures** — `Hinge.nadoc` lost its bundled OverhangBinding + ds linker, so the specs now build
  the feature in-tab (relax: set OH2 sub-domain = revcomp(OH1) then POST `/design/overhang-bindings`; dsdna:
  POST `/design/overhang-connections` → auto-named L1); (4) stale model/timeouts (binding dropped
  `driven/driver_overhang_id` → use `target_joint_id`; bump timeouts for the in-tab build). **Lesson: e2e
  specs outside the `just smoke` gate bit-rot silently as infra (multi-doc, modal migrations, fixture
  contents, model fields) evolves — and the failure surfaces far from the root cause (a Create-button timeout
  masked a stale fixture three layers down). Prototype the real API payloads against a live backend before
  rewriting spec setup.**
- **`.bind()`-restore is not reference-restore (#48 oracle bug).** `storeTrace`/`posTrace` save the original as
  `fn.bind(obj)` and restore *that* — so post-restore the slot holds a functionally-equivalent bound copy, not
  the literal pre-patch reference. A `toBe(original)` oracle is wrong; assert functional restoration (the
  restored fn is no longer the wrapper AND calling it delegates to the real fn).
- **Other backlog impure exclusions (do NOT extract):** `_applyFKLive`, `_applyGearLive*`
  (assemblyRenderer); `_filterAtomData` (`_atomDataCache`); `_rebakeHelixAxesForClusterDelta`
  (`store`); `_effectiveInstanceMatrix` (`_assemblyPendingTransforms`); `_buildSsdnaPayload`,
  `_ooPreviewFromFields` (store/DOM); `_computeAssemblyDuplicateOffset` (assemblyRenderer).
- **Borderline singletons (need a small tweak):** ~~`_heatmapHex`~~ ✅ #13 — co-located `HEATMAP_MIN/MAX` (only this fn used them) in color_util.js; ~~`_fretQuenchedDonors`~~ ✅ #14 — parameterized the maps (left in main.js, populated there); fret_util.js
- **Discovery pass #1 findings (after mapped backlog drained):** scanned main() for pure fns. Extracted `vecClose` (#15). Logged non-candidates:
  - `_isManualSelect` — reads closure `_manualFilters` Set (impure, skip).
  - `_highDetailGeometries` — reads/writes closure cache `_hdGeoCache` + allocates THREE geometries (impure resource cache, skip).
  - `_atomisticUrl` (returns the literal '/api/design/atomistic') and `_formatAqueousBackground` (returns a constant CSS string) — pure but TRIVIAL constants, not worth a module; left in place.
  - Remaining heuristic hits are overwhelmingly DOM/panel show/hide helpers (capture element refs → stateful) — not pure; not individually logged.
- **Discovery pass #2 (deeper) — well is DRY.** Read all remaining substantive heuristic hits; every one is impure/stateful, so the autonomous loop STOPPED here:
  - `_applyResponseDelta` (delegates to `_applyClusterUndoRedoDeltas`/`_applyPositionsOnlyDiff` + registers with `api`), `_broadcastInstanceChanged` (`nadocBroadcast.emit`), `_runCoalescedAssemblyRefresh` (closure `_asmRefresh*` state + setTimeout), `_applyRegionSurfaceOverlay` (closure `_regionSurfaceSig/_regionSurfaceTimer` + setTimeout) — stateful.
  - `_setMotionChip`, `_mrSetTransformValuesFromMatrix` (→ `_mrSetTransformValues`), `_updateReprRadio`/`_updateAtomisticRadio`, `_ascUpdateWarning` — DOM mutators.
  - `_clearStapleChecks`/`_clearScaffoldChecks` — empty no-ops (nothing to extract).
  - Remaining heuristic hits are all panel show/hide DOM helpers. **Conclusion: the pure-helper well inside main() is exhausted; further decomposition requires stateful/HARD extraction (factory + gesture e2e + human eye), out of scope for the autonomous pure-only loop.**

## Loop complete (2026-06-03)
Autonomous pure-extraction loop terminated on dry discovery pass. 6 loop iterations
(#10–#15) on top of the 6 mapped groups (#4–#9) and 3 pilots (#1–#3). Next decomposition
step is the HARD/stateful tier (per-tool factory extractions with the gesture-e2e template),
which needs human review and is intentionally NOT automated.

## Robust gesture validation (2026-06-03) — research + harness

Deep-research (WebGL/Three.js e2e validation, 24/25 claims confirmed) → built a reusable gesture
harness so the HARD/stateful tier isn't hand-rolled per spec. Key conclusions:

- **The project→screen + real synthetic-click pattern is the recognized approach** (MapGrab is the
  productized reference). The robustness is NOT in pre-verifying the pixel — it's in **clicking through
  the REAL raycast + asserting exposed state + RETRYING on miss**. Empirically: integer-pixel clicks on
  small WebGL beads hit only ~half the time, so a single "verified" click is flaky; the retry loop is
  what works (the original measurement spec already relied on it).
- **GPU object-ID color-picking was NOT evidenced in production e2e** — don't build it; the real-raycast
  pick (`pickBeadAt`) is the occlusion-correct oracle teams actually use.
- **r3f `fireEvent` skips raycasting** → can't validate occlusion; real clicks are required.
- **Tier 3 visual-regression** (Playwright `toHaveScreenshot`/pixelmatch, odiff, Loki/Chromatic) is the
  "does it look right" complement, but needs a **pinned software rasterizer** (headless Chrome defaults
  to SwiftShader; baselines are per-OS/browser) — deferred until we have CI determinism. First-time
  aesthetic correctness is the irreducible human-eye boundary pixel-diffing never covers.

**Shipped:** `frontend/e2e/helpers/scene_harness.js` (`loadScaffoldedPart`, `beadCandidates`,
`altPickBeads`) + dev-only `__nadocTest.pickBeadAt` / `getSelectedObject`. Proven on EASY
(`bead_select.spec.js`, alt-pick 1 bead) and HARD (`measurement_tool.spec.js`, alt-pick 2 + M + clear)
— 6/6 across repeats. **Dropped** an earlier `findClickableBeads` "pre-verify the pixel" hook: it gave
false confidence (a float-center-verified point still misses at integer click precision) — retry beats it.

### USER TODO — manually confirm the robust gesture loop works on your machine
The automated specs pass here; please sanity-check once that they pass for you (servers auto-start via
the fixed `playwright.config.js`):
1. `cd frontend && npx playwright test bead_select.spec.js measurement_tool.spec.js` → expect all green.
2. Re-run with `--repeat-each=3` once → confirm non-flaky on your hardware (WSL2 timing differs).
3. Manually in the app (`just dev` + `just frontend`, load a real design): Alt-click two beads, press
   `M` → cyan line + "Distance: … nm"; press `M` again → it clears. (This is what the HARD spec automates.)
4. If a spec hangs at server start with `spawn /bin/sh ENOENT`, the dev servers aren't up AND the config
   cwd regressed — see the ledger entry on `playwright.config.js`.
