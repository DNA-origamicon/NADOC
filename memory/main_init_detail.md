# main.js extraction loop — detail (on-demand)

Split out of `.claude/rules/main-init.md` on 2026-07-09 for context economy.
That rule auto-loads on every read of `frontend/src/main.js`; this file does not.
Read this only when performing a closure→module extraction.

---

## Decomposing this file (streamlined extraction loop)

`main.js` is one large `async function main()` closure (**8,059 lines measured 2026-07-30**, down
from ~16.5k but **up +245 since 2026-07-13** — feature work is re-growing it, see the status banner
in `.claude/rules/main-init.md`) — the project's worst structural debt. We shrink it by
**extraction-on-touch**: when a task
takes you into a subsystem, lift its pure parts out into a module + unit-test, then leave the stateful
wiring thin. The act of making a function unit-testable *is* the act of lifting it out of the closure.

**Current phase: stateful-subsystem extraction.** The pure-helper well is drained. The prioritized
backlog lives in `main_js_carveup.md` at the repo root; the metrics log + difficulties ledger are in
`main_js_extraction_log.md`. Read both before claiming a region.

**Do NOT declare the loop "done / composition-root maintenance" by assertion.** The three hardest clusters
(Translate/Rotate tool, Representation switcher, Atomistic/surface) were each deferred for weeks behind a
"leave it, it's glue" hand-wave before #81/#84/#86 carved them — that is the failure mode to avoid. The
carve-up map carries a **TERMINAL-STATE GATE** (in its `## Next-session handoff`): the loop may flip to
maintenance ONLY after a documented residual-coupling pass on each carved cluster (extract the leftover
cohesive sub-block, or justify it as shared glue by NAMING the ≥2 foreign consumers + the shared closure
state that splitting would fragment), the co-editing scrap is resolved, and a fresh terminal scan is clean.
"Irreducible glue" is a conclusion you earn with named consumers, never a default to stop early. **The carve-up map is SEQUENCING-ONLY**
— trust its banner text (as a locator) and tier order (as priority), but treat its LOC counts, line
numbers, deps, and "what it is" descriptions as hints to verify, never facts (it groups by banner
adjacency, which ≠ cohesion, and has been wrong about scope 5+ times — see the ⚠ callout atop the map).
Read the region and re-derive its real size/deps/scope before investing. Run each batch in a FRESH session —
token cost scales with conversation length, and those two files carry all the state a cold session
needs. Gate before investing: confirm the feature is still wanted (we built `loop_popup` with 10
tests, then deleted it an hour later as unwanted).

This **replaces** the heavyweight `refactor_prompts/` worker+followup ceremony for pure
extractions (see the note at the top of `REFACTOR_AUDIT.md`). Per extraction:

