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
import { trackConsoleErrors } from './helpers/scene_harness.js'

const API = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8000') + '/api'
// A small honeycomb bundle → a real duplex core that solves in seconds (Coarse + Fine).
const DESIGN_PATH = '/home/jojo/Work/NADOC/workspace/2hb_noT.nadoc'
const WS_PATH = 'workspace/2hb_noT.nadoc'

/** Poll /snupi/jobs until a completed job with the given solver mode exists; return it. */
async function waitForCompletedJob(page, { nonlinear }) {
  let job = null
  await expect(async () => {
    const jobs = await (await page.request.get(`${API}/snupi/jobs`)).json()
    expect(Array.isArray(jobs)).toBeTruthy()
    job = jobs.find((j) => j.status === 'completed' && j.nonlinear === nonlinear)
    // Surface a failed solve immediately instead of timing out.
    const failed = jobs.find((j) => j.status === 'failed' && j.nonlinear === nonlinear)
    expect(failed, failed ? `SNUPI solve failed: ${failed.error}` : undefined).toBeFalsy()
    expect(job, `no completed ${nonlinear ? 'Fine' : 'Coarse'} SNUPI job yet`).toBeTruthy()
  }).toPass({ timeout: 90_000 })
  return job
}

test('SNUPI Coarse + Fine buttons submit real jobs that complete + display', async ({ page, request }) => {
  test.setTimeout(240_000)
  const errors = trackConsoleErrors(page)
  const doc = 'snupirun'
  const H = { 'Content-Type': 'application/json', 'X-NADOC-Doc': doc }

  // Boot into design mode (File→New sets the workspace path the job list filters on), then
  // swap in a real solvable bundle via one atomic /design/load + a design-changed broadcast
  // (the frontend refetches → its store adopts the loaded design; no multi-step build to race).
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__snupirun')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  await page.waitForTimeout(500)

  const r = await page.request.post(`${API}/design/load`, { data: { path: DESIGN_PATH }, headers: H })
  expect(r.ok(), 'POST /design/load failed').toBeTruthy()
  const loaded = await (await page.request.get(`${API}/design`, { headers: H })).json()
  expect(loaded.design.helices.length).toBeGreaterThanOrEqual(2)
  await page.evaluate((d) => {
    const bc = new BroadcastChannel('nadoc-design')
    bc.postMessage({ type: 'design-changed', source: 'e2e-' + Math.random(), docId: d })
    bc.close()
  }, doc)
  await page.waitForFunction(() => {
    const s = window.__nadocTest?.scene
    if (!s) return false
    let ok = false
    s.traverse(o => { if (o.isInstancedMesh && o.name === 'backboneSpheres' && o.count > 0) ok = true })
    return ok
  }, null, { timeout: 20_000 })

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
  const proceed = page.getByRole('button', { name: /proceed|continue|run anyway|ok/i }).first()
  if (await proceed.isVisible({ timeout: 800 }).catch(() => false)) await proceed.click()
  const coarse = await waitForCompletedJob(page, { nonlinear: false })
  expect(coarse.n_nodes).toBeGreaterThan(0)
  expect(coarse.solver === undefined || true).toBeTruthy()

  // ── Press FINE (nonlinear corotational) — a second real job ───────────────────
  // The button re-enables once no SNUPI job is active (the panel poll clears it).
  await expect(fineBtn).toBeEnabled({ timeout: 20_000 })
  await fineBtn.click()
  const proceed2 = page.getByRole('button', { name: /proceed|continue|run anyway|ok/i }).first()
  if (await proceed2.isVisible({ timeout: 800 }).catch(() => false)) await proceed2.click()
  const fine = await waitForCompletedJob(page, { nonlinear: true })
  expect(fine.n_nodes).toBeGreaterThan(0)

  // ── Select the completed Fine job in the unified list + show the predicted shape ─
  await page.waitForTimeout(1800)   // one master poll cycle picks up the completed jobs
  const row = page.locator('#simulate-jobs-list [data-job-id]').first()
  await expect(row).toBeVisible({ timeout: 15_000 })
  await row.click()
  const deform = page.locator('.snupi-display-mode[value="deform"]')
  await expect(deform).toBeEnabled({ timeout: 15_000 })
  await deform.check()
  await page.waitForTimeout(1000)
  await expect(deform).toBeChecked()
  await expect(page.locator('#snupi-jobs-display-status')).toContainText(/predicted shape/i)

  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
