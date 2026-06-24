/**
 * MD jobs panel — trajectory scrub + flexibility-map (RMSF) visualization tools.
 *
 * Verifies the oxDNA-style viz tools are wired for a NAMD job: selecting a job with
 * written frames enables the toggles, and toggling each tool drives the shared
 * display controller through the MD api adapter to the correct MD endpoint
 * (DOM toggle → md_jobs_panel handler → mdViz controller → mdVizApiAdapter →
 * GET /md/jobs/{id}/trajectory | /rmsf) — with no uncaught console errors.
 *
 * The endpoints' correctness (200-frame composite trajectory; per-residue RMSF map)
 * is covered by backend tests + direct HTTP validation; this asserts the frontend
 * integration that joins them to the renderer.  Skips unless the 6hb test job exists.
 *
 * Run (against the running dev servers on :8000/:5173):
 *   cd /home/jojo/Work/NADOC/frontend
 *   npx playwright test e2e/md_viz_tools.spec.js
 */

import { test, expect } from '@playwright/test'

const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000'}/api`
const JOB_ID = 'b9f5df08a55e'
const DESIGN_PATH = '/home/jojo/Work/NADOC/workspace/6hb_84bp.nadoc'

test('MD trajectory + flexibility-map toggles drive the MD viz endpoints', async ({ page, request }) => {
  test.setTimeout(60_000)

  const jr = await request.get(`${API}/md/jobs/${JOB_ID}`)
  test.skip(!jr.ok(), 'test job 6hb b9f5df08a55e not present')

  const lr = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(lr.ok(), 'POST /design/load failed').toBeTruthy()

  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

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

  // The viz toggles enable once the selected job has written frames.
  const trajToggle = page.locator('#md-jobs-traj-toggle')
  const flexToggle = page.locator('#md-jobs-flex-toggle')
  await expect(trajToggle).toBeEnabled()
  await expect(flexToggle).toBeEnabled()

  // Toggling "View trajectory" issues the composite-trajectory request for this job
  // (DOM → panel handler → mdViz.loadTrajectory → adapter → MD endpoint).
  const trajReq = page.waitForRequest(
    r => r.url().includes(`/md/jobs/${JOB_ID}/trajectory`) && !r.url().includes('trajectory-meta'),
    { timeout: 15_000 })
  await trajToggle.check()
  await trajReq
  await trajToggle.uncheck()

  // Toggling "Flexibility map" issues the RMSF request for this job
  // (DOM → panel handler → mdViz.displayRmsf → adapter → MD endpoint).
  const rmsfReq = page.waitForRequest(
    r => r.url().includes(`/md/jobs/${JOB_ID}/rmsf`), { timeout: 15_000 })
  await flexToggle.check()
  await rmsfReq

  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
