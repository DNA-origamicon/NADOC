/** Read-only source load; edits only unsaved wizard state. No jobs/structures created. */
import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

test('temperature belongs to settings and reaches both engine stage configurations', async ({ page }) => {
  test.setTimeout(120000)
  const errors = [];const creates = []
  page.on('pageerror', e => errors.push(String(e)))
  page.on('request', r => { if (r.method() === 'POST' && /\/api\/(md|oxdna)\/jobs$/.test(new URL(r.url()).pathname)) creates.push(r.url()) })
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: process.env.NADOC_TEMPERATURE_SOURCE }, headers: route.request().headers() }); await route.fulfill({ response })
  })
  await page.goto('/?debug=1&doc=__e2e__temperature&open=2hb_1xT.nadoc&open-type=design')
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  if (!(await page.locator('#simulate-body').isVisible())) await page.click('#simulate-heading')
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await expect(page.locator('#md-box-temperature')).toHaveCount(0)
  await page.locator('#md-jobs-new-btn').click()
  let modal = page.locator('.modal--wizard:visible')
  await modal.locator('.wiz-target-card[data-target="local"] > div').first().click()
  await modal.locator('.wizard-tab', { hasText: 'Protocol & settings' }).click()
  console.log('NAMD settings opened')
  await page.evaluate(() => {
    window.__numericShortcutClicks = []
    for (const id of ['menu-routing-scaffold-ends', 'menu-routing-full-autostaple', 'menu-seq-update-routing', 'menu-seq-assign-scaffold', 'menu-seq-assign-staples', 'menu-seq-hairpin-dimer']) {
      document.getElementById(id)?.addEventListener('click', e => { window.__numericShortcutClicks.push(id);e.preventDefault();e.stopImmediatePropagation() }, true)
    }
  })
  await modal.locator('.modal__title').click()
  await page.keyboard.type('124560')
  expect(await page.evaluate(() => window.__numericShortcutClicks)).toEqual([])
  await modal.locator('.wizard-preset').filter({hasText:'Match the literature'}).click()
  let input = modal.locator('[data-job-temperature]')
  await expect(input).toBeEnabled({ timeout: 60000 })
  await expect(input).toHaveValue('300')
  await input.click();await input.press('ControlOrMeta+a');await input.pressSequentially('293.15', { delay: 100 });await expect(input).toBeFocused();await input.press('Tab')
  await expect(modal.locator('[data-job-temperature]')).toHaveValue('293.15', { timeout: 30000 })
  await expect(modal).toContainText('20.00 °C')
  console.log('NAMD temperature updated')
  expect(await page.evaluate(() => window.__numericShortcutClicks)).toEqual([])
  const screenshot = path.join(process.env.NADOC_WORKSPACE, 'typed-temperature.png')
  await page.screenshot({ path: screenshot });console.log('REVIEW_IMAGE', screenshot);await page.waitForTimeout(15000)

  await modal.locator('.wizard-tab', { hasText: 'What each stage runs' }).click()
  const row = modal.locator('.wizard-stages tr').filter({ has: page.locator('.param', { hasText: 'Temperature (K)' }) })
  await expect(row).toContainText('293.15')
  await modal.locator('.modal__actions button', { hasText: /Cancel|Close/ }).click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await page.locator('#oxdna-jobs-new-btn').click()
  modal = page.locator('.modal--oxdna-wizard:visible')
  await modal.locator('.wiz-target-card[data-target="local"] > div').first().click()
  await modal.locator('.wizard-tab', { hasText: 'Parameters & options' }).click()
  input = modal.locator('[data-job-temperature]')
  await input.click();await input.press('ControlOrMeta+a');await input.pressSequentially('293.15', { delay: 100 });await expect(input).toBeFocused();await input.press('Tab')
  await expect(modal).toContainText('20.00 °C')
  await modal.locator('.wizard-tab', { hasText: 'Full configuration' }).click()
  const text = await modal.locator('.oxdna-wizard-config').textContent()
  expect(text.match(/temperature = 293\.15K/g)).toHaveLength(3)
  await modal.locator('.modal__actions button', { hasText: /Cancel|Close/ }).click()
  expect(errors).toEqual([]);expect(creates).toEqual([])
  await fs.writeFile(path.join(process.env.NADOC_WORKSPACE, 'ui-verification.json'), JSON.stringify({errors, creates, oxdnaTemperatureStages:3}))
})
