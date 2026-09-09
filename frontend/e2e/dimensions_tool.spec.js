/** Real gesture coverage for CAD-style Dimensions in parts and assemblies. */
import { test, expect } from '@playwright/test'
import {
  beadCandidates,
  loadAssemblyWithParts,
  loadScaffoldedPart,
  trackConsoleErrors,
} from './helpers/scene_harness.js'

const dimensionLineCount = page => page.evaluate(() => {
  let count = 0
  window.__nadocTest.scene.traverse(object => {
    if (object.isLine && object.parent?.userData?.isDimension) count++
  })
  return count
})

async function pickTwoDimensionBases(page) {
  const candidates = await beadCandidates(page)
  let count = 0
  const used = []
  for (const point of candidates) {
    if (used.some(old => Math.hypot(old.x - point.x, old.y - point.y) < 8)) continue
    await page.mouse.click(point.x, point.y)
    await page.waitForTimeout(100)
    const next = await page.evaluate(() => window.__nadocTest.getCtrlBeadCount())
    if (next > count) used.push(point)
    else if (next < count) used.length = 0
    count = next
    if (count === 2) return count
  }
  return count
}

test('D opens Dimensions; two ordinary base clicks create and record a dimension', async ({ page }) => {
  test.setTimeout(60_000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: 'e2e-dimensions-part', name: 'dimensions-part' })

  await page.keyboard.press('d')
  await expect(page.locator('#right-tab-content-properties')).toBeVisible()
  await expect(page.locator('#dimensions-body')).toBeVisible()
  // The test harness starts with the sidebar collapsed; opening it changes the
  // viewport width, so frame the design in the newly visible canvas area.
  await page.keyboard.press('f')
  await page.waitForTimeout(300)
  const picked = await pickTwoDimensionBases(page)
  expect(picked).toBe(2)
  await expect(page.locator('#dimensions-record')).toBeEnabled()
  await expect(page.locator('.dimensions-row')).toHaveCount(0)
  expect(await dimensionLineCount(page)).toBe(0)

  await page.locator('#dimensions-record').click()
  await expect(page.locator('.dimensions-row')).toHaveCount(1)
  await expect(page.locator('.dimensions-row__name')).toHaveText('Dimension 1')
  expect(await dimensionLineCount(page)).toBe(1)

  await page.keyboard.press('Escape')
  await expect(page.locator('#dimensions-body')).toBeHidden()
  expect(await dimensionLineCount(page)).toBe(1) // recorded overlays persist

  await page.keyboard.press('d')
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await expect(page.locator('#dimensions-body')).toBeHidden()
  expect(await page.evaluate(() => window.__nadocTest.dimensions.isPickingBases())).toBe(false)

  await page.keyboard.press('d')

  await page.locator('.dimensions-row [aria-label="Hide dimension"]').click()
  expect(await page.evaluate(() => window.__nadocTest.dimensions.measurements()[0].visible)).toBe(false)
  await page.locator('.dimensions-row [aria-label="Delete dimension"]').click()
  expect(await page.evaluate(() => window.__nadocTest.dimensions.measurements())).toEqual([])

  await page.evaluate(() => document.getElementById('menu-file-close-session')?.click())
  await expect.poll(() => page.locator('#dimensions-body').isHidden()).toBe(true)
  expect(await page.evaluate(() => window.__nadocTest.dimensions.isPickingBases())).toBe(false)
  expect(errors, errors.join('\n')).toEqual([])
})

test('assembly Dimensions creates two movable gizmos with a live updating distance', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await loadAssemblyWithParts(page, { doc: 'e2e-dimensions-assembly', n: 2, name: 'dimensions-assembly' })

  await page.keyboard.press('d')
  await expect(page.locator('#dimensions-body')).toBeVisible()
  const endpoints = await page.evaluate(() => window.__nadocTest.dimensions.endpoints())
  expect(endpoints).toHaveLength(2)
  const before = await page.evaluate(() => window.__nadocTest.dimensions.measurements()[0].distance)

  await page.evaluate(() => window.__nadocTest.dimensions.setEndpoint(1, [20, 0, 0]))
  const after = await page.evaluate(() => window.__nadocTest.dimensions.measurements()[0].distance)
  expect(after).not.toBe(before)
  await page.locator('#dimensions-record').click()
  expect(await page.evaluate(() => window.__nadocTest.dimensions.measurements().length)).toBe(2)

  // Closing removes the editable live line/gizmos but preserves the recorded line.
  await page.locator('#dimensions-heading').click()
  expect(await page.evaluate(() => window.__nadocTest.dimensions.measurements().length)).toBe(1)
  expect(await dimensionLineCount(page)).toBe(1)

  // Regression: Clear followed by close must not let TransformControls disposal
  // recreate the live line.
  await page.keyboard.press('d')
  await page.locator('#dimensions-clear').click()
  await page.locator('#dimensions-heading').click()
  expect(await page.evaluate(() => window.__nadocTest.dimensions.measurements())).toEqual([])
  expect(await dimensionLineCount(page)).toBe(0)
  expect(errors, errors.join('\n')).toEqual([])
})
