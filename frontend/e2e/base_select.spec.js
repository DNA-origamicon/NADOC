/**
 * Base-level selection — the `base` selectionLevel gesture set.
 *
 * Exercises the real filter button, the real raycast/magnet, and the real store pool:
 * engage the level, plain-click one bead, Ctrl-click a second, Ctrl-drag a lasso.
 * Assertions read `__nadocTest.getSelectedBaseKeys()` (the pool), never the internals.
 *
 * NOT part of the routine dev loop — this is the one app exercise the stateful
 * selection_manager change needs (that file has zero unit tests).
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

/**
 * Load a part, frame it, and zoom in far enough for beads to be separable.
 *
 * Two camera problems the shared harness leaves behind, both fatal to bead picking:
 *   1. `loadScaffoldedPart` never moves the camera, so every bead projects outside the
 *      NDC cube and `beadCandidates` returns []. `f` (fit-to-view) fixes that.
 *   2. Fitted, the whole 200-bp part spans ~24 px — all 199 beads sit inside the 80 px
 *      magnet radius, so no two clicks can resolve to different bases. Wheel-zooming to
 *      a ~670 px spread makes them individually addressable.
 */
async function loadFramedPart(page, opts) {
  await loadScaffoldedPart(page, opts)
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(300)
  const box = await page.locator('#canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < 14; i++) { await page.mouse.wheel(0, -240); await page.waitForTimeout(40) }
  await page.waitForTimeout(300)
}

/** Click the real #select-filter base button and confirm the level engaged. */
async function engageBaseLevel(page) {
  await page.locator('#select-filter .sf-btn[data-key="base"]').click()
  await page.waitForTimeout(80)
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('base')
}

const poolOf = (page) => page.evaluate(() => window.__nadocTest.getSelectedBaseKeys())

/**
 * On-canvas bead positions, sorted farthest-apart-first.
 *
 * The shared `beadCandidates` helper caps at the first 80 instances (consecutive bases on
 * one helix) and sorts by distance from the viewport centre — a set too tightly clustered
 * to address individually through the 80 px magnet. This reads the whole mesh and returns
 * a pair-friendly ordering instead.
 */
async function spreadBeads(page) {
  const box = await page.locator('#canvas').boundingBox()
  const pts = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(400))
  const inCanvas = pts.filter(p =>
    p.x > box.x + 40 && p.x < box.x + box.width - 320 &&
    p.y > box.y + 60 && p.y < box.y + box.height - 40)
  return inCanvas
}

test.describe('Base-level selection', () => {
  test('the base button engages the level and lights up', async ({ page }) => {
    await loadFramedPart(page, { doc: 'e2e-base-select', name: 'base-select' })
    await engageBaseLevel(page)
    await expect(page.locator('#select-filter .sf-btn[data-key="base"]')).toHaveClass(/active/)
  })

  test('Tab reaches base from xover, and Escape leaves it', async ({ page }) => {
    await loadFramedPart(page, { doc: 'e2e-base-tab', name: 'base-tab' })
    // strand → domain → end → xover → base
    for (let i = 0; i < 5; i++) { await page.keyboard.press('Tab'); await page.waitForTimeout(50) }
    expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('base')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(80)
    expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('default')
  })

  test('a plain click selects exactly one base; Ctrl-click adds a second', async ({ page }) => {
    await loadFramedPart(page, { doc: 'e2e-base-click', name: 'base-click' })
    await engageBaseLevel(page)
    expect(await poolOf(page)).toEqual([])

    const cands = await spreadBeads(page)
    expect(cands.length, 'expected on-canvas beads').toBeGreaterThan(0)

    // The 80px magnet means the click need not be pixel-precise.
    const first = cands[0]
    await page.mouse.click(first.x, first.y)
    await page.waitForTimeout(120)
    const one = await poolOf(page)
    expect(one, 'plain click selects exactly one base').toHaveLength(1)
    expect(one[0]).toMatch(/:/)   // an app-wide base key

    // The farthest bead on screen, so the 80px magnet can't resolve back to the first.
    const dist = (c) => Math.hypot(c.x - first.x, c.y - first.y)
    const far = cands.reduce((a, b) => (dist(b) > dist(a) ? b : a), first)
    expect(dist(far), 'need a bead beyond the 80px magnet radius').toBeGreaterThan(80)
    await page.keyboard.down('Control')
    await page.mouse.click(far.x, far.y)
    await page.keyboard.up('Control')
    await page.waitForTimeout(120)

    const two = await poolOf(page)
    expect(two.length, 'Ctrl-click is additive').toBe(2)
    expect(two[0]).toBe(one[0])   // the plain-click pick survived
  })

  test('Ctrl-click on an already-picked base removes it (toggle)', async ({ page }) => {
    await loadFramedPart(page, { doc: 'e2e-base-toggle', name: 'base-toggle' })
    await engageBaseLevel(page)
    const [b] = await spreadBeads(page)
    await page.mouse.click(b.x, b.y)
    await page.waitForTimeout(120)
    expect(await poolOf(page)).toHaveLength(1)

    await page.keyboard.down('Control')
    await page.mouse.click(b.x, b.y)
    await page.keyboard.up('Control')
    await page.waitForTimeout(120)
    expect(await poolOf(page), 'toggling the same base clears it').toHaveLength(0)
  })

  test('a Ctrl-drag lasso captures many bases at once', async ({ page }) => {
    await loadFramedPart(page, { doc: 'e2e-base-lasso', name: 'base-lasso' })
    await engageBaseLevel(page)

    const cands = await spreadBeads(page)
    const xs = cands.map(c => c.x), ys = cands.map(c => c.y)
    const x1 = Math.min(...xs), x2 = Math.max(...xs)
    const y1 = Math.min(...ys), y2 = Math.max(...ys)

    await page.keyboard.down('Control')
    await page.mouse.move(x1 - 5, y1 - 5)
    await page.mouse.down()
    await page.mouse.move((x1 + x2) / 2, (y1 + y2) / 2, { steps: 8 })
    await page.mouse.move(x2 + 5, y2 + 5, { steps: 8 })
    await page.mouse.up()
    await page.keyboard.up('Control')
    await page.waitForTimeout(200)

    const pool = await poolOf(page)
    expect(pool.length, 'lasso captured multiple bases').toBeGreaterThan(1)
    expect(new Set(pool).size, 'no duplicate keys in the pool').toBe(pool.length)
  })

  test('leaving base level and clicking elsewhere clears the pool', async ({ page }) => {
    const errors = trackConsoleErrors(page)
    await loadFramedPart(page, { doc: 'e2e-base-clear', name: 'base-clear' })
    await engageBaseLevel(page)
    const [b] = await spreadBeads(page)
    await page.mouse.click(b.x, b.y)
    await page.waitForTimeout(120)
    expect(await poolOf(page)).toHaveLength(1)

    await page.keyboard.press('Escape')          // → default level
    await page.waitForTimeout(80)
    await page.mouse.click(b.x, b.y)             // a plain click at default level
    await page.waitForTimeout(150)
    expect(await poolOf(page), 'the base pool is cleared once the level is left').toHaveLength(0)
    expect(errors, 'no console errors across the whole gesture set').toEqual([])
  })
})
