import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// No designs, native processes or tour evidence; cleanup reporter removes reports/traces.
test('Debug VR Tours exposes categories, tab commands and launch errors', async ({ page, context }) => {
  const errors = trackConsoleErrors(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/?doc=e2e-vr-tour-menu')
  await page.locator('#menu-item-debug > button').click()
  await page.locator('#menu-debug-vr-tours').click()
  const dialog = page.getByRole('dialog', { name: 'VR Tours & Tests' })
  await expect(dialog).toBeVisible()
  for (const name of ['Overview','Left sidebar','Right sidebar','Controls & layout','Properties · Dimensions','Tools · Authoring']) {
    await dialog.getByRole('tab', { name, exact: true }).click()
    await expect(dialog.getByRole('tabpanel').locator('article').first()).toBeVisible()
    await expect(dialog.getByRole('tabpanel').locator('code').first()).toContainText('uv run python -m tools.vr_workflows.')
  }
  await dialog.getByRole('tab', { name: 'Right sidebar', exact: true }).click()
  await expect(dialog.locator('article')).toHaveCount(7)
  await dialog.getByLabel('Tour mode').selectOption('validate')
  const properties = dialog.locator('article').filter({ has: page.getByRole('heading', {name:'Properties',exact:true}) })
  await expect(properties.locator('code')).toContainText('--tab right:properties --validate')
  await properties.getByRole('button', {name:'Copy command'}).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('--tab right:properties --validate')
  // The mocked conflict avoids acquiring the physical headset in the browser test.
  await page.route('**/api/vr/tours/start', route => route.fulfill({json:{detail:'Close the active VR viewer before starting an isolated tour.'},status:409}))
  await properties.getByRole('button', {name:'Run validation'}).click()
  await expect(dialog.getByRole('status')).toContainText('Close the active VR viewer')
  await page.waitForTimeout(1200)
  await expect(dialog.getByRole('status')).toContainText('Close the active VR viewer')
  await dialog.getByRole('button', {name:'Close',exact:true}).click()
  await expect(dialog).toBeHidden()
  expect(errors.filter(e=>!e.includes('409')),errors.join('\n')).toEqual([])
})
