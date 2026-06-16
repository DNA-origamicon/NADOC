/**
 * MD jobs panel — Relax → Resume relabel for an interrupted run.
 *
 * Verifies the UX wired for crash/interruption recovery: when an interrupted
 * (stopped, mid-ladder) relaxation job is selected, the prominent "▶ Relax"
 * button relabels to "▶ Resume".  Uses the real stalled job in the workspace
 * (18hb_42bp, parked at the k=0.5 relaxation stage) surfaced via "Show all".
 *
 * Run:
 *   cd /home/jojo/Work/NADOC/frontend
 *   npx playwright test e2e/md_resume_button.spec.js
 */

import { test, expect } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api'
const JOB_ID = '01968f730c8e'   // 18hb_42bp, status=stopped, pending relax segment
const DESIGN_PATH = '/home/jojo/Work/NADOC/workspace/18hb_42bp.nadoc'

test('interrupted relaxation relabels Relax button to Resume', async ({ page, request }) => {
  // The job must exist and be stopped for this assertion to mean anything.
  const jr = await request.get(`${API}/md/jobs/${JOB_ID}`)
  test.skip(!jr.ok(), 'stalled test job 01968f730c8e not present')
  const job = await jr.json()
  test.skip(job.status !== 'stopped', `job is ${job.status}, expected stopped`)

  // A design must be loaded for the Dynamics tab to enable.
  const lr = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH },
    headers: { 'Content-Type': 'application/json' },
  })
  expect(lr.ok(), 'POST /design/load failed').toBeTruthy()

  await page.goto('/')
  await page.waitForSelector('#canvas')
  // Hide startup overlays and reveal the Dynamics tab content directly. Tab
  // gating/switching is not under test here — only the MD-jobs button relabel is.
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

  // Expand the Molecular Dynamics section (its heading click triggers the job fetch).
  const body = page.locator('#md-jobs-panel-body')
  if (!(await body.isVisible())) await page.click('#md-jobs-panel-heading')
  await expect(body).toBeVisible()

  // Surface jobs for every design, then select the stalled one.
  const showAll = page.locator('#md-jobs-show-all')
  if (!(await showAll.isChecked())) await showAll.check()

  const runBtn = page.locator('#md-jobs-run-btn')
  await expect(runBtn).toHaveText(/Relax/)   // default before selection

  const row = page.locator(`#md-jobs-list [data-job-id="${JOB_ID}"]`)
  await expect(row).toBeVisible()
  await row.click()

  // After selecting the interrupted relaxation, the button reads "Resume".
  await expect(runBtn).toHaveText(/Resume/)
})
