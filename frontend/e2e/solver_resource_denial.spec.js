// No structures/jobs are created: reject every tested POST in the browser.
// Dedicated test server disables session persistence; only Playwright reports
// can be written, and artifact-cleanup-reporter removes them after the run.
import { test, expect } from '@playwright/test'

test('solver create and restart resource refusals show a blocking popup', async ({ page }) => {
  await page.route(/\/api\/(snupi|mrdna)\/jobs(?:\/saved\/start)?$/, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({
      code: 'memory_budget_exceeded',
      detail: 'Job cannot start. RAM: estimated 80.00 GiB required; 12.00 GiB available after headroom.',
    }) })
  })
  await page.goto('/?doc=__e2e__solver_resource_denial')
  await page.waitForSelector('#canvas')
  for (const method of ['createSnupiJob', 'createMrdnaJob', 'startSnupiJob', 'startMrdnaJob']) {
    const result = await page.evaluate(async name => {
      const api = await import('/src/api/client.js')
      return api[name](name.startsWith('create') ? {} : 'saved')
    }, method)
    expect(result).toBeNull()
    await expect(page.getByText('Job start denied — insufficient resources', { exact: true })).toBeVisible()
    await expect(page.locator('.modal__body').filter({ hasText: '80.00 GiB required; 12.00 GiB available' })).toBeVisible()
    await page.getByRole('button', { name: 'OK', exact: true }).click()
    await expect(page.getByText('Job start denied — insufficient resources', { exact: true })).toHaveCount(0)
  }
})
