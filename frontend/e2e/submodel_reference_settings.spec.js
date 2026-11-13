import { test, expect } from '@playwright/test'
import path from 'node:path'

// Existing source + frozen settings are linked/copied into the runner's isolated
// workspace. No authoring, job creation, native preparation or execution is allowed.
test('submodel wizard previews its bound full-model settings', async ({ page }) => {
  const source = process.env.NADOC_SUBMODEL_SELECTION_SOURCE
  test.skip(!source, 'Requires isolated reference-settings review runner')
  test.setTimeout(120000)
  let mutations = 0
  await page.route('**/api/md/jobs**', route => {
    if (route.request().method() !== 'GET') { mutations++; return route.abort() }
    return route.continue()
  })
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: source }, headers: route.request().headers() })
    await route.fulfill({ response })
  })
  // Resource sizing is outside this UI contract and would rebuild the full
  // atomistic geometry. Physics/provenance below come from the real plan endpoint.
  await page.route('**/api/md/protocol-box-preview', route => route.fulfill({ json: {
    calculated_nm: [21, 22, 20], selected_nm: [21, 22, 20], center_nm: [0, 0, 0],
    padding_nm: 6, box_mode: 'rotation', estimated: true, note: 'UI-test sizing placeholder',
  } }))
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto(`/?debug=1&doc=__e2e__submodel-reference&open=${encodeURIComponent(path.basename(source))}`)
  await page.waitForFunction(() => window.__nadocTest && window.__NADOC_SUBMODEL__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30000 })
  for (const name of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const close = page.getByRole('button', { name, exact: true }); if (await close.count()) await close.first().click()
  }
  await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.locator('#md-box-solvent-toggle').click()
  await page.evaluate(() => {
    const { nuc } = window.__nadocTest.getDesignRenderer().getBackboneEntries()[0]
    window.__nadocTest.selectRefsForTest([{ kind: 'base', key: `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}` }])
  })
  await page.locator('#md-submodel-from-selection').click()
  const responsePromise = page.waitForResponse(r => r.url().includes('/api/md/protocol-plan') && r.request().postDataJSON()?.submodel != null)
  await page.locator('#md-jobs-new-btn').click()
  const response = await responsePromise
  expect(response.ok()).toBeTruthy()
  const body = response.request().postDataJSON()
  expect(body.design_source_path).toBe('24hb_2xT.nadoc')
  expect(body.submodel).toBeTruthy()
  const plan = await response.json()
  expect(plan.request.submodel_reference_job_id.value).toBe('fc12195d0636')
  expect(plan.request.mg_conc_mM).toMatchObject({ value: 0, provenance: 'forced' })
  expect(plan.request.ion_conc_mM.value).toBe(0)
  for (const stage of plan.stages) {
    expect(Number(stage.params.langevindamping)).toBe(1)
    expect(Number(stage.params.timestep)).toBe(4)
    expect(stage.params.langevinpiston).toBe('off')
  }
  await expect(page.locator('.modal--wizard')).toBeVisible()
  console.log('REFERENCE_PREVIEW_VERIFIED', JSON.stringify({ reference: plan.request.submodel_reference_job_id.value, stages: plan.stages.length, mgCl2_mM: plan.request.mg_conc_mM.value, damping_ps_inv: 1, timestep_fs: 4, ensemble: 'NVT', jobMutations: mutations }))
  expect(mutations).toBe(0)
})
