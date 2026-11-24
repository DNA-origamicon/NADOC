import { test, expect } from '@playwright/test'

// Read-only review. Any fallback document uses __e2e__ and global teardown;
// session caching is off. Screenshots/traces use the cleanup reporter's paths.
test('Corner comparison shows native history, exact seams and phase controls without editing the part', async ({ page }, testInfo) => {
  test.setTimeout(240000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1600, height: 1200 })
  await page.goto('/?doc=__e2e__corner-placement-review&geometryReview=corner')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(() => document.getElementById('welcome-screen')?.classList.add('hidden'))
  const snapshot = () => page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign))
  const before = await snapshot()
  const modal = page.locator('#geometry-review')
  await expect(modal).toHaveAttribute('data-case', 'corner', { timeout: 60000 })
  await expect(modal).toHaveAttribute('data-ready', 'true')
  await expect(modal.locator('canvas')).toHaveCount(4)
  await expect(modal.locator('[data-ref="construction"]')).toContainText('F3: Corner 1')
  await expect(modal.locator('[data-ref="phases"]')).toContainText('53/53')
  await expect(modal.locator('[data-ref="metrics"]')).toContainText('contacts < 0.080 nm')
  await expect(modal.locator('[data-ref="junctions"] button')).toHaveCount(12)
  await modal.getByRole('button', { name: 'Focus corner seams', exact: true }).click()
  for (const id of ['current', 'candidate', 'difference', 'defects']) {
    await modal.getByLabel(`${id} representation`, { exact: true }).selectOption('ballstick')
  }
  await modal.screenshot({ path: testInfo.outputPath('corner-atoms.png') })
  await modal.locator('[data-ref="junctions"] button').first().click()
  await modal.locator('.gr-body').evaluate(el => { el.scrollTop = 0 })
  await modal.screenshot({ path: testInfo.outputPath('corner-junction.png') })
  for (const id of ['current', 'candidate', 'difference', 'defects']) {
    await modal.getByLabel(`${id} representation`, { exact: true }).selectOption('full')
  }
  await modal.screenshot({ path: testInfo.outputPath('corner-full.png') })
  console.log('Corner review captures:', testInfo.outputPath('corner-junction.png'))
  for (const [id, title, seams] of [['corner-square', '1×8 square', 16], ['corner-hc2', '2HB honeycomb', 4], ['corner-sq2', '2HB square', 4]]) {
    await modal.getByLabel('Review case', { exact: true }).selectOption(id)
    await expect(modal).toHaveAttribute('data-case', id, { timeout: 60000 })
    await expect(modal.locator('[data-ref="title"]')).toContainText(title)
    await expect(modal.locator('[data-ref="junctions"] button')).toHaveCount(seams)
    await expect(modal.locator('canvas')).toHaveCount(4)
    await expect(modal.locator('[data-ref="defects"]')).not.toBeEmpty()
    await modal.getByRole('button', { name: 'Focus corner seams', exact: true }).click()
    await modal.screenshot({ path: testInfo.outputPath(`${id}.png`) })
  }
  console.log('All Corner controls rendered')
  // Optional bounded pause lets a developer inspect transient images before
  // the failure-safe reporter removes them; ordinary runs do not pause.
  if (process.env.NADOC_REVIEW_INSPECTION_MS) await page.waitForTimeout(Math.min(60000, Number(process.env.NADOC_REVIEW_INSPECTION_MS)))
  expect(await snapshot()).toBe(before)
  await modal.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(modal.locator('canvas')).toHaveCount(0)
  expect(errors).toEqual([])
})
