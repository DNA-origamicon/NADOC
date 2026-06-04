/**
 * Reusable scene-gesture harness for WebGL e2e.
 *
 * Robust pattern (validated empirically + by research): drive a REAL synthetic
 * click through the app's REAL raycast, assert on EXPOSED STATE (`__nadocTest`),
 * and RETRY on miss. Retry is the load-bearing part: at integer pixel precision a
 * click on a small WebGL bead lands only ~half the time, so "project a point and
 * click once" is flaky — you click candidates until the state actually changes.
 *
 * `__nadocTest.pickBeadAt(x,y)` is the occlusion-correct identity oracle (the real
 * raycast — "what is front-most here?"); `getSelectedObject` / `getCtrlBeadCount`
 * are the state oracles the retry loop checks. Tier 1 (logic) lives in vitest;
 * this is Tier 2 (real interaction). Tier 3 (golden-image "does it look right")
 * is intentionally NOT here — it needs a pinned software rasterizer + per-platform
 * baselines we don't yet run in CI.
 */
import { expect } from '@playwright/test'

const API = 'http://localhost:8000/api'

/**
 * Collect browser console errors + uncaught page errors into an array.
 *
 * The stateful-extraction "one app exercise" gate is, at minimum, "drive the
 * feature and assert zero console errors". Every throwaway exercise spec opened
 * with the same three lines; this centralizes them.
 *
 *   const errors = trackConsoleErrors(page)
 *   ... exercise the feature ...
 *   expect(errors, errors.join('\n')).toEqual([])
 *
 * @param {import('@playwright/test').Page} page
 * @returns {string[]} live array, appended to as errors occur
 */
export function trackConsoleErrors(page) {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))
  return errors
}

/**
 * Boot on a PINNED ?doc, create a part, build a scaffolded 200-bp helix in that
 * same backend doc (so page.request and the tab agree — multi-doc), nudge a
 * rebuild, wait for backbone beads, then zoom past cylinder-LOD so beads are
 * full-scale + pickable. Returns once the scene has pickable beads.
 */
export async function loadScaffoldedPart(page, { doc, name = 'harness' }) {
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  // `__e2e__` prefix → global-teardown removes the auto-saved workspace file.
  await page.fill('#new-design-name', `__e2e__${name}`)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await page.waitForTimeout(500)

  await page.request.post(`${API}/design/helix-at-cell`, { data: { row: 0, col: 0, length_bp: 200 }, headers: H })
  const scf = await page.request.post(`${API}/design/auto-scaffold`, { data: {}, headers: H })
  if (!scf.ok()) {
    const { design } = await (await page.request.get(`${API}/design`, { headers: H })).json()
    await page.request.post(`${API}/design/scaffold-domain-paint`, {
      data: { helix_id: design.helices[0].id, lo_bp: 0, hi_bp: 199 }, headers: H,
    })
  }
  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: d })
    bc.close()
  }, doc)

  await page.waitForFunction(() => {
    const s = window.__nadocTest?.scene
    if (!s) return false
    let ok = false
    s.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 20_000 })
  await page.waitForTimeout(300)

  const box = await page.locator('#canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 10; i++) await page.mouse.wheel(0, -120)
  await page.waitForTimeout(600)
}

/**
 * Candidate bead client points: projected centres, with points under the menu bar
 * or side panels removed (those overlay the full-width canvas, so a click there
 * never reaches it), sorted by proximity to canvas centre (most reliably hittable
 * first). The retry loops below click through these until the state changes.
 */
export async function beadCandidates(page) {
  const box = await page.locator('#canvas').boundingBox()
  const pts = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(80))
  const rects = []
  for (const sel of ['#menu-bar', '#left-panel', '#right-panel']) {
    const b = await page.locator(sel).boundingBox().catch(() => null)
    if (b) rects.push(b)
  }
  const covered = (p) => rects.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height)
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2
  return pts.filter(p => !covered(p)).sort((a, b) => Math.hypot(a.x - cx, a.y - cy) - Math.hypot(b.x - cx, b.y - cy))
}

// NOTE on plain-click strand selection: selection_manager gates regular-click
// selection by `selectableTypes` (set via the filter UI), so a bare bead click
// won't select a strand in a default/fresh part. The Alt-click measurement-bead
// pick below is NOT gated, so it's the reliable primitive to build gesture tests
// on (and `getSelectedObject` is exposed for specs that first enable a filter).

/**
 * Alt-pick distinct beads until exactly `n` measurement beads are registered.
 * A missed Alt-click clears the set (selection_manager behaviour), so reset and
 * keep going — this state-feedback retry is what makes tiny-target clicking reliable.
 * Returns the final ctrl-bead count.
 */
export async function altPickBeads(page, n = 2) {
  const cands = await beadCandidates(page)
  let count = 0
  const used = []
  for (const b of cands) {
    if (used.some(u => Math.hypot(u.x - b.x, u.y - b.y) < 20)) continue
    await page.keyboard.down('Alt')
    await page.mouse.click(b.x, b.y)
    await page.keyboard.up('Alt')
    await page.waitForTimeout(120)
    const c = await page.evaluate(() => window.__nadocTest.getCtrlBeadCount())
    if (c > count) used.push(b); else used.length = 0
    count = c
    if (count === n) break
  }
  return count
}
