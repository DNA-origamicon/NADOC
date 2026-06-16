/**
 * MD jobs panel — a running job shows live state, never a stale "stopped" banner.
 *
 * Reproduces the reported symptom's end state: selecting an actively-running NAMD
 * job must show a running status, hide the stopped/error banner, and open the
 * live status WebSocket (so the detail keeps updating).  Skips unless the test
 * job 01968f730c8e is actually running.
 *
 * Run:
 *   cd /home/jojo/Work/NADOC/frontend
 *   npx playwright test e2e/md_live_no_stale.spec.js
 */

import { test, expect } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api'
const JOB_ID = '01968f730c8e'
const DESIGN_PATH = '/home/jojo/Work/NADOC/workspace/18hb_42bp.nadoc'

test('a running job shows live status with no stale stopped banner', async ({ page, request }) => {
  const jr = await request.get(`${API}/md/jobs/${JOB_ID}`)
  test.skip(!jr.ok(), 'test job 01968f730c8e not present')
  const job = await jr.json()
  test.skip(job.status !== 'running', `job is ${job.status}, expected running`)

  const lr = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(lr.ok(), 'POST /design/load failed').toBeTruthy()

  // Capture the live-status WebSocket the panel should open for a running job.
  let wsOpened = false
  page.on('websocket', ws => {
    if (ws.url().includes(`/ws/md-jobs/${JOB_ID}`)) wsOpened = true
  })

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
  const row = page.locator(`#md-jobs-list [data-job-id="${JOB_ID}"]`)
  await expect(row).toBeVisible()
  await row.click()

  // Detail reflects the live run, not a frozen stopped snapshot.
  const status = page.locator('#md-jobs-detail-status')
  await expect(status).toContainText(/running/i)

  // The stopped/error banner must not be showing its old "resume to continue" text.
  const errorBanner = page.locator('#md-jobs-detail-error')
  await expect(errorBanner).toBeHidden()

  // The Stop button (running-only) is visible; Start (resume) is not.
  await expect(page.locator('#md-jobs-stop-btn')).toBeVisible()
  await expect(page.locator('#md-jobs-start-btn')).toBeHidden()

  // And the panel is actively monitoring via WebSocket.
  await expect.poll(() => wsOpened, { timeout: 8000 }).toBe(true)
})
