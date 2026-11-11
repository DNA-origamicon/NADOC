import { test, expect } from '@playwright/test'

// Caller owns isolated workspace and removes it in finally. Source is read-only.
// Intercept preparation/start: this verifies launch inputs without running dynamics.
test('submodel launch sizes its region and does not confirm duration', async ({ page }) => {
  test.skip(!process.env.NADOC_SUBMODEL_ZOOM_SOURCE, 'Requires read-only source fixture')
  test.setTimeout(180000)
  const source = process.env.NADOC_SUBMODEL_ZOOM_SOURCE
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: source }, headers: route.request().headers() })
    await route.fulfill({ response })
  })
  const intercepted = []
  await page.route(/\/api\/md\/jobs\/[^/]+\/(prepare|start)(\?.*)?$/, async route => {
    intercepted.push(route.request().postDataJSON())
    await route.fulfill({ status: 409, json: { detail: 'Test stopped before preparation; no dynamics launched.' } })
  })
  await page.goto('/?debug=1&doc=__e2e__submodel-zoom&open=Submodel_tests.nadoc')
  await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_SUBMODEL__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30000 })
  for (const label of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const close = page.getByRole('button', { name: label, exact: true })
    if (await close.count()) await close.first().click()
  }
  await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  const box = { min_corner:[3.7487173471166066,-1.5831412905105324,11.705349921961698],
    max_corner:[11.22386897691828,6.082134180594805,18.144822657206035], rotation:[0,0,0,1], shell_nm:2, visible:true }
  const created = await page.request.post('/api/md/jobs', {
    headers: { 'X-NADOC-Doc': '__e2e__submodel-zoom' },
    data: { draft:true, design_source_path:'Submodel_tests.nadoc', submodel:box, threads:16, relax_preset:'standard', gpu_resident:'off', padding_nm:2 },
  })
  expect(created.ok(), await created.text()).toBe(true)
  const job = await created.json()
  await page.evaluate(async id => { await window.__nadocMdPanel.refresh(); await window.__nadocMdPanel.selectJob(id) }, job.job_id)
  const forecasts = {}
  for (const endpoint of ['preflight-vram', 'estimate-disk']) {
    await page.route(`**/api/md/jobs/${endpoint}`, async route => {
      expect(route.request().postDataJSON().submodel).toMatchObject(box)
      const response = await route.fetch({ timeout:120000 })
      expect(response.ok()).toBe(true)
      forecasts[endpoint] = await response.json()
      await route.fulfill({ response })
    })
  }
  await page.locator('#md-jobs-run-btn').click()
  await expect.poll(() => intercepted.length, { timeout:140000 }).toBe(1)
  expect(intercepted[0].submodel).toMatchObject(box)
  expect(forecasts['preflight-vram'].tier).toBe('ok')
  expect(forecasts['preflight-vram'].current_host_mb).toBeGreaterThan(0)
  expect(forecasts['estimate-disk'].submodel.retained_solute_atoms).toBeLessThan(forecasts['estimate-disk'].submodel.source_solute_atoms)
  await expect(page.getByText('Long run — start it?', { exact:true })).toHaveCount(0)
  // Explicit multi-day input also bypasses confirmation in the running application.
  expect(await page.evaluate(async () => {
    const { confirmBigRunOk } = await import('/src/ui/job_activity.js')
    return confirmBigRunOk({ predicted_bytes:1.6*1024**3, est_hours:407 })
  })).toBe(true)
  console.log('FORECAST', JSON.stringify(forecasts))
})
