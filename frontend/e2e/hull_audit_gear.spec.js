import { test, expect } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const GEAR_DESIGN = path.resolve(HERE, '../../workspace/Gear_test.nadoc')

test('recreated Gear_test has a visible, non-degenerate generalized hull', async ({ page }) => {
  test.setTimeout(90_000)
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))

  await page.goto('/?doc=e2e-hull-audit-gear')
  await page.waitForSelector('#canvas')
  await page.evaluate(async designPath => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(designPath)
  }, GEAR_DESIGN)
  await expect.poll(() => page.evaluate(() => window.__nadocTest?.viewerDiagnostic().geometryCount ?? 0), {
    timeout: 25_000,
    message: 'Gear_test geometry was not generated',
  }).toBeGreaterThan(0)

  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.locator('#menu-help-hull-audit').click()
  await expect(page.locator('#hull-audit')).toBeVisible()
  await expect(page.locator('#hull-audit .ha-panel[data-panel="candidate"] canvas')).toBeVisible()

  const newMetric = page.locator('#hull-audit .ha-metrics > div').filter({
    has: page.locator('span', { hasText: /^New$/ }),
  })
  await expect(newMetric).toBeVisible({ timeout: 45_000 })
  expect(await page.locator('#hull-audit .ha-warning').count()).toBe(0)
  const dimensions = (await newMetric.locator('small').innerText())
    .replace(/ nm$/, '')
    .split(' × ')
    .map(Number)
  expect(dimensions).toHaveLength(3)
  expect(dimensions.every(value => Number.isFinite(value) && value > 1),
    `expected a 3D candidate hull, received ${dimensions.join(' × ')} nm`).toBe(true)
  expect(pageErrors).toEqual([])
})
