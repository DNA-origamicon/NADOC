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
| 3 | 2026-06-05 | ISSUE-2 sub-phase C — sync console logging silent by default | `ui/sync_badge.js` (`syncLog` console mirror gated on new `debugLogging` flag; show/hide/toggle/close drive the flag in lockstep with panel `.visible`) | vitest `ui/sync_badge.test.js` ×5 (silent default = repro; records row while silent; mirrors when panel shown; silent on hide; silent on close button) + 3 existing console-assertions updated to open panel first | ~1 session (cheap) | **0** (fix entirely in extracted module; no main.js touch) | 5 unit (net +5: 909→914) | clean (vitest 914 green first pass; smoke 23/23) | yes — live `Belt`-less boot: `__nadocSyncDebug.forceResync()` emitted 0 `[SYNC]` lines with panel closed, 2 with `.show()` open | n/a |
| 5 | 2026-06-05 | ISSUE-1 Phase 1 — context-menu inventory + target spec (NO code; survey + AskUserQuestion) | none (doc-only): `issues_ledger.md` ISSUE-1 dossier (inventory table of 18 builders + banked spec + refined phase plan) | inventory table IS the repro (survey bug, not a single gesture) — no automated test this phase | ~½ session (cheap) | **0** (no code) | 0 | n/a | n/a (no code to validate) | n/a |
| 4 | 2026-06-05 | ISSUE-2 sub-phase B — "saved" badge co-editing (stale-sibling) indicator; closes ISSUE-2 | `ui/sync_badge.js` (compose base status + sibling count via `_render`; new `setSiblingCoediting` + pure `countCoeditingSiblings`), `index.html` (`.sync-dot.coedit` blue), main.js (doc-presence carries `workspacePath`+`docId`; `_refreshCoediting`; `doc-goodbye` emit/handler; `_setWorkspacePath` re-announces) | vitest `ui/sync_badge.test.js` ×13 (7 badge-render incl. green-only annotation/plural/revert = the fix; 6 detector incl. same-docId-excluded) | ~1 session | **+22** (thin wiring across existing doc-presence / beforeunload / setter blocks — not a new cohesive block; cohesive logic lives in `sync_badge.js`) | 13 unit (net +13: 914→927) | clean (vitest 927 green first pass; smoke 23/23) | **USER TODO** — two-real-tab gesture (BroadcastChannel can't cross Playwright contexts; same constraint as row 2) | n/a |
| 6 | 2026-06-05 | ISSUE-1 Phase 2a-binding — overhang-binding menu migrated onto the shared `createContextMenu` primitive (pure consolidation, no behavior change) | new `ui/overhang_binding_menu.js` (factory `initOverhangBindingMenu`), `ui/primitives/context_menu.js` (+reusable `danger` item flag), `styles/components.css` (+`.context-menu__item--danger`), main.js (inline `_showBindingCtx`/`_hideBindingCtx` block → 1 factory-init line) | vitest `ui/overhang_binding_menu.test.js` ×9 (renders header+Bind+Delete via `.context-menu` markup, Unbind-when-bound, danger class, unknown-id→nothing, Bind/Delete api-wiring, confirm-gated delete, hide/no-stack, auto-dismiss-on-click) | ~½ session (cheap) | **−81** (83-line inline block → 1 factory-init line; +1 import) | 9 unit (net +9: 927→936) | clean (vitest 936 green first pass; smoke 23/23) | **USER TODO** (boot/wiring exercised by smoke console-error gate; live right-click-on-binding-line not drivable — no fixture has non-empty `overhang_bindings`) | n/a |
| 8 | 2026-06-05 | ISSUE-4 Phase 1 — drill-selection current-state map + target interaction spec (NO code; survey + AskUserQuestion) | none (doc-only): `issues_ledger.md` ISSUE-4 dossier (3-mechanism current-state map + friction catalogue + banked target spec A–G + target state-machine diagram). Verified by code read that the drill is **design-editor only** (`assembly_pointer.js`/`assembly_lasso.js` have zero drill) | narrated USER TODO walkthrough = the repro (survey UX issue, not a single gesture) — no automated test this phase | ~½ session (cheap) | **0** (no code) | 0 | n/a | n/a (no code to validate) | n/a |
| 7 | 2026-06-05 | ISSUE-1 Phase 2a-orientation — overhang-orientation menu migrated onto the shared `createContextMenu` primitive (pure consolidation, no behavior change) | new `ui/overhang_orientation_menu.js` (factory `initOverhangOrientationMenu`), `ui/primitives/context_menu.js` (+reusable `{ type:'custom', el }` HTMLElement passthrough — for the rep hover-flyout the flat-item model can't express), main.js (inline `_showOverhangOrientMenu`/`_dismissOvhgMenu`/`_ovhgCtxMenu` block → 1 factory-init line, `_orientPanel` passed via lazy getter) | vitest `ui/overhang_orientation_menu.test.js` ×12 (item set + ordering, single-vs-multi gating of Set Label/Generate, Clear-All danger class, Edit/Reset/Generate/Open-Manager/Clear api-wiring, Set-Label prompt + cancel, hide/no-stack) + `ui/primitives/context_menu.test.js` ×4 (custom-item append, no-el tolerance, no-dismiss-on-inside-click, dismiss-on-outside-click) | ~½ session (cheap) | **−83** (92-line inline block → 9-line factory-init; +1 import) | 16 unit (net +16: 941→957) | clean (vitest 957 green first pass; smoke 23/23) | **USER TODO** (boot/wiring exercised by smoke console-error gate; live right-click-on-rendered-overhang WebGL raycast gesture not drivable here) | n/a |

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

**ISSUE-1 Phase 2a (2026-06-05) — the handoff's "2a = 3 menus in one phase" was wrong; the 3 design-editor menus differ a LOT in migration cost.** Verified before implementing: (1) **overhang-binding** is a clean dynamic builder → trivial `createContextMenu` migration (the only gap was no `danger` styling on the primitive — added a reusable flag). (2) **overhang-orientation** embeds a hover-flyout SUBMENU (`createRepresentationMenuItem`, shared with `selection_manager.js`) that `createContextMenu` cannot express → needs a primitive extension (a `{ type:'custom', el }` item type) FIRST. (3) **blunt-end** is not a builder at all — a static `#blunt-end-ctx-menu` HTML element with 3 heavy pre-wired handlers; converting it moves real launch logic. Lesson: for the menu-migration phases, scope ONE menu per session and read its structure before committing — "they're all just context menus" hides a 10× cost spread. The `danger` flag is now shipped and reusable for every remaining migration's destructive items.

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