1. **Identify & tier the target** (see purity tiers below). One extraction per commit.
2. **Move verbatim** to a new/existing module under `frontend/src/` — body unchanged, exported by name.
3. **Import it back** into `main.js` at the original call sites.
4. **Write ≥1 vitest test per extracted pure function** (input→output). **Scaffold the structure with
   the `extract-tests` skill** (`node frontend/scripts/scaffold-tests.mjs src/<area>/<module>.js`) — it
   emits imports + `mountIds` DOM stub + `makeDeps()` `vi.fn()` stubs + empty `describe`/`it` blocks, so
   you only write the assertions. **Generate structure, never the oracle** — auto-written assertions just
   restate the code and pin nothing; the expected values come from the spec / pre-extraction behavior, by
   hand. Shared helpers (import, don't re-roll): `src/test-helpers/mock_store.js` (`createMockStore`),
   `src/test-helpers/factory_dom.js` (`mountIds`/`clearDom`), `e2e/helpers/scene_harness.js`
   (`trackConsoleErrors`). Reference patterns: pure math/data → `src/scene/cluster_gizmo.test.js` (real
   module + real THREE, no mocks); factory/DI → `src/ui/strand_groups_panel.test.js` /
   `src/scene/fret_checker.test.js` (createMockStore + mountIds + mock deps, drive clicks/`_emit`).
   **Test-ordering — prove the pin for ADAPTED code.** A test written against the *moved* code that passes
   first-run only proves behavior preservation for a **verbatim lift** (byte-identical body — the move
   itself is the proof). For **adapted** code — get/set shims, alias rewiring, lazy-arrow wrapping, any
   non-byte-identical change — "green first run" is a *non-signal*, not a virtue: either (a) get the test
   green against the symbol **in its original location**, then move test + code together, or (b) if already
   moved, run the new test once against a `git stash`'d copy of the old code and confirm it passes there
   too (a test that can't pass against the pre-move code isn't pinning shared behavior). Record which
   method in the log row. *(A periodic Stryker mutation run over `src/scene`+`ui` is the objective audit
   that these pins actually assert behavior rather than restating it — a survived mutant on a new pin test
   = a missing assertion; run it out-of-band, not in the per-commit gate.)*
5. **Gate:** `just test-frontend` green; `just lint` delta ≤ 0. Iterate with `just test-frontend-watch`.
   **"Done" is coupling + cohesion, not LOC.** An extraction is done when the new module has **one reason
   to change** and a **small, countable dep surface** (the dep list you write in the log row) — LOC-Δ is
   narrative only, never the goal. A drop in LOC with coupling unchanged just relocated the problem.
6. **Stateful extractions only** (touch DOM/scene/store): also exercise the feature once in the
   running app **and** run `just smoke` before committing. Pure extractions skip this — vitest green
   is sufficient. `just smoke` is two gates now: the **console-error render gate** (boots + renders a
   real design, asserts nothing throws) **and** the **teardown gate** (design close-session + assembly
   exit — added 2026-06-04 because teardown was a blind spot; #34's const-reassignment TypeError on
   assembly exit escaped the render-only gate). **#34-class discipline:** when an extraction converts a
   raw scene-object closure var into a `const` factory, grep its teardown/reassignment sites
   (`scene.remove`, `.geometry`/`.material` pokes, `= null`) — the smoke teardown gate now catches the
   `_resetForNewDesign` + assembly-exit paths, but a teardown site OUTSIDE those two still escapes.
7. **Route findings into the sibling loops (push, don't let them get mined):** the carve-up shares its
   discipline with two other ledgers, and an extraction session feeds both.
   - **A bug you hit while extracting** (in the region or adjacent) → a new `ISSUE-N` dossier in
     `issues_ledger.md` (+ an `issues_fix_log.md` row and `[x]` if you fix it the same session). The
     extraction *difficulties ledger* is for extraction dead-ends only — a user-facing bug logged there
     is invisible to the fix loop.
   - **A stateful/gesture region you shipped without hand-checking its live gesture/visual** (the "NOT
     hand-driven" caveat) → a PENDING `MV-N` row in `manual_validation_debt.md` (manual op + which
     extractions it discharges + a fixture hint). Push it; don't rely on the validation loop re-mining
     it from the metrics column.

### Gesture validation for stateful/HARD extractions (the WebGL-canvas tier)

The scene is one GPU canvas — you can't query it like DOM. For tools whose behaviour is an
interaction (click/drag/keypress on rendered beads), use the shared harness
`frontend/e2e/helpers/scene_harness.js` instead of hand-rolling per spec. Templates:
`e2e/bead_select.spec.js` (easy: alt-pick one bead) and `e2e/measurement_tool.spec.js` (hard:
alt-pick two + 'M' + clear).

The robust pattern (validated empirically + by research — see the deep-research notes in
`main_js_extraction_log.md`):
- **Real synthetic click through the REAL raycast**, never a fake `fireEvent` (only the real ray is
  occlusion-correct).
- **Assert on exposed state**, not pixels: dev-only `window.__nadocTest` hooks
  (`pickBeadAt` = occlusion-correct "what's front-most here?", `getCtrlBeadCount`, `getSelectedObject`,
  `scene`). These are gated behind `import.meta.env.DEV` — never shipped.
- **RETRY on miss is load-bearing.** At integer-pixel precision a click on a small WebGL bead lands
  only ~half the time, so "project a point and click once" is flaky. Click candidate beads until the
  *state* changes (`altPickBeads` / the count loop). Pre-verifying the pixel does NOT replace this.
- **Gotchas baked into the harness:** pin an explicit `?doc` and stamp `X-NADOC-Doc` on `page.request`
  builds (multi-doc); plain-click *strand selection* is gated by `selectableTypes`, so build gesture
  tests on the (ungated) Alt-click measurement pick; filter candidate points under `#menu-bar` /
  side panels (they overlay the canvas); zoom past cylinder-LOD so beads are pickable.
- **Tier 3 (golden-image "does it look right") is deliberately NOT automated** — it needs a pinned
  software rasterizer (SwiftShader/llvmpipe) + per-platform baselines we don't run in CI yet.
  Appearance correctness stays a human-eye check until that infra exists.
- **Cleanup policy:** any e2e that creates a part/assembly via File>New auto-saves it to `workspace/`
  (gitignored). Name such parts with the `__e2e__` prefix (the harness's `loadScaffoldedPart` does this;
  do the same in any new gesture spec) so the Playwright `globalTeardown`
  (`e2e/global-teardown.js`) removes `workspace/__e2e__*.{nadoc,nass}` after the run. Never leave
  test parts behind.

**Purity tiers** (decide before moving):
- **Pure, already top-level** (outside the closure): trivial — move + test, zero behavioral risk.
- **Pure, inside the closure**: lift out, pass inputs explicitly; confirm it captures nothing from the
  closure (no `scene`/`camera`/`renderer`/`store`/DOM references) — if it does, it's not this tier.
- **Stateful cluster** (a dialog/tool/panel-wiring block): extract to a factory
  `initX({ scene, store, ... })` returning a small API (mirror `initEndExtrudeArrows`); needs the
  step-6 gate.

**Hard rule:** preserve store-subscription *registration order* (see below) when lifting anything that
subscribes — re-register at the same point in `main()`. Reordering subscribers silently breaks the
position-overlay invariants documented in this file.

**Factory-init placement (recurring — #26/#32/#52).** A `const x = initX({...})` is NOT hoisted, so it
must sit where its deps already exist AND before any code that *executes* one of its methods. Two cases
keep recurring: (a) **deps consumed before the factory's natural spot** (a callback registered ~1000 ln
earlier passes one of the factory's methods) → declare `let _x = null` early, assign at the real init
point, and wrap the early reference as `(...a) => _x?.method(...a)` (mirrors `onOpenPart`); (b) **the
factory's deps are declared BELOW its banner** (#52: `initFileIo` needs `_setSyncStatus`/`_syncLog`/
`libraryPanel`, all ~4000 ln below the "File open / save" banner) → place the `const` where the deps
exist (here the autosave region), NOT at the banner, and grep-verify NO boot path *calls* a method
synchronously during `main()` (every call site must be a user-action handler or a captured-for-later
ref). A ref captured before the init line needs the lazy wrapper; one captured after can be direct.

