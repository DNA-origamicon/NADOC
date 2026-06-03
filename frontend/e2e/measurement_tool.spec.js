/**
 * Measurement tool — interactive gesture e2e (HARD-tier template).
 *
 * This is the path that unit tests + the console-error smoke gate CANNOT cover:
 * the real Alt-click bead selection → 'M' keypress → measurement line + readout,
 * driven through selection_manager and the main.js shortcut wiring.
 *
 * It doubles as the reusable template for verifying other stateful tools'
 * gestures. Two things make driving the GPU scene from a headless test tractable:
 *
 *   1. Multi-document: a main-app tab with no ?doc adopts a sticky RANDOM doc id,
 *      so page.request (default doc) would hit a different document than the tab.
 *      Pin an explicit ?doc=<DOC> and stamp X-NADOC-Doc:<DOC> on API builds so
 *      both target the same backend session; emit the rebuild nudge with the same
 *      docId (the design-changed receiver scopes by isSameDoc).
 *   2. Dev-only test hooks on window.__nadocTest:
 *        getBackboneBeadScreenPositions(maxN) → screen {x,y} of visible beads
 *        getCtrlBeadCount() → number of Alt-picked measurement beads
 *
 * Pattern for a new gesture test: load a design into a pinned ?doc, locate the
 * on-screen targets via a __nadocTest hook, drive the real input, then assert on
 * visible DOM + the scene graph.
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:8000/api'
const DOC = 'e2e-measure' // stable doc id shared by the tab and page.request

const docHeaders = { 'Content-Type': 'application/json', 'X-NADOC-Doc': DOC }

// New Part (dismiss welcome), then build one scaffolded 200-bp helix via the API
// in the SAME document, so the scene has a sparse, easily-clickable bead row.
async function buildScaffoldedPart(page, name) {
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await page.waitForTimeout(500)

  await page.request.post(`${API}/design/helix-at-cell`, {
    data: { row: 0, col: 0, length_bp: 200 }, headers: docHeaders,
  })
  // auto-scaffold needs a routable bundle and 422s on a lone helix; fall back to
  // painting a scaffold domain directly so the strand (and its beads) exist.
  const scf = await page.request.post(`${API}/design/auto-scaffold`, { data: {}, headers: docHeaders })
  if (!scf.ok()) {
    const { design } = await (await page.request.get(`${API}/design`, { headers: docHeaders })).json()
    await page.request.post(`${API}/design/scaffold-domain-paint`, {
      data: { helix_id: design.helices[0].id, lo_bp: 0, hi_bp: 199 }, headers: docHeaders,
    })
  }

  // page.request bypasses the frontend API client; nudge a rebuild via the same
  // doc-scoped BroadcastChannel the editor uses (docId must match the tab's doc,
  // and source must differ from the tab's own id so it isn't ignored as an echo).
  await page.evaluate((doc) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: doc })
    bc.close()
  }, DOC)

  await page.waitForFunction(() => {
    const scene = window.__nadocTest?.scene
    if (!scene) return false
    let ok = false
    scene.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 20_000 })
  await page.waitForTimeout(300) // settle one frame for LOD/visibility
}

// Drop points that fall inside the menu bar or either side panel — those overlay
// the canvas, so a click there never reaches #canvas (and the gesture is lost).
async function filterUncovered(page, pts) {
  const rects = []
  for (const sel of ['#menu-bar', '#left-panel', '#right-panel']) {
    const b = await page.locator(sel).boundingBox().catch(() => null)
    if (b) rects.push(b)
  }
  const covered = (p) => rects.some(r =>
    p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height)
  return pts.filter(p => !covered(p))
}

// Match the measurement line specifically by its cyan colour (0x00e5ff) — other
// overlays may also use renderOrder 999, so that alone is too loose.
const hasMeasureLine = (page) => page.evaluate(() => {
  let found = false
  window.__nadocTest.scene.traverse(o => {
    if (o.isLine && o.material?.color?.getHex?.() === 0x00e5ff) found = true
  })
  return found
})

test.describe('Measurement tool — interactive gesture', () => {
  test('Alt-pick two beads + M shows a distance readout; M again clears it', async ({ page }) => {
    await page.goto(`/?doc=${DOC}`)
    await buildScaffoldedPart(page, 'measure-gesture')

    // Zoom in so beads render at the bead LOD (large, individually pickable) — at
    // the default framing the helix is small/cylinder-LOD and clicks miss.
    const box = await page.locator('#canvas').boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    for (let i = 0; i < 10; i++) await page.mouse.wheel(0, -120)
    await page.waitForTimeout(600)

    const beads = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(60))
    expect(beads.length, 'expected visible backbone beads to click').toBeGreaterThan(1)
    // The side panels + menu bar overlay the (full-width) canvas, so beads that
    // project under them aren't clickable — the pointer event goes to the panel,
    // not #canvas. Keep only beads in open canvas, central ones first (an Alt-click
    // that MISSES a bead calls _clearCtrlBeads, so every click must land a hit).
    const clickable = await filterUncovered(page, beads)
    expect(clickable.length, 'expected ≥2 beads in open canvas (not under panels)').toBeGreaterThan(1)
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2
    clickable.sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy))

    // Alt-click central, well-separated beads until exactly two register. A miss
    // resets the set to 0, so we re-pick rather than assume both first clicks hit.
    let count = 0
    const used = []
    for (const b of clickable) {
      if (used.some(u => Math.hypot(u.x - b.x, u.y - b.y) < 20)) continue // distinct beads only
      await page.keyboard.down('Alt')
      await page.mouse.click(b.x, b.y)
      await page.keyboard.up('Alt')
      await page.waitForTimeout(120)
      const c = await page.evaluate(() => window.__nadocTest.getCtrlBeadCount())
      if (c > count) { used.push(b) } else { used.length = 0 } // hit grows the set; a miss clears it
      count = c
      if (count === 2) break
    }
    expect(count, 'two measurement beads selected via Alt-click').toBe(2)

    // Press 'M' → cyan line + "Distance: X.XXX nm" readout.
    await page.keyboard.press('m')
    const readout = page.getByText(/^Distance: [\d.]+ nm$/)
    await expect(readout).toBeVisible()
    expect(await hasMeasureLine(page), 'a measurement line should be in the scene').toBe(true)

    // Press 'M' again → measurement clears.
    await page.keyboard.press('m')
    await expect(readout).not.toBeVisible()
    expect(await hasMeasureLine(page), 'measurement line should be removed on toggle-off').toBe(false)
  })
})
