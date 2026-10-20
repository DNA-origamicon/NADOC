/**
 * In-app rendering exercise with synthetic jobs only. No API mutations or saved
 * designs/jobs. The temporary DOM is removed in afterEach; context storage dies
 * with the browser. Reports/traces remain in Playwright's configured output only.
 */
import { test, expect } from '@playwright/test'

test.afterEach(async ({ page }) => {
  await page.evaluate(() => document.getElementById('__e2e__download_queue')?.remove())
  await expect(page.locator('#__e2e__download_queue')).toHaveCount(0)
})

test('queued Alpine results have a waiting badge and disabled run control', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await page.goto('/?doc=__e2e__download_queue')
  await expect(page.locator('#canvas')).toBeAttached()
  await page.evaluate(async () => {
    const { buildJobRowModel } = await import('/src/ui/jobs_panel_model.js')
    const { renderJobRow } = await import('/src/ui/jobs_panel_render.js')
    const { mdRunControl } = await import('/src/ui/md_jobs_panel.js')
    const host = document.createElement('div')
    host.id = '__e2e__download_queue'
    host.style.cssText = 'position:fixed;inset:20px;z-index:99999;background:#222;color:white;padding:20px'
    document.body.append(host)
    for (const state of ['queued', 'downloading', 'processing']) {
      const job = { job_id: `__e2e__${state}`, design_name: `Results ${state}`,
        status: 'running', execution_target: 'alpine', slurm_job_id: 'test-only',
        slurm_state: 'COMPLETED', download_status: { state }, progress_fraction: 0.99 }
      const model = buildJobRowModel(job, {
        engine: 'namd', displayName: job => job.design_name,
      })
      host.append(renderJobRow(model))
      const control = mdRunControl(job, { clusterState: 'connected' })
      const button = document.createElement('button')
      button.id = `__e2e__control_${state}`
      button.textContent = control.label
      button.disabled = control.disabled
      host.append(button)
    }
  })
  const queued = page.locator('[data-job-id="__e2e__queued"]')
  await expect(queued.locator('[title="Finished on Alpine — waiting to download"]')).toBeVisible()
  await expect(queued.locator('.nadoc-spinner')).toHaveCount(0)
  await expect(page.locator('#__e2e__control_queued')).toHaveText('Waiting to download…')
  await expect(page.locator('#__e2e__control_queued')).toBeDisabled()
  await expect(page.locator('#__e2e__control_downloading')).toHaveText('Downloading results…')
  await expect(page.locator('#__e2e__control_processing')).toHaveText('Processing results…')
  expect(errors).toEqual([])
})
