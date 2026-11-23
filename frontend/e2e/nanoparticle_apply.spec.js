import { expect, test } from '@playwright/test'

// Only __e2e__gold-apply.nadoc and its revision store may persist. Global teardown
// removes both, session caching is disabled, and the reporter cleans screenshots.
test('gold Apply commits once and closes the popup and gizmo, including unchanged poses', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/?doc=__e2e__gold-apply')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__gold-apply')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.metadata?.name === '__e2e__gold-apply')
  const { nanoparticle_id: id } = await page.evaluate(() => window.__nadocTest.nanoparticles.create(10))
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered().length)).toBe(1)
  await page.evaluate(id => window.__nadocTest.nanoparticles.select(id), id)
  const count = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.length)
  const before = await count()
  const popup = page.locator('.tool-popup[data-tool-panel="move-rotate-panel"]')
  await page.keyboard.press('m')
  await expect(popup).toBeVisible()
  await expect(page.locator('#mr-tx')).toBeEnabled()
  await page.locator('#mr-tx').fill('3')
  await page.locator('#mr-tx').press('Tab')
  await page.locator('#mr-apply-btn').click()
  await expect(popup).not.toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().translateRotateActive)).toBe(false)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.gizmoAttached())).toBe(false)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0]?.position)).toEqual([3, 0, 0])
  expect(await count()).toBe(before + 1)

  // Reopening without another change must also finish cleanly, without a new feature.
  await page.locator('#canvas').click({ position: { x: 10, y: 10 } })
  await page.evaluate(id => window.__nadocTest.nanoparticles.select(id), id)
  await page.keyboard.press('m')
  await expect(popup).toBeVisible()
  await page.locator('#mr-apply-btn').click()
  await expect(popup).not.toBeVisible()
  expect(await count()).toBe(before + 1)
  expect(await page.evaluate(() => window.__nadocTest.nanoparticles.gizmoAttached())).toBe(false)
  expect(errors).toEqual([])
})
