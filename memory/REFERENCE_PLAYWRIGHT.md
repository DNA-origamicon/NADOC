---
name: Playwright E2E testing patterns
description: How to write and run Playwright tests for NADOC — API patterns, server setup, common pitfalls
type: reference
originSessionId: ebee5130-b4fe-4931-8053-4e9bd2cfe8a2
---
# Playwright E2E Testing

> **When to use (policy):** Playwright is a *troubleshooting* tool, not a routine dev-cycle verification step — it is too slow for tight iteration. Use it only to (a) reproduce/isolate a specific error or bug, or (b) clarify behavior when it's unclear what the user is describing. Default frontend verification is exercising the running app directly. The patterns below apply *when* you've decided a spec is warranted. See [[playwright-fixtures-location]].

## Running tests

```bash
cd /home/joshua/NADOC/frontend

# Both servers must be running (or Playwright auto-starts them):
#   Terminal 1: just dev       (FastAPI :8000)
#   Terminal 2: just frontend  (Vite :5173)

npx playwright test e2e/autobreak_edges.spec.js --reporter=list
npx playwright test                              # all e2e tests
```

## Config

- Config: `frontend/playwright.config.js`
- Test dir: `frontend/e2e/`
- Screenshots: `frontend/e2e/screenshots/`
- Browser: Chrome at `/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe` (WSL2)
- `webServer` entries auto-start both servers if not running (`reuseExistingServer: true`)

## API interaction pattern

Tests use `page.request` for API calls — no need to navigate to the page for pure API tests:

```js
const API = 'http://localhost:8000/api'

// Create bundle
const r = await page.request.post(`${API}/design/bundle`, {
  data: { cells: [[0,0],[0,1]], length_bp: 42, name: 'test', plane: 'XY' },
})
expect(r.ok()).toBeTruthy()
const design = (await r.json()).design  // response is { design: {...} }
```

## Common pitfalls

1. **Response shape**: API returns `{ design: { helices, strands, crossovers, ... } }`. Access via `(await r.json()).design`, NOT `await r.json()` directly.

2. **Status codes**: Bundle creation returns `201` not `200`. Use `r.ok()` which checks 200-299.

3. **GET /api/design**: Returns the full design object directly (no `design` wrapper for some endpoints). Check the actual response shape.

4. **Screenshots require UI navigation**:
   ```js
   await page.goto('/')
   await page.waitForTimeout(1000)
   await page.goto('/cadnano-editor')
   await page.waitForTimeout(2000)
   await page.screenshot({ path: 'e2e/screenshots/name.png', fullPage: true })
   ```

5. **Design reload in UI**: After API mutations, trigger UI refresh:
   ```js
   await page.evaluate(() => window.dispatchEvent(new Event('nadoc:design-changed')))
   await page.waitForTimeout(500)
   ```

## 3D-canvas interaction (read before testing selection/picking)

**You cannot drive 3D click-selection via simulated clicks headlessly.** See `LESSONS.md` H7. Specifics confirmed 2026-05-31:

6. **`page.mouse` emits no pointer events.** `selection_manager` listens for `pointerdown`/`pointerup`; Playwright's `page.mouse.move/down/up` only produced mouse events here (a probe listener on `#canvas` saw `down:0, up:0`). A synthetic `PointerEvent` dispatched to the canvas *does* fire the listener, but the handler's internal raycast still resolves no hit headlessly (even when an in-page raycast at the same pixel hits). Bottom line: don't simulate canvas clicks — drive selection programmatically:
   ```js
   const dbg = window._nadocDebug           // exposes { selectionManager, overhangLinkArcs, scene }
   dbg.selectionManager.selectStrand(id)     // also .selectNucleotide(nuc)
   const sel = (await import('/src/state/store.js')).store.getState().selectedObject
   ```
   (The passing `dsdna_linker_selection.spec.js` uses exactly this.)

7. **`document.querySelector('canvas')` returns the WRONG canvas.** The first `<canvas>` in the DOM is `#dd-pathview-canvas` (0×0); other 0×0 canvases (`#plate-canvas`, `#strand-hist-canvas`) also exist. The WebGL viewport canvas is **`document.getElementById('canvas')`** (`#canvas`), which the selection manager binds to (main.js ~203).

