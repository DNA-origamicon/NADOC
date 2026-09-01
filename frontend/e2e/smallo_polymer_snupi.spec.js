import { expect, test } from '@playwright/test'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`

test('smallO-poly SNUPI result stays current and enables visualization', async ({ page }) => {
  test.setTimeout(180_000)
  const doc = '__e2e__smallo-poly-snupi'
  const headers = { 'X-NADOC-Doc': doc }

  await page.goto(`/?doc=${doc}&open=smallO-poly.nass&open-type=assembly`)
  await page.waitForFunction(() => {
    const state = window.__NADOC_DBG__?.store.getState()
    return state?.assemblyActive && state.currentAssembly?.instances?.length === 3
  }, null, { timeout: 90_000 })
  await page.evaluate(() => window.__NADOC_DBG__?.renderer.setAnimationLoop(null))

  const prior = await (await page.request.get(`${API}/snupi/jobs`, { headers })).json()
  const priorIds = new Set(prior.map(job => job.job_id))
  await page.getByRole('button', { name: 'Simulations', exact: true }).click()
  await page.getByRole('tab', { name: 'SNUPI', exact: true }).click()
  await page.locator('#snupi-jobs-coarse-btn').click()

  let job
  await expect(async () => {
    const jobs = await (await page.request.get(`${API}/snupi/jobs`, { headers })).json()
    job = jobs.find(candidate => !priorIds.has(candidate.job_id))
    expect(job?.status).toBe('completed')
  }).toPass({ timeout: 120_000, intervals: [500, 1000, 2000] })
  expect(job.out_of_date).toBe(false)

  // Launching another job without an intervening edit must not make the first
  // result stale. This is the user-reported regression sequence.
  await expect(page.locator('#snupi-jobs-coarse-btn')).toBeEnabled({ timeout: 15_000 })
  await page.locator('#snupi-jobs-coarse-btn').click()
  let secondJob
  await expect(async () => {
    const jobs = await (await page.request.get(`${API}/snupi/jobs`, { headers })).json()
    secondJob = jobs.find(candidate => !priorIds.has(candidate.job_id) && candidate.job_id !== job.job_id)
    expect(secondJob?.status).toBe('completed')
  }).toPass({ timeout: 120_000, intervals: [500, 1000, 2000] })
  const firstAfterSecond = await (await page.request.get(`${API}/snupi/jobs/${job.job_id}`, { headers })).json()
  expect(firstAfterSecond.out_of_date).toBe(false)
  expect(secondJob.out_of_date).toBe(false)
  const unified = await (await page.request.get(`${API}/simulate/jobs?show_all=true`, { headers })).json()
  const unifiedFirst = unified.find(candidate => candidate.engine === 'snupi' && candidate.job_id === job.job_id)
  expect(unifiedFirst?.out_of_date).toBe(false)

  const row = page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`)
  await expect(row).toBeVisible({ timeout: 15_000 })
  await row.click()
  const deform = page.locator('.snupi-display-mode[value="deform"]')
  await expect(deform).toBeEnabled({ timeout: 15_000 })
  await deform.check()
  await expect(deform).toBeChecked()

  // Server restoration rematerializes the assembly into the active simulation
  // Design. Exercise that exact boundary again: the persisted job must not acquire
  // a false stale warning from regenerated derived-record ids.
  const rematerialized = await page.request.post(`${API}/assembly/flatten/load-as-design`, { headers })
  expect(rematerialized.ok()).toBeTruthy()
  const afterReload = await (await page.request.get(`${API}/snupi/jobs/${job.job_id}`, { headers })).json()
  expect(afterReload.out_of_date).toBe(false)
})
