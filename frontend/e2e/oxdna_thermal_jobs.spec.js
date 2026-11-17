// Reads an existing design and mocks job responses; never starts or writes a job.
// Isolated __e2e__ session, global teardown and artifact-cleanup reporter own cleanup.
import { expect, test } from '@playwright/test'

test('Tm jobs expand into live temperature steps and retain expansion on refresh', async ({ page }, testInfo) => {
  test.setTimeout(process.env.NADOC_THERMAL_VISUAL_REVIEW ? 120000 : 60000)
  const job = { job_id: '__e2e__thermal-list', parent_job_id: '__e2e__relaxed',
    design_source_path: '2hb_1xT.nadoc', design_name: '2hb_1xT', status: 'running', backend: 'CPU',
    created_at: 1, current_stage_idx: 1,
    run_config: { kind: 'run', thermal_ramp: { start_c: 25, end_c: 40, step_c: 5 } },
    stages: ['done', 'running', 'pending', 'pending'].map((status, i) => ({
      name: `${i + 1}_thermal`, kind: 'production', status, steps: 1000000 })) }
  await page.route(/\/api\/oxdna\/jobs(?:\?.*)?$/, route => route.fulfill({ json: [job] }))
  await page.route(`**/api/oxdna/jobs/${job.job_id}`, route => route.fulfill({ json: job }))
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [{ ...job, engine: 'oxdna', kind: 'run' }] }))
  await page.route('**/api/jobs/active', route => route.fulfill({ json: { jobs: [] } }))
  await page.goto('/?doc=__e2e__thermal-list&open=2hb_1xT.nadoc&open-type=design')
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await expect(page.locator('#op-progress')).not.toHaveClass(/visible/, { timeout: 15000 })
  const group = page.locator('#simulate-jobs-list .thermal-job-group')
  await expect(group.locator('[data-job-id]')).toContainText('Tm Run 1')
  const toggle = group.locator('.thermal-job-toggle')
  await toggle.focus()
  await expect(toggle).toBeFocused()
  await toggle.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(group.locator('[data-status="completed"]')).toContainText('25C - Run 1')
  await expect(group.locator('[data-status="running"]')).toContainText('30C - Run 1')
  await expect(group.locator('[data-status="waiting"]')).toHaveCount(2)
  if (process.env.NADOC_THERMAL_VISUAL_REVIEW) {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await expect(page.locator('#op-progress')).not.toHaveClass(/visible/, { timeout: 15000 })
    await page.screenshot({ path: testInfo.outputPath('thermal-job-list.png') })
    console.log('THERMAL_LIST_VISUAL_READY', testInfo.outputPath('thermal-job-list.png'))
    await page.waitForTimeout(45000)
  }
  job.stages[1].status = 'done'; job.stages[2].status = 'running'; job.current_stage_idx = 2
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed')))
  await expect(group.locator('.thermal-job-summary')).toHaveText('2 / 4 temperature steps completed')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(group.locator('[data-status="running"]')).toContainText('35C - Run 1')
  await toggle.click()
  await expect(group.locator('.thermal-job-details')).toBeHidden()
})
