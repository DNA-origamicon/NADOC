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
