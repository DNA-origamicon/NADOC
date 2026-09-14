/** No persistent artifacts: no design or job is created; the acknowledgment API is
 * intercepted in-browser. Browser DOM/storage dies with the context. Screenshots
 * and traces, if any, stay inside Playwright's configured output directory.
 */
import { test, expect } from '@playwright/test'

test('restart notice works in the running app and acknowledgment survives rerender', async ({ page }) => {
  const notice = { id:'123-r1', revision:1, mode:'continued', slurm_job_id:'123',restart_count:1,
    acknowledged_at:null, segments:[{segment:'prod',mode:'continued',checkpoint_step:20000,timestep_fs:4}] }
  let saved = false
  await page.route('**/api/md/jobs/__e2e__restart_notice/restart-acknowledgment', async route => {
    expect(route.request().postDataJSON()).toEqual({events:[{id:'123-r1',revision:1}]})
    saved = true
    await route.fulfill({json:{ok:true,restart_events:[{...notice,acknowledged_at:123}]}})
  })
  await page.goto('/')
  await expect(page.locator('#canvas')).toBeAttached()
  await page.evaluate(async notice => {
    const { buildJobListModel } = await import('/src/ui/jobs_panel_model.js')
    const { renderJobList } = await import('/src/ui/jobs_panel_render.js')
    const host = document.createElement('div')
    host.id = '__e2e__restart_notice'
    host.style.cssText = 'position:fixed;inset:20px;z-index:9999;background:#222;color:white;padding:20px'
    document.body.append(host)
    const job = {job_id:'__e2e__restart_notice',design_name:'Restart check',status:'running',restart_events:[notice]}
    renderJobList(host,buildJobListModel([job],{engine:'namd',displayName:j=>j.design_name}),{})
  }, notice)
  const icon = page.locator('[data-alpine-restart="__e2e__restart_notice"]')
  await icon.click()
  await expect(page.getByRole('dialog')).toContainText('continued at step 20000 (0.080 ns)')
  await page.getByRole('button',{name:'Close',exact:true}).click()
  expect(saved).toBe(false)
  await expect(icon).toHaveText('⚠')
  await icon.click()
  await page.getByRole('button',{name:'I understand',exact:true}).click()
  await expect(icon).toHaveText('ⓘ')
  expect(saved).toBe(true)
  await icon.click()
  await expect(page.getByRole('dialog')).toContainText('Resumed from checkpoint')
  await expect(page.getByRole('button',{name:'I understand',exact:true})).toHaveCount(0)
  await page.getByRole('button',{name:'Close',exact:true}).click()
  await page.evaluate(() => document.getElementById('__e2e__restart_notice').remove())
})
