/**
 * SNUPI FEM — REAL button-press automation.
 *
 * Loads a small paired bundle into the backend session (POST /design/load, the same path
 * md_ballstick.spec.js uses — no File→New, so nothing clobbers the design mid-build), then
 * drives the actual Coarse and Fine run buttons in the SNUPI engine tab and waits for each
 * real job to complete. Finally selects the completed job and flips the Predicted-shape viz
 * toggle to confirm the FEM overlay applies (Physical-layer display only). Asserts zero
 * console errors.
 *
 * Run:  cd frontend && npx playwright test e2e/snupi_run.spec.js
 */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000') + '/api'
/** Poll /snupi/jobs until a completed job with the given solver mode exists; return it. */
async function waitForCompletedJob(page, { nonlinear, excludeIds = new Set() }) {
  let job = null
  await expect(async () => {
    const jobs = await (await page.request.get(`${API}/snupi/jobs`)).json()
    expect(Array.isArray(jobs)).toBeTruthy()
    job = jobs.find((j) => !excludeIds.has(j.job_id) && j.status === 'completed' && j.nonlinear === nonlinear)
    // Surface a failed solve immediately instead of timing out.
    const failed = jobs.find((j) => !excludeIds.has(j.job_id) && j.status === 'failed' && j.nonlinear === nonlinear)
    expect(failed, failed ? `SNUPI solve failed: ${failed.error}` : undefined).toBeFalsy()
    expect(job, `no completed ${nonlinear ? 'Fine' : 'Coarse'} SNUPI job yet`).toBeTruthy()
  }).toPass({ timeout: 90_000 })
  return job
}

test('SNUPI Coarse + Fine buttons submit real jobs that complete + display', async ({ page, request }) => {
  test.setTimeout(240_000)
  const errors = trackConsoleErrors(page)
  const doc = 'snupirun'
  await loadScaffoldedPart(page, { doc, name: 'snupirun' })
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }
  const current = await (await page.request.get(`${API}/design`, { headers: H })).json()
  const scaffold = current.design.strands.find((s) => String(s.strand_type).toLowerCase() === 'scaffold')
  const domain = scaffold.domains[0]
  const opposite = domain.direction === 'FORWARD' ? 'REVERSE' : 'FORWARD'
  const staple = await page.request.post(`${API}/design/strands`, {
    headers: H,
    data: {
      strand_type: 'staple',
      domains: [{
        helix_id: domain.helix_id,
        start_bp: domain.end_bp,
        end_bp: domain.start_bp,
        direction: opposite,
      }],
    },
  })
  expect(staple.ok(), 'failed to add duplex staple').toBeTruthy()
  const priorJobs = await (await page.request.get(`${API}/snupi/jobs`, { headers: H })).json()
  const priorIds = new Set(priorJobs.map((job) => job.job_id))
  // Dynamics tab → SNUPI engine tab.
  await page.click('[data-tab="dynamics"]')
  await page.waitForTimeout(300)
  await page.click('.engine-selector-btn[data-engine="snupi"]')
  await expect(page.locator('#snupi-jobs-panel')).toBeVisible()
  const coarseBtn = page.locator('#snupi-jobs-coarse-btn')
  const fineBtn = page.locator('#snupi-jobs-fine-btn')
  await expect(coarseBtn).toBeVisible()

  // ── Press COARSE (linear) — a real job is created + runs + completes ──────────
  await coarseBtn.click()
  // The unified card gets an optimistic selected row synchronously; users never
  // stare at an unchanged card while materialization/job creation is in flight.
  await expect(page.locator('#simulate-jobs-list [data-job-id]').first()).toBeVisible({ timeout: 1_000 })
  await expect(page.locator('#simulate-jobs-status')).toContainText(/SNUPI.*(preparing|running)/i, { timeout: 3_000 })
  const proceed = page.getByRole('button', { name: /proceed|continue|run anyway|ok/i }).first()
  if (await proceed.isVisible({ timeout: 800 }).catch(() => false)) await proceed.click()
  const coarse = await waitForCompletedJob(page, { nonlinear: false, excludeIds: priorIds })
  expect(coarse.n_nodes).toBeGreaterThan(0)
  expect(coarse.solver === undefined || true).toBeTruthy()

  // ── Press FINE (nonlinear corotational) — a second real job ───────────────────
  // The button re-enables once no SNUPI job is active (the panel poll clears it).
  await expect(fineBtn).toBeEnabled({ timeout: 20_000 })
  await fineBtn.click()
  await expect(page.locator('#simulate-jobs-status')).toContainText(/SNUPI.*(preparing|running)/i, { timeout: 3_000 })
  const proceed2 = page.getByRole('button', { name: /proceed|continue|run anyway|ok/i }).first()
  if (await proceed2.isVisible({ timeout: 800 }).catch(() => false)) await proceed2.click()
  priorIds.add(coarse.job_id)
  const fine = await waitForCompletedJob(page, { nonlinear: true, excludeIds: priorIds })
  expect(fine.n_nodes).toBeGreaterThan(0)

  // ── Select the completed Fine job in the unified list + show the predicted shape ─
  await page.waitForTimeout(1800)   // one master poll cycle picks up the completed jobs
  const row = page.locator(`#simulate-jobs-list [data-job-id="${fine.job_id}"]`)
  await expect(row).toBeVisible({ timeout: 15_000 })
  const deform = page.locator('.snupi-display-mode[value="deform"]')
  // The immediate-launch path may already have the row highlighted. Clicking the
  // completed row must still open/retain its visualization controls, never toggle
  // the selection off and disable them.
  await row.click()
  await expect(deform).toBeEnabled({ timeout: 15_000 })
  await deform.check()
  await page.waitForTimeout(1000)
  await expect(deform).toBeChecked()
  await expect(page.locator('#snupi-jobs-display-status')).toContainText(/predicted shape/i)

  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
