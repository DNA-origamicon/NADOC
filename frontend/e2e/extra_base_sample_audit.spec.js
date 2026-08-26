import { test, expect } from '@playwright/test'

test('24hb trajectory audit renders a selectable real crossover sample', async ({ page }) => {
  test.setTimeout(180_000)
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  // This read-only audit does not exercise the background mrDNA job reconciler. Stub
  // that unrelated startup poll so the test cannot race its filesystem status writer.
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))

  await page.goto('/?doc=e2e-extra-base-sample-audit')
  await page.waitForSelector('#canvas')
  await page.evaluate(() => {
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('menu-help-extra-base-metrics-audit')?.click()
  })

  const modal = page.locator('#extra-base-metrics-audit')
  await expect(modal).toHaveClass(/visible/)
  await expect(modal.locator('.xbma-source')).toHaveValue('0', { timeout: 30_000 })
  await expect(modal.locator('.xbma-sample-crossovers option')).toHaveCount(338, {
    timeout: 120_000,
  })
  await expect(modal.locator('.xbma-sample-card')).toHaveCount(1, { timeout: 120_000 })
  await expect(modal.locator('.xbma-sample-card canvas')).toHaveCount(1)
  await expect(modal.locator('.xbma-sample-status')).toContainText('DCD frame')

  const frameInput = modal.locator('.xbma-sample-dcd-frame')
  await frameInput.fill('4554')
  await frameInput.press('Tab')
  await expect(frameInput).toHaveValue('4554')

  await modal.locator('[data-sample-representation="schematic"]').click()
  await expect(modal.locator('[data-sample-representation="schematic"]')).toHaveClass(/active/)
  await modal.locator('[data-sample-representation="atomistic"]').click()
  await expect(modal.locator('[data-sample-representation="atomistic"]')).toHaveClass(/active/)
  await modal.locator('.xbma-sample-reset').click()

  await modal.screenshot({ path: 'e2e/screenshots/extra-base-sample-audit-24hb.png' })
  await modal.locator('.xbma-sample-card').screenshot({
    path: 'e2e/screenshots/extra-base-sample-audit-24hb-pose.png',
  })
  expect(pageErrors).toEqual([])
})
