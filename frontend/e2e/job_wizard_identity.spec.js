import { test, expect } from '@playwright/test'

// Caller owns/removes isolated workspace and source link; no molecular authoring.
test('job wizard header identifies original and copied jobs', async ({ page }, info) => {
  test.skip(!process.env.NADOC_SUBMODEL_ZOOM_SOURCE, 'Requires read-only source fixture')
  test.setTimeout(150000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const source = process.env.NADOC_SUBMODEL_ZOOM_SOURCE
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: source }, headers: route.request().headers() })
    await route.fulfill({ response })
  })
  await page.goto('/?debug=1&doc=__e2e__submodel-zoom&open=Submodel_tests.nadoc')
  await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_ZOOM_VOLUME__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30000 })
  for (const label of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const close = page.getByRole('button', { name: label, exact: true })
    if (await close.count()) await close.first().click()
  }
  await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  const created = await page.request.post('/api/md/jobs', {
    headers: { 'X-NADOC-Doc': '__e2e__submodel-zoom' },
    data: { draft: true, design_source_path: 'Submodel_tests.nadoc', threads: 4 },
  })
  expect(created.ok()).toBe(true)
  const original = await created.json()
  await page.evaluate(() => window.__nadocMdPanel.refresh())
  let id = original.job_id
  for (const copied of [false, true]) {
    if (copied) {
      await page.locator(`[data-job-id="${original.job_id}"]:visible`).first().click({ button: 'right' })
      const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/md/jobs/${original.job_id}/copy`))
      await page.getByText('Copy job (new seed)', { exact: true }).click()
      id = (await (await response).json()).job.job_id
    }
    await page.locator(`[data-job-id="${id}"]:visible`).first().click({ button: 'right' })
    await page.getByText('Edit…', { exact: true }).click()
    const wizard = page.locator('.modal--wizard:visible')
    await expect(wizard.locator('.modal__header .wizard-job-id')).toHaveText(`Job ID: ${id}`)
    await expect(wizard.locator('.wizard-job-id')).toHaveCSS('text-transform', 'none')
    if (copied) {
      await page.screenshot({ path: info.outputPath('wizard-job-id.png') })
      console.log('REVIEW_IMAGE', info.outputPath('wizard-job-id.png'))
      await page.waitForTimeout(20000)
    }
    await wizard.getByRole('button', { name: 'Close', exact: true }).click()
  }
  await page.locator('#md-jobs-new-btn').click()
  await expect(page.locator('.modal--wizard:visible .wizard-job-id')).toHaveCount(0)
  await page.locator('.modal--wizard:visible').getByRole('button', { name: 'Cancel', exact: true }).click()
})