8. **Load a design into the *tab's* doc, not the default doc.** `page.request.post('/design/load')` writes the **default** doc, but each app tab uses its own doc context (multi-document) and won't see it. Instead call the app's own client inside the page so the store syncs:
   ```js
   await page.evaluate(async (p) => {
     const a = await import('/src/api/client.js')
     await a.loadDesign(p); await a.getGeometry()
     document.getElementById('welcome-screen')?.classList.add('hidden')      // overlay; not gating selection
     document.getElementById('filter-view-strip')?.classList.remove('locked-disabled')
   }, '/abs/path/Examples/6hb_test.nadoc')
   ```
   Selection is **not** gated by the welcome screen (`isDisabled` = `slicePlane.isContinuation()` only); hiding the overlay just frees the canvas for pointer events. `f` frames-all; `__NADOC_DBG__` exposes `{ store, scene, camera, controls, THREE }`.

9. **Use a tiny design for mechanics.** Large designs (e.g. `NS_trans_fix.nadoc` ~14.7k beads) take 1.5+ min to load+build geometry — a single test can exceed the timeout. Use `6hb_test.nadoc` / `U6hb.nadoc` (6 helices); reserve big designs for the one distinction that needs them (e.g. sub-cluster vs default cluster).

## Test structure pattern

```js
import { test, expect } from '@playwright/test'
const API = 'http://localhost:8000/api'

test.describe('Feature name', () => {
  test('test name', async ({ page }) => {
    // 1. Create design via API
    const bundleRes = await page.request.post(`${API}/design/bundle`, { data: {...} })
    expect(bundleRes.ok()).toBeTruthy()

    // 2. Run operations via API
    const xoverRes = await page.request.post(`${API}/design/crossovers/auto`)
    expect(xoverRes.ok()).toBeTruthy()
    const design = (await xoverRes.json()).design

    // 3. Assert on data
    expect(design.crossovers.length).toBeGreaterThan(0)

    // 4. (Optional) Visual verification
    await page.goto('/cadnano-editor')
    await page.waitForTimeout(2000)
    await page.screenshot({ path: 'e2e/screenshots/feature.png', fullPage: true })
  })
})
```

## Useful helpers

**Coverage check** — verify staple nucleotide coverage:
```js
function coverage(design, bpLo, bpHi) {
  const cov = new Set()
  for (const s of design.strands) {
    if (s.strand_type === 'scaffold') continue
    for (const d of s.domains) {
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      for (let bp = Math.max(lo, bpLo); bp <= Math.min(hi, bpHi); bp++)
        cov.add(`${d.helix_id}|${bp}|${d.direction}`)
    }
  }
  return cov
}
```

**Staple direction from grid position** (HC lattice):
```js
function stapleDir(row, col) {
  return (row + col) % 2 === 0 ? 'REVERSE' : 'FORWARD'
}
```

**Terminal lookup maps** for crossover junction verification:
```js
const fivePrime = new Map(), threePrime = new Map()
for (const s of design.strands) {
  if (s.strand_type === 'scaffold' || !s.domains.length) continue
  const fd = s.domains[0], ld = s.domains[s.domains.length - 1]
  fivePrime.set(`${fd.helix_id}|${fd.start_bp}|${fd.direction}`, s.id)
  threePrime.set(`${ld.helix_id}|${ld.end_bp}|${ld.direction}`, s.id)
}
```

## Existing test files

| File | What it tests |
|------|---------------|
| `autobreak_edges.spec.js` | Edge coverage, crossover junctions, max strand length after autobreak |
| `crossover_holliday.spec.js` | Manual crossover placement, Holliday junction, coverage preservation |
| `cadnano_crosssection.spec.js` | Cross-section slice view |
| `cadnano_sliceview_positions.spec.js` | Slice view helix positions |
| `smoke.spec.js` | Basic app loading |
| `examples.spec.js` | Example design loading |
| `blunt_ends_trim.spec.js` | Blunt end trimming |
| `edge-cases.spec.js` | Various edge cases |
