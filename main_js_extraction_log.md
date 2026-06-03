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

Singletons (do one when convenient): `_clusterTransformAfterJointDelta` (cluster_joint_math), the
`_format*` report helpers (aksel_format), `_computeGroupHiddenInstanceIds` (assembly_groups_util),
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

## Difficulties ledger (for later attempts / the autonomous loop)

Append-only. Record candidates that turned out NOT to be clean pure extractions, plus any
gotcha worth remembering. The autonomous extraction loop writes here when it skips something.

- **`_clusterBeadCount` — NOT pure (skip).** The purity-scan agent flagged it CLEAR, but it
  calls `designRenderer.getBackboneEntries()`. Left in main.js (group 6). Lesson: re-verify the
  agent's "CLEAR" rating by reading the body before extracting — the scan over-trusts signatures.
- **`_ovhgDomainBpRange` — dead (0 callers).** Removed rather than carried into a module.
- **Playwright boot gate was unrunnable on this machine** until `playwright.config.js` cwd was
  fixed (it hardcoded `/home/jojo/Work/NADOC`). Now derived from the config file location, so
  `just smoke` / the console-error gate auto-start the servers anywhere. If the gate ever fails
  with `spawn /bin/sh ENOENT`, the servers are down AND the cwd is wrong again.
- **Other backlog impure exclusions (do NOT extract):** `_applyFKLive`, `_applyGearLive*`
  (assemblyRenderer); `_filterAtomData` (`_atomDataCache`); `_rebakeHelixAxesForClusterDelta`
  (`store`); `_effectiveInstanceMatrix` (`_assemblyPendingTransforms`); `_buildSsdnaPayload`,
  `_ooPreviewFromFields` (store/DOM); `_computeAssemblyDuplicateOffset` (assemblyRenderer).
- **Borderline singletons (need a small tweak):** `_heatmapHex` reads `_HEATMAP_MIN/MAX`
  consts → pass as params or co-locate; `_fretQuenchedDonors` reads `_FRET_DONOR_MAP`/`_FRET_R0_MAP`
  → co-locate the maps with it.
