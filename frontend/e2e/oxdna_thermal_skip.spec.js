// Existing design only; all job mutations mocked. No native process is touched.
// __e2e__ autosaves/caches/credentials: global teardown. Screenshots: cleanup reporter.
import { expect, test } from '@playwright/test'

test('parent and every temperature menu skip only the active stage', async ({ page }, info) => {
  test.setTimeout(90000)
  const job = { job_id: '__e2e__skip', parent_job_id: '__e2e__parent', engine: 'oxdna',
    design_source_path: '2hb_1xT.nadoc', design_name: '2hb_1xT', status: 'running', backend: 'CUDA',
    created_at: 1, current_stage_idx: 1, run_config: { kind: 'run', thermal_ramp: { start_c: 25, end_c: 40, step_c: 5 } },
    stages: ['done', 'running', 'pending', 'pending'].map((status, i) => ({
      name: `${i+1}_thermal`, kind: 'production', status, steps: 50000000 })) }
  const requests = []
  await page.route(/\/api\/oxdna\/jobs(?:\?.*)?$/, r => r.fulfill({ json: [job] }))
  await page.route(`**/api/oxdna/jobs/${job.job_id}`, r => r.fulfill({ json: job }))
  await page.route(`**/api/oxdna/jobs/${job.job_id}/**`, async r => {
    if (r.request().url().endsWith('/skip-stage')) {
      const body = r.request().postDataJSON()
      requests.push(body)
      expect(body.expected_stage).toBe(job.stages[job.current_stage_idx].name)
      job.stages[job.current_stage_idx].status = 'skipped'
      job.current_stage_idx++
      job.stages[job.current_stage_idx].status = 'running'
      return r.fulfill({ json: { ok: true } })
    }
    return r.fulfill({ json: { ready: false, active: false } })
  })
  await page.route('**/api/simulate/jobs**', r => r.fulfill({ json: [{ ...job, kind: 'run' }] }))
  await page.route('**/api/jobs/active', r => r.fulfill({ json: { jobs: [] } }))
  await page.goto('/?doc=__e2e__skip&open=2hb_1xT.nadoc&open-type=design')
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentGeometry?.length)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  const group = page.locator('#simulate-jobs-list .thermal-job-group')
  await group.locator('.thermal-job-toggle').click()
  const command = page.getByRole('menuitem', { name: 'Skip to next stage', exact: true })
  // Context menus work on past, current and queued temperature rows.
  for (let i = 1; i <= 4; i++) {
    await group.locator(`[data-thermal-stage="${i}_thermal"]`).click({ button: 'right' })
    await expect(command).toBeVisible()
    await expect(command).not.toHaveClass(/disabled/)
    await page.keyboard.press('Escape')
  }
  await group.locator('[data-thermal-stage="4_thermal"]').click({ button: 'right' })
  if (process.env.NADOC_SKIP_VISUAL_REVIEW) {
    await page.screenshot({ path: info.outputPath('skip-temperature-menu.png') })
    console.log('SKIP_VISUAL_READY', info.outputPath('skip-temperature-menu.png'))
    await page.waitForTimeout(30000)
  }
  await command.click()
  await expect(group.locator('[data-thermal-stage="2_thermal"]')).toContainText('Skipped')
  await expect(group.locator('[data-thermal-stage="3_thermal"]')).toContainText('Running')
  expect(requests).toEqual([{ expected_stage: '2_thermal' }])
  await group.locator('[data-job-id]').click({ button: 'right' })
  await command.click()
  await expect(group.locator('[data-thermal-stage="3_thermal"]')).toContainText('Skipped')
  await group.locator('[data-job-id]').click({ button: 'right' })
  await expect(command).toHaveClass(/disabled/)
  expect(requests).toHaveLength(2)
})
