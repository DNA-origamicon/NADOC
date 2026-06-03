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
| 2 | 2026-06-03 | MEDIUM | `quatToEulerDeg/eulerDegToQuat/extractJointAngleDeg` → `scene/rotation_math.js` | ~12 min | −22 (inside closure — real shrink) | 8 (3 fns → ratio 2.7) | 1 (green first run) | 0 (pure; console-error gate auto) | none — clean |
| 3 | | HARD | measurement tool (`_measClear/_measShow` + state, main.js:940–1012) → `scene/measurement_tool.js` | | | | | | |

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

## Notes / lessons per extraction

**#1 (EASY, bundle trio):** Smooth — verbatim move + import-back + 9 vitest tests, green on first run, app boots clean.
- **Key lesson:** these were already at *module top level* (outside the `main()` closure), so the extraction shrank main.js by 16 lines but reduced the closure body by **0**. EASY top-level extractions are good for establishing the loop and growing the test tier, but the closure-shrink goal needs MEDIUM (inside-closure) extractions. Adjust expectations: don't judge progress on EASY by closure-line reduction.
- `bundleMaxOffset` had 0 callers (dead) — extracted + exported anyway to keep the API; flagged in the module for later removal.
- `_flexibleRunForBead` (the 4th candidate originally grouped here) was **deferred** — it's thematically a flexible-segment helper, not bundle-axis math. It's the natural next EASY extraction into its own module.
- Frontend has no JS linter (`just lint` is Python-only), so the lint-delta gate is N/A for `.js` extractions; vitest + console-error gate are the real gates.

**#2 (MEDIUM, rotation-math trio):** Confirmed the loop's value — the three Euler/quat/joint-angle helpers were *inside* the `main()` closure but captured nothing from it (THREE + Math only), so the lift was clean: verbatim move, rename 7 call sites (3 names), one import. **−22 lines off the closure body** — the first real closure shrink, vs EASY's 0. 8 vitest tests green on first run; app boots clean.
- The math paths (Move/Rotate fields, cluster gizmo) aren't hit on plain design load, so the console-error gate doesn't exercise them — but the move was verbatim (identical call args), and unit tests cover the math, so per the streamlined rule a pure extraction needs no manual app exercise here.
- Takeaway for scaling: MEDIUM "pure-but-trapped-in-closure" extractions are the high-value target — same near-zero risk as EASY, but they actually drain the closure. The bottleneck is finding pure functions amid the closure; a grep for inside-`main()` functions that reference only THREE/Math/args would surface the next batch.
