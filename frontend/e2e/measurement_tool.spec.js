/**
 * Measurement tool — interactive gesture e2e (HARD-tier template), v2 on the
 * shared scene-harness.
 *
 * The path unit tests + the console-error smoke gate CANNOT cover: real Alt-click
 * bead selection → 'M' keypress → measurement line + readout, driven through
 * selection_manager and the main.js shortcut wiring.
 *
 * v2 change: the load + the alt-pick-two-beads retry now live in the reusable
 * harness (loadScaffoldedPart + altPickBeads) instead of being copy-pasted here.
 * The robustness comes from state-feedback retry (a missed click on a small bead
 * clears the set, so we keep clicking candidates until the count reaches 2).
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, altPickBeads } from './helpers/scene_harness.js'

// Match the measurement line by its cyan colour (0x00e5ff) — other overlays may
// also use renderOrder 999, so that alone is too loose.
const hasMeasureLine = (page) => page.evaluate(() => {
  let found = false
  window.__nadocTest.scene.traverse(o => {
    if (o.isLine && o.material?.color?.getHex?.() === 0x00e5ff) found = true
  })
  return found
})

test.describe('Measurement tool — interactive gesture', () => {
  test('Alt-pick two beads + M shows a distance readout; M again clears it', async ({ page }) => {
    await loadScaffoldedPart(page, { doc: 'e2e-measure', name: 'measure-gesture' })

    const count = await altPickBeads(page, 2)
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
