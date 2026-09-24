import { test, expect } from '@playwright/test'

// Smoke config provides disposable servers and disables session-cache writes.
// Any autosaved designs use __e2e__; global-teardown removes them after failure too.
test('Extrude from defaults to the loaded part source plane and allows an explicit choice', async ({ page }, testInfo) => {
  await page.goto('/?doc=e2e-extrude-source-plane')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__Extrude source plane')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: [[0,0],[0,1]], lengthBp: 21, plane: 'XZ', name: '__e2e__Extrude source plane' })
    const { store } = await import('/src/state/store.js')
    store.setState({ currentPlane: 'XY' })
  })
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await page.click('#menu-tools-extrude')
  const source = page.locator('#extrude-from')
  await expect(source).toBeVisible()
  await expect(source).toHaveValue('XZ')
  await source.selectOption('YZ')
  await expect(source).toHaveValue('YZ')
  expect(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentPlane)).toBe('YZ')
  await page.screenshot({ path: testInfo.outputPath('extrude-from.png') })
})
