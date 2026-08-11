// Verifies the VRAM "Fix" affordance end-to-end against the running app:
// a GPU-out-of-memory job shows a Fix button, and clicking it opens the popup
// (which is populated by the live /api/md/jobs/{id}/vram-advice endpoint).
import { test, expect } from '@playwright/test'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000'}/api`
const DESIGN_PATH = '/home/jojo/Work/NADOC/workspace/6hb_84bp.nadoc'

test('VRAM-failed job explains the full-box hardware requirement', async ({ page, request }) => {
  test.setTimeout(60_000)

  // A GPU-OOM job must exist to test against (VoltronCore full-box run).
  const jobs = await (await request.get(`${API}/md/jobs`)).json()
  const oom = jobs.find(j => j.failure_kind === 'vram_oom')
  test.skip(!oom, 'no vram_oom job present to fix')

  // Any design enables the Dynamics panel; show-all surfaces the OOM job.
  const lr = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH }, headers: { 'Content-Type': 'application/json' },
  })
  expect(lr.ok(), 'POST /design/load failed').toBeTruthy()

  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.evaluate(() => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.querySelectorAll('.left-tab-btn').forEach(b => { b.disabled = false })
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    document.querySelectorAll('.tab-content').forEach(el => {
      el.hidden = el.id !== 'tab-content-dynamics'
    })
  })

  const body = page.locator('#md-jobs-panel-body')
  if (!(await body.isVisible())) await page.click('#md-jobs-panel-heading')
  await expect(body).toBeVisible()
  await page.locator('#md-jobs-show-all').check()

  // The OOM job's row shows a Fix button.
  const fixBtn = page.locator(`#md-jobs-list [data-job-id="${oom.job_id}"] button`, { hasText: 'Fix' })
  await expect(fixBtn).toBeVisible({ timeout: 15000 })

  await fixBtn.click()

  const modal = page.locator('[data-testid="vram-fix-modal"]')
  await expect(modal).toBeVisible()
  await expect(modal).toContainText('Ran out of GPU memory')
  await expect(modal).toContainText(/complete periodic water box/i)
  await expect(modal.locator('button', { hasText: /Re-run with/ })).toHaveCount(0)

  // Close without applying (don't spawn a real multi-hour job from the test).
  await modal.locator('button', { hasText: 'Close' }).click()
  await expect(modal).toBeHidden()
})
