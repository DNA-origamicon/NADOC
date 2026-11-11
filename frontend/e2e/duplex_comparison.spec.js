import { expect, test } from '@playwright/test'
import { existsSync } from 'node:fs'

test.use({ deviceScaleFactor: 2 })

// Read the existing legacy part; do not construct, edit, or save a fixture.
// Session persistence is disabled by playwright.config.js. No extra artifacts.
test('duplex survives multi-view and multi-overlay', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  test.skip(!existsSync(new URL('../../workspace/duplex.nadoc', import.meta.url)), 'duplex.nadoc is not installed in this workspace')
  const errors = []
  page.on('pageerror', error => errors.push(error.stack || error.message))
  await page.goto('/?doc=e2e-duplex-comparison')
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.loadDesign('workspace/duplex.nadoc')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
  })
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.locator('#right-multi-view .mv-layout-btn[data-count="2"]').click()
  await expect(page.locator('.mv-viewport-panel[data-ready="true"]')).toHaveCount(2, { timeout: 30_000 })
  if (process.env.NADOC_COMPARISON_REVIEW) {
    await page.screenshot({ path: testInfo.outputPath('multi-view.png') })
    await page.waitForTimeout(20_000)
  }
  for (const count of [3, 4]) {
    await page.locator(`#right-multi-view .mv-layout-btn[data-count="${count}"]`).click()
    await expect(page.locator('.mv-viewport-panel[data-ready="true"]')).toHaveCount(count, { timeout: 30_000 })
  }
  await page.locator('#right-multi-overlay .mo-count-btn[data-count="2"]').click()
  await expect(page.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(2, { timeout: 30_000 })
  if (process.env.NADOC_COMPARISON_REVIEW) {
    await page.screenshot({ path: testInfo.outputPath('multi-overlay.png') })
    await page.waitForTimeout(20_000)
  }
  await page.locator('.mo-representation').first().selectOption('full')
  await expect(page.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(2, { timeout: 30_000 })
  await page.locator('#right-multi-overlay .mo-count-btn[data-count="2"]').click()
  expect(errors).toEqual([])
})
