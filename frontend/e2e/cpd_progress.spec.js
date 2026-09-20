import { expect, test } from '@playwright/test'

// Read-only modal exercise: no workspace designs, decisions, downloads or saved state.
// Server disables session cache; standard teardown/reporter removes test artifacts.
test('CPD progress shows real evidence, rotates, inspects a failed bond and closes', async ({ page }, testInfo) => {
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.goto('/')
  const help = page.locator('#menu-bar > .menu-item').filter({ has: page.locator('#menu-help-cpd-progress') })
  await help.hover(); await page.locator('#menu-help-cpd-progress').click()
  const modal = page.locator('.cpd-progress-modal')
  await expect(modal).toBeVisible()
  await expect(modal).toContainText('DNA short pilot: 6/6 assessed (pass)')
  await expect(modal).toContainText('longer sampling and convergence remain unvalidated')
  await expect(modal.locator('[data-atom]')).toHaveCount(36)
  await modal.getByLabel('Photoproduct structure').selectOption('syn-boundary-1')
  await expect(modal.locator('[data-atom]')).toHaveCount(49)
  const bond = modal.locator("[data-bond=\"1:C1'—1:N1\"]")
  await bond.focus()
  await expect(modal.locator('.cpd-progress__details')).toContainText('Independent glycosidic-bond geometry')
  await expect(modal.locator('.cpd-progress__details')).toContainText('+0.04025 Å')
  await page.screenshot({ path: testInfo.outputPath('cpd-progress.png') })
  const svg = modal.locator('svg'); const before = await modal.locator('[data-atom]').first().getAttribute('cx'); const box = await svg.boundingBox()
  await page.mouse.move(box.x + 20, box.y + 20); await page.mouse.down(); await page.mouse.move(box.x + 80, box.y + 50, { steps: 5 }); await page.mouse.up()
  expect(await modal.locator('[data-atom]').first().getAttribute('cx')).not.toBe(before)
  await modal.getByLabel('Photoproduct structure').selectOption('syn-corrected-1')
  await modal.locator("[data-bond=\"1:C1'—1:N1\"]").focus()
  await expect(modal.locator('.cpd-progress__details')).toContainText('+0.02880 Å error; before +0.02602 Å')
  await expect(modal.locator('.cpd-progress__details')).toContainText('0 newly failing bonds/angles')
  await expect(modal).toContainText('Corrected training minimum')
  await modal.getByLabel('Validation scope').selectOption('local')
  for (const id of ['syn-core-corrected', 'syn-corrected-1', 'syn-corrected-2']) {
    await modal.getByLabel('Photoproduct structure').selectOption(id)
    await expect(modal.locator('[data-atom]:not([fill="#35bd7c"])')).toHaveCount(0)
    await expect(modal.locator('[data-bond]:not([stroke="#35bd7c"])')).toHaveCount(0)
  }
  await page.screenshot({ path: testInfo.outputPath('cpd-progress-corrected.png') })
  await modal.getByLabel('Photoproduct structure').selectOption('anti-boundary-1')
  await expect(modal).toContainText('Repaired starting structure')
  await modal.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(modal).toHaveCount(0)
  expect(errors).toEqual([])
})
