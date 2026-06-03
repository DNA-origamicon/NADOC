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
| 1 | | EASY | `_bundleAxisRange/_bundleMaxOffset/_bundleMidOffset` (+`_flexibleRunForBead`) → `scene/bundle_geometry.js` | | | | | | |
| 2 | | MEDIUM | `_quatToEulerDeg/_eulerDegToQuat/_extractJointAngleDeg` → `scene/rotation_math.js` | | | | | | |
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

(append observations here as pilots run — surprises, closure captures discovered, test-pattern friction)
