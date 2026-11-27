/** Read-only source PDF; downloaded ZIP lives in Playwright-managed temp storage.
 * No structures, screenshots or user workspace output. Existing global teardown
 * removes the isolated server bridge credential and __e2e__ caches on failure. */
import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const source = fileURLToPath(new URL('../../experiments/origami_publication_catalog/assets/sources/PMC6906287-41467_2019_13284_MOESM2_ESM.pdf', import.meta.url))
test('D014 imports module tables, traces raster and downloads unresolved evidence', async ({ page }) => {
  test.skip(!existsSync(source), 'Optional local publication corpus')
  test.setTimeout(90000)
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/'); await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.locator('#menu-help-experimental').hover(); await page.locator('#menu-help-image-evaluation').click()
  await page.locator('[data-paper]').setInputFiles(source)
  const analysisResponse = page.waitForResponse(r => r.url().endsWith('/article-reconstruction/analyze'))
  await page.locator('[data-analyze]').click()
  const analyzed = await analysisResponse
  expect(analyzed.ok(), await analyzed.text()).toBeTruthy()
  const card = page.locator('.article-design-card').filter({ hasText: 'page 45 · raster candidate' })
  await expect(card).toHaveCount(1, { timeout: 45000 })
  await expect(card).toContainText('raster color traces')
  await expect(card).toContainText('1 supported panel overlap(s)')
  await expect(card).toContainText('support scaffold/staple lane classification')
  await expect(card).toContainText('classified staple traces')
  await expect(card).toContainText('same-helix connector drawing(s)')
  await expect(card).toContainText('offset endpoint-marker observation(s)')
  await card.locator('input[type=checkbox]').check()
  await card.locator('select').first().selectOption({ index: 1 })
  await expect(card).toContainText('270 physical sequence rows')
  await expect(card).toContainText('Pal: unsupported lipid')
  await expect(card).toContainText('5Cy5: supported terminal label pending route')
  await expect(card).toContainText('toehold: labeled native overhang pending route')
  await card.getByLabel('Table modules to include in reconstruction report').selectOption(['Top_A', 'inner', 'cyl'])
  await expect(page.locator('[data-reconstruct]')).toBeEnabled()
  const responsePromise = page.waitForResponse(r => r.url().endsWith('/article-reconstruction/reconstruct'))
  const downloadPromise = page.waitForEvent('download')
  await page.locator('[data-reconstruct]').click()
  const response = await responsePromise; expect(response.ok()).toBeTruthy()
  const download = await downloadPromise
  try {
    expect(download.suggestedFilename()).toBe('reconstructed-designs.zip')
    await expect(page.locator('.article-reconstruction [data-status]')).toContainText('Downloaded reconstruction package')
  } finally { await download.delete() }
  await page.locator('.modal').filter({ has: page.locator('.article-reconstruction') }).locator('.modal__close').click()
  expect(errors).toEqual([])
})
