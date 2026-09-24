import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

// Persistence inventory: import is in-memory with session cache disabled. Any
// incidental workspace save uses __e2e__ and is removed by global-teardown.
// Screenshots stay in Playwright output and its failure-safe cleanup reporter.
test('builds a preliminary cis-syn product through live preflight and formation', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1800, height: 1100 })
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/mrdna/jobs*', route => route.fulfill({ json: [] }))
  await page.goto('/?doc=__e2e__cpd_builder')
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.fill('#new-design-name', '__e2e__cpd_builder')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  const design = JSON.parse(readFileSync(path.resolve('../docs/examples/cpd_preliminary_duplex.nadoc'), 'utf8'))
  design.metadata.name = '__e2e__cpd_builder'
  design.photoproduct_junctions = []
  await page.evaluate(async content => {
    await window.__nadocTest.nanoparticles.importDesign(content)
    const { store } = await import('/src/state/store.js')
    const items = ['h0:5:FORWARD', 'h0:6:FORWARD'].map(key => ({ kind: 'base', key }))
    store.setState({ selection: { items, primary: items[0] } })
  }, JSON.stringify(design))
  await expect(page.locator('.cpd-form-btn')).toBeEnabled()
  await expect(page.locator('#properties-content')).toContainText('Preliminary cis-syn v6 additive parameters')
  await page.screenshot({ path: testInfo.outputPath('before-formation.png') })
  page.once('dialog', async dialog => {
    expect(dialog.message()).toContain('Preliminary cis-syn v6 additive parameters')
    await dialog.accept()
  })
  await page.locator('.sidebar-column[data-panel-type="properties"] .cpd-form-btn').first().click()
  await expect(page.locator('#properties-content')).toContainText('Formed product')
  await page.evaluate(async () => { await window.__nadocTest.setRepresentation('ballstick') })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getAtomisticRenderer().centroidOf() !== null)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('cpd-builder.png') })
  expect(errors).toEqual([])
})

// Optional retained evidence lives only in the caller's development-artifact directory.
test.afterEach(async ({ page }) => {
  if (process.env.NADOC_CPD_EVIDENCE_DIR) {
    await page.screenshot({ path: path.join(process.env.NADOC_CPD_EVIDENCE_DIR, 'builder-app.png') })
  }
})
