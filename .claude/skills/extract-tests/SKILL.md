---
name: extract-tests
description: Scaffold the vitest test structure for a freshly-extracted main.js subsystem (factory or pure module), then guide filling real assertions. Use during the main.js stateful-subsystem extraction loop right after moving a region into src/{ui,scene}/<module>.js, before hand-writing its <module>.test.js. Generates structure only — never the oracle.
---

# extract-tests

Generate the **structure** of a `<module>.test.js` for a just-extracted main.js
region, using the shared test helpers. This removes the repeated boilerplate
(mock store, DOM mount, mock deps, describe skeleton) so the only work left is
the part that must stay human: **the assertions (the oracle)**.

## The bright line (read first)

This skill writes test *scaffolding*, NOT test *judgment*. A test's value is that
its expected answer comes from a source independent of the code. If the assertions
are generated from the same reading of the code under test, the test just restates
the implementation — it passes but pins nothing, and it does so *silently* (green
suite, zero protection). So:

- **Generate:** imports, `mountIds` stub, `makeDeps()` with `vi.fn()` stubs,
  `describe`/`it` blocks, `beforeEach`.
- **Author by hand:** every assertion. The oracle comes from the spec / the
  pre-extraction behavior / your understanding of what the feature *should* do —
  never from paraphrasing the function body.

For verbatim extractions the behavior is preserved by construction (you moved the
code unchanged); the tests then *confirm* that contract and lock it for the future.

## When to use

In the main.js extraction loop (see `.claude/rules/main-init.md` +
`main_js_carveup.md` + `main_js_extraction_log.md`), right after step 2/3 (module
moved + imported back), to produce the test file for step 4.

## Steps

1. **Scaffold** the skeleton from the extracted module:
   ```bash
   cd frontend
   node scripts/scaffold-tests.mjs src/ui/<module>.js > src/ui/<module>.test.js
   ```
   The generator (regex, no AST) detects: exported pure functions → one `describe`
   each; an `init…({ … })` factory → `makeDeps()` stubbing each `dep.method()` call
   (and direct-function deps as `vi.fn()`), plus a `DOM` map from the
   `getElementById` ids it queries. Tag guesses (button/input/canvas) are advisory.

2. **Fix the stubs the generator can't infer:**
   - DOM tags it guessed wrong (it defaults to `div`; clicking works on any tag,
     but use `input`/`canvas` where the factory reads `.value`/`getContext`).
   - Deps it left as `{} // TODO` — stub the methods the factory actually calls.
   - Positions/vectors that need real types (e.g. `THREE.Vector3` when the code
     calls `.distanceTo`) — plain arrays will throw.

3. **Replace every `TODO`** with a real assertion. Per export, cover: happy path,
   null/empty, and the one boundary/branch that matters. For factories: the
   no-DOM no-op, each user action (`getElementById('x').click()` →
   `expect(deps.X.method).toHaveBeenCalledWith(...)`), and each store-subscription
   branch (`store._emit({ … })` → assert the reaction).

4. **Gate:** `just test-frontend` green (≥1 assertion per pure fn). For stateful
   regions also run `just smoke` + one running-app exercise. Pure-2D-DOM panels
   need no Playwright gesture spec; WebGL-bead interactions use
   `e2e/helpers/scene_harness.js`.

## Shared helpers (import these; don't re-roll them)

- `src/test-helpers/mock_store.js` — `createMockStore(initialState)`: getState /
  setState-that-notifies / subscribe (returns unsubscribe) / `_emit`. Subscribers
  fire in registration order with `(new, prev)`.
- `src/test-helpers/factory_dom.js` — `mountIds(spec)` (array of ids → `<div>`, or
  `{id: tag}`) + `clearDom()`. `getElementById` ignores nesting, so a flat set of
  by-id elements is enough to wire a factory.
- `e2e/helpers/scene_harness.js` — `trackConsoleErrors(page)` for the throwaway
  app-exercise spec (`expect(errors).toEqual([])`); `loadScaffoldedPart` /
  `altPickBeads` for WebGL gestures.

## Pattern note (why this exists / where it's heading)

The reusable asset is **propose → validate against an authoritative oracle →
retry**, not "trust generated output". Here the oracle is `just test-frontend` +
`just smoke` + the verbatim-move discipline. The same harness shape (generate a
structured artifact, then gate it on independent validators) is the intended
foundation for later validator-gated generation features (e.g. text→design, where
the oracle becomes the topology / three-layer / crossover validators). Keep the
generate and the validate halves separate; never let the generator also be the
judge.
