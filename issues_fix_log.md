# Issues fix log

Tracks the "fix next issue" loop (backlog + protocol in `issues_ledger.md`). One row per phase shipped,
one commit per phase. Mirrors `main_js_extraction_log.md` for the carve-up.

**Why this exists:** to keep bug-fixing on the same disciplined rails as the carve-up — repro-first,
test-pinned, routed through extracted modules (NOT back into main.js), gated by vitest + smoke + app
exercise — and to measure whether the loop is actually tight (wall-clock, edits-to-green, did a phase
regress anything).

## Baselines (at loop start, 2026-06-05)

- `frontend/src/main.js` LOC: 9600
- vitest spec count: 725 (66 files) — NOTE: actual count at first run was **906 (75 files)**; the 725
  baseline was stale at ledger creation. Use 906 as the real pre-ISSUE-3 baseline.
- Open issues: 4 (ISSUE-1 context menus, ISSUE-2 cross-tab sync, ISSUE-3 ctrl-click, ISSUE-4 drill)
- Backend test count: ~1786 (frontend-only fixes don't touch it)

## Metrics per phase

| # | Date | Issue / phase | What changed (module) | Repro pinned by | Wall-clock | main.js LOC Δ | tests added | edits-to-green | app-validated | regression caught |
|---|------|---------------|------------------------|-----------------|-----------|---------------|-------------|----------------|---------------|-------------------|
| 1 | 2026-06-05 | ISSUE-3 (single phase) — Ctrl+click multi-select feedback + toggle semantics | `scene/assembly_lasso.js` (new pure `toggleInstanceSelection`), `scene/assembly_multi_box.js` (white-for-1 / purple-for-2+, relaxed ≥2 gate), main.js `onClick` re-wired to the helper | vitest (`toggleInstanceSelection` ×6, `assembly_multi_box` color cases) + e2e `assembly_select.spec.js` ISSUE-3b (real raycast, discriminating) | ~1 session | **+1** (dev-only `getMultiSelectedInstanceIds` oracle; onClick body net 0) | 6 unit + 1 e2e (+2 updated multi-box tests, +1 e2e helper) | clean (vitest 906 green first pass; e2e 3a/3c reframed once after discovering empty-centers fixture + gizmo occlusion) | yes — real `Belt_test1.nass` on shared renderer: white box (1 part) → purple (2 parts), `getInstanceCenters`=62 | n/a (no prior phase) |
| 2 | 2026-06-05 | ISSUE-2 (Phase 1 repro+ask + propagation fix) — different-doc same-file tabs didn't cross-sync | `app/lifecycle.js` (new `registerSiblingSave(path, sameDoc)` — doc-scoped echo guard), main.js `file-saved` handler re-wired to it | vitest `app/lifecycle.test.js` ×3 (same-doc suppresses; **different-doc reloads = repro**; 5 s clear) + USER TODO two-real-tab app check | ~1 session | **−4** (9-line inline echo block → 1 call) | 3 unit | clean (vitest 909 green first pass; smoke 23/23) | **USER TODO** — two-real-tab gesture (BroadcastChannel can't cross Playwright contexts; see difficulties) | n/a |

**Column notes:**
- **Repro pinned by** — the failing-then-passing test that defines "fixed": `vitest` / `e2e (scene_harness)` /
  `USER TODO` (un-automatable, user-confirmed — log it explicitly, like the carve-up's accepted caveats).
- **main.js LOC Δ** — should be **≤ 0**. A positive delta means the fix grew the closure; justify it
  (rare: a one-line wiring tweak) or refactor. Prefer routing the fix through an extracted module.
- **app-validated** — minutes of manual app exercise, or "USER TODO" if handed to the user.

## Difficulties ledger

_Append a dated entry whenever a phase hits a dead-end, a surprising root cause, a flaky repro, or a
"the obvious fix was wrong" moment. Future sessions read this to avoid re-paying the cost. Empty at
creation._

**ISSUE-3 (2026-06-05) — empty-centers fixture + gizmo occlusion blocked two of three e2e repros.**
The inline `loadAssemblyWithParts` fixture has an empty renderer bounding box, so `getInstanceCenters()`
returns `[]` and `instanceUnionBox` returns null → the multi-select box NEVER materializes in that e2e at
any selection count. So the box's white/purple rendering can't be asserted in e2e — it's pinned by the
vitest unit test (mocked centers) instead. Separately, the move/rotate gizmo auto-arms on plain-click and
occludes the second rod in the tight fixture, so "plain-click A then Ctrl+click B → both" can't be driven
either (pinned by `toggleInstanceSelection` unit test). Net: only the "Ctrl+click the active part toggles
it off cleanly" case is both e2e-drivable AND discriminating (pre-fix left a phantom size-1 multi-set).
Lesson: for assembly visual/center-dependent behavior, app-verify on a REAL `.nass` via
`__NADOC_DBG__.{store,assemblyRenderer}` + `importAssembly` (centers ARE populated there — 62 for
Belt_test1); the inline e2e fixture is only good for pick/selection-STATE wiring.

**ISSUE-2 (2026-06-05) — the obvious repro (2-context Playwright) cannot reproduce the bug; root cause was a doc-id split, not the suppression-window the dossier suspected.**
The ledger's hypothesis pointed at `_RELOAD_SUPPRESS_MS = 10000` (the `markSameDocActivity` window). That
was wrong: that window is only armed by a *same-doc* `design-changed`, which the two failing tabs (different
sticky doc ids) never exchange. The real defeater was the `file-saved` cross-tab echo guard in `main.js`
adding the path to `selfSavedPaths` with NO doc check — so a different-doc sibling's genuine save was
treated as a self-echo and its SSE `file-changed` reload was dropped. Also: the handoff's suggested
acceptance test (two `browser.newContext()` on the same `?doc`) can't reproduce it — `BroadcastChannel`
does not cross Playwright contexts, so tab B never gets the `file-saved` echo and the reload fires even on
the buggy code. The bug needs two REAL same-browser tabs (shared BroadcastChannel) with DIFFERENT doc ids.
Pinned the logic with `registerSiblingSave` unit tests instead; app-verification is a two-real-tab USER TODO.
Lesson: trace the doc-id/broadcast/SSE interplay before trusting a suppression-window hypothesis, and check
whether your repro harness even shares the channel the bug rides.

**Loop conventions banked at creation (2026-06-05):**
- **Repro before fix, ask before implement.** The two non-negotiables. A bug without a reproducing test
  is not ready to fix; a UX bug without the user's chosen target behavior is not ready to implement.
- **`rg`, not `grep`, on main.js** — grep's binary heuristic trips on some byte in the file and silently
  returns zero matches (carried over from the carve-up loop, where it cost ~5 tool calls).
- **`just lint` is Python-only** (`ruff check backend/ tests/`), currently ~38 pre-existing errors unrelated
  to frontend; a frontend-only fix has lint delta 0 by construction. No eslint config exists for the frontend.
- **`just smoke` is two gates** (console-error render + teardown) — run it for any DOM/scene/store fix.
- **Don't grow main.js** — see the prime-directive section in `issues_ledger.md`. If the buggy code is
  still inline, extract-then-fix (carve-up) or minimal-patch-then-log-as-extraction-target.
