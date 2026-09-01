import { expect, test } from '@playwright/test'

test('creating an oxDNA job from an assembly closes the wizard', async ({ page }) => {
  test.setTimeout(120_000)
  const created = []
  await page.route('**/api/simulate/recommendation**', route => route.fulfill({
    json: { gpu: { busy: false }, recommendation: { engine: 'oxdna', backend: 'CUDA' }, free_cores: 4 },
  }))
  await page.route('**/api/oxdna/jobs/estimate-disk', route => route.fulfill({ json: {
    warn: false, free_bytes: 100 * 1024 ** 3, predicted_bytes: 1024,
    free_after_bytes: 100 * 1024 ** 3,
  } }))
  await page.route(/\/api\/oxdna\/jobs$/, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    created.push(body)
    await route.fulfill({ status: 201, json: {
      job_id: '__e2e__assembly-prepared', status: 'queued', backend: body.backend,
      device: body.device, design_name: 'smallO-poly', stages: [], run_config: body,
    } })
  })

  await page.goto('/?doc=__e2e__oxdna-assembly-wizard&open=smallO-poly.nass&open-type=assembly')
  await page.waitForFunction(() =>
    window.__NADOC_DBG__?.store.getState().currentAssembly?.instances?.length === 3,
  null, { timeout: 90_000 })
  await page.getByRole('button', { name: 'Simulations', exact: true }).click()
  await page.getByRole('tab', { name: 'oxDNA', exact: true }).click()
  await expect(page.locator('#oxdna-jobs-new-btn')).toBeEnabled({ timeout: 15_000 })
  await page.locator('#oxdna-jobs-new-btn').click()
  const wizard = page.locator('.modal--oxdna-wizard')
  await expect(wizard).toBeVisible()
  await wizard.locator('.wizard-tab', { hasText: 'Full configuration' }).click()
  await wizard.getByRole('button', { name: 'Create job' }).click()

  await expect.poll(() => created.length).toBe(1)
  await expect(wizard).toBeHidden()
  expect(created[0]).toMatchObject({ autostart: false })
})
