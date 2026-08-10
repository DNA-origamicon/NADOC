import { test, expect } from '@playwright/test'
import path from 'node:path'

const DESIGN = path.resolve(import.meta.dirname, '../../workspace/VoltronCore_Arm.nadoc')

test('VoltronCore Arm helix 49 blunt-end recommendation stays useful', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/?doc=__e2e__voltron-extrude-rec')
  await page.waitForSelector('#canvas')
  await page.evaluate(async designPath => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(designPath)
  }, DESIGN)

  await expect.poll(async () => {
    const ends = await page.evaluate(() => window.__nadocTest?.getDomainEndScreenPositions?.() ?? [])
    return ends.filter(e => e.helixId === 'h_sc_49').length
  }, { timeout: 60_000 }).toBeGreaterThan(0)

  const ends = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions())
  console.log('h_sc_49 ends:', ends.filter(e => e.helixId === 'h_sc_49'))
  const end = ends.find(e => e.helixId === 'h_sc_49')
  // Exercise the exact downstream action of the right-click menu deterministically.
  // Raycasting a ring in this 59-helix fixture takes minutes under SwiftShader.
  await page.evaluate(e => window.__nadocTest.openExtrudeAtEnd(e), end)
  await expect(page.locator('#extrude-panel')).toBeVisible()

  const recommendations = await page.locator('#slice-scaffold-rec .rec-chip').evaluateAll(chips =>
    chips.map(c => ({ bp: c.dataset.bp == null ? null : Number(c.dataset.bp), text: c.textContent.trim() })))
  console.log('Voltron helix 49 recommendations:', recommendations)
  expect(recommendations).toHaveLength(2)
  expect(recommendations[0].bp).toBe(7235)
  expect(recommendations[1].bp).toBe(8050)
})
