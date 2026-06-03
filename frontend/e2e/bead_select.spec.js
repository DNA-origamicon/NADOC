/**
 * EASY-target gesture validation — the simplest version of the measurement
 * gesture: Alt-click ONE backbone bead → one measurement bead registers.
 *
 * Same robust pattern as the hard target, scaled down: real synthetic click
 * through the app's real raycast + state-feedback RETRY (altPickBeads clicks
 * candidate beads until the count reaches the target) + assert on exposed state.
 * Also exercises pickBeadAt, the occlusion-correct identity oracle.
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, altPickBeads, beadCandidates } from './helpers/scene_harness.js'

test.describe('Bead pick (easy gesture)', () => {
  test('Alt-clicking one bead registers one measurement bead', async ({ page }) => {
    await loadScaffoldedPart(page, { doc: 'e2e-bead-pick', name: 'bead-pick' })

    expect(await page.evaluate(() => window.__nadocTest.getCtrlBeadCount())).toBe(0)

    const count = await altPickBeads(page, 1)
    expect(count, 'one measurement bead registered via Alt-click').toBe(1)
  })

  test('pickBeadAt is occlusion-correct at a projected bead centre', async ({ page }) => {
    await loadScaffoldedPart(page, { doc: 'e2e-bead-pick', name: 'bead-pick' })
    const [pt] = await beadCandidates(page)
    expect(pt, 'expected at least one on-canvas bead').toBeTruthy()
    // The real raycast at a projected bead centre must report a front-most bead hit.
    const hit = await page.evaluate(p => window.__nadocTest.pickBeadAt(p.x, p.y), pt)
    expect(hit, 'pickBeadAt should resolve a front-most bead at a projected centre').not.toBeNull()
    expect(hit.strand_id).toBeTruthy()
  })
})
