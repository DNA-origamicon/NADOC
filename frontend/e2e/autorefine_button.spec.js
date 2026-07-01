/**
 * Autorefine skips/loops button — renders in the oxDNA panel, gated to SQUARE lattice.
 *
 * Exercises the real DOM: loads a square-lattice design (button enabled, correct label
 * + tooltip) then a honeycomb design (button disabled with the square-only tooltip).
 * GPU-free: it never STARTS a run (that would launch a multi-hour simulation) — it only
 * asserts the gating + presentation the user sees.
 */
import { test, expect } from '@playwright/test'
import path from 'node:path'

const ROOT = path.resolve(import.meta.dirname ?? __dirname, '../..')
const SQUARE_DESIGN = path.join(ROOT, 'tests/fixtures/teeth.nadoc')        // 16-helix SQUARE
const HONEYCOMB_DESIGN = path.join(ROOT, 'Examples/26hb_platform_v3.nadoc') // HONEYCOMB

async function newDesign(page, name) {
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
}

async function loadInto(page, p) {
  await page.evaluate(async (fp) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(fp)
  }, p)
}

test('autorefine button renders + gates to SQUARE lattice', async ({ page }) => {
  await newDesign(page, 'autorefine-button-test')
  await page.click('#left-tab-strip [data-tab="dynamics"]')
  await page.evaluate(() => {
    const body = document.getElementById('oxdna-jobs-body')
    const heading = document.getElementById('oxdna-jobs-heading')
    if (body && heading && (body.hidden || getComputedStyle(body).display === 'none')) heading.click()
  })

  const btn = page.locator('#oxdna-jobs-autorefine-btn')
  await expect(btn).toHaveText(/Autorefine skips\/loops/)

  // SQUARE lattice → enabled (oxDNA is available on this machine), descriptive tooltip.
  await loadInto(page, SQUARE_DESIGN)
  await expect(btn).toBeEnabled({ timeout: 15_000 })
  await expect(btn).toHaveAttribute('title', /iteratively tune/i)

  // HONEYCOMB → disabled, with a tooltip explaining the square-only limitation.
  await loadInto(page, HONEYCOMB_DESIGN)
  await expect(btn).toBeDisabled({ timeout: 15_000 })
  await expect(btn).toHaveAttribute('title', /SQUARE lattice/i)
})

test('autorefine start reveals Stop, and Stop ends the run (mocked backend)', async ({ page }) => {
  // Mock the autorefine endpoints so the UI flow runs without launching a real job.
  let stopped = false
  await page.route('**/design/oxdna/autorefine/start', (route) =>
    route.fulfill({ json: { autorefine_id: 'mock1', state: 'running' } }))
  await page.route('**/design/oxdna/autorefine/mock1/stop', (route) => {
    stopped = true
    return route.fulfill({ json: { autorefine_id: 'mock1', stopping: true, killed_job: true } })
  })
  await page.route('**/design/oxdna/autorefine/mock1', (route) => route.fulfill({
    json: stopped
      ? { state: 'stopped', phase: 'stopped', result: { status: 'stopped',
          primary_metric: 'global_twist_deg', converged_period: 24,
          before: { twist_residual_deg: 37, rmsd_nm: 1.5 },
          after: { twist_residual_deg: 2, rmsd_nm: 1.3 }, iterations: [] } }
      : { state: 'running', phase: 'iteration',
          last_event: { period: 24, steering: { bundle_twist_residual_deg: 3.1 } } },
  }))
  page.on('dialog', (d) => d.accept())   // auto-accept the "this can take a long time" confirm

  await newDesign(page, 'autorefine-stop-test')
  await page.click('#left-tab-strip [data-tab="dynamics"]')
  await page.evaluate(() => {
    const body = document.getElementById('oxdna-jobs-body')
    const heading = document.getElementById('oxdna-jobs-heading')
    if (body && heading && (body.hidden || getComputedStyle(body).display === 'none')) heading.click()
  })
  await loadInto(page, SQUARE_DESIGN)

  const btn = page.locator('#oxdna-jobs-autorefine-btn')
  const stop = page.locator('#oxdna-jobs-autorefine-stop-btn')
  await expect(btn).toBeEnabled({ timeout: 15_000 })
  await expect(stop).toBeHidden()

  await btn.click()                                  // start → Stop appears
  await expect(stop).toBeVisible({ timeout: 10_000 })

  await stop.click()                                 // stop → run ends, result renders, Stop hides
  await expect(page.locator('#oxdna-jobs-autorefine-result')).toContainText('before vs after', { timeout: 10_000 })
  await expect(page.locator('#oxdna-jobs-autorefine-status')).toContainText(/stopped/i)
  await expect(stop).toBeHidden()
})

test('autorefine status, completion, apply-skips + re-run guard (mocked backend)', async ({ page }) => {
  let done = false, applyCalls = 0
  await page.route('**/design/oxdna/autorefine/start', (route) =>
    route.fulfill({ json: { autorefine_id: 'm2', state: 'running' } }))
  await page.route('**/oxdna/jobs/jobX', (route) => route.fulfill({
    json: { stages: [{ kind: 'production', status: 'running' }] } }))
  // The panel applies skips to the design live (per iteration) + on completion (with
  // a ?period= query).  Empty (no `design`) response → syncDesignResponse is a no-op.
  await page.route(/\/autorefine\/m2\/apply/, (route) => { applyCalls++; return route.fulfill({ json: {} }) })
  await page.route('**/design/oxdna/autorefine/m2', (route) => route.fulfill({
    json: done
      ? { state: 'done', phase: 'done', current_job_id: 'jobX', current_period: 24, result: { status: 'met',
          primary_metric: 'global_twist_deg', converged_period: 24,
          before: { twist_residual_deg: 49, rmsd_nm: 3.0 }, after: { twist_residual_deg: -5, rmsd_nm: 1.96 },
          iterations: [{ period: 48, twist_residual_deg: 49, status: 'unmet', early_reject: true },
                       { period: 24, twist_residual_deg: -5, status: 'met', early_reject: false }] } }
      : { state: 'running', phase: 'iteration', current_job_id: 'jobX', current_period: 48,
          last_event: { period: 48, early_reject: true, steering: { bundle_twist_residual_deg: 49 } } } }))

  const dialogs = []
  page.on('dialog', (d) => { dialogs.push(d.message()); if (/nothing has changed/i.test(d.message())) d.dismiss(); else d.accept() })

  await newDesign(page, 'autorefine-status-test')
  await page.click('#left-tab-strip [data-tab="dynamics"]')
  await page.evaluate(() => {
    const body = document.getElementById('oxdna-jobs-body')
    const heading = document.getElementById('oxdna-jobs-heading')
    if (body && heading && (body.hidden || getComputedStyle(body).display === 'none')) heading.click()
  })
  await loadInto(page, SQUARE_DESIGN)

  const btn = page.locator('#oxdna-jobs-autorefine-btn')
  const status = page.locator('#oxdna-jobs-autorefine-status')
  // The deviation toggle now lives in the job-detail section, directly below the
  // flexibility-map toggle, and is disabled until the autorefine run's job is selected.
  await expect(page.locator('#oxdna-jobs-deviation-toggle')).toBeDisabled()
  await expect(btn).toBeEnabled({ timeout: 15_000 })

  await btn.click()                                  // start (accepts the long-run confirm)
  // Live status: spinner + iteration + sub-stage from the in-flight job.
  await expect(status).toContainText(/iteration 1 · producing/i, { timeout: 10_000 })

  done = true                                         // flip the mock to a completed run
  await expect(status).toContainText(/✓ Autorefine complete/i, { timeout: 10_000 })
  const result = page.locator('#oxdna-jobs-autorefine-result')
  await expect(result).toContainText('before vs after')
  await expect(result).toContainText('period 48')    // iteration log
  await expect(result).toContainText('rejected (early)')
  await expect(result).toContainText('period 24')

  // The converged skips were applied to the design (feature-log entry).
  await expect.poll(() => applyCalls, { timeout: 10_000 }).toBeGreaterThan(0)

  // Re-run guard: design unchanged since the run → the "nothing has changed" confirm.
  await btn.click()
  await expect.poll(() => dialogs.some((m) => /nothing has changed/i.test(m)), { timeout: 5_000 }).toBe(true)
})

test('autorefine selects + [AR]-tags the in-flight job and suppresses the stale ⚠ (mocked backend)', async ({ page }) => {
  // The in-flight job, returned by BOTH the single-job and the list endpoints.  Marked
  // out_of_date to prove the design-changed ⚠ is suppressed WHILE the run is active (the
  // loop edits the design every iteration, which would otherwise flag every job stale).
  const jobX = {
    job_id: 'jobX', status: 'running', created_at: 1, out_of_date: true,
    design_source_path: null,
    stages: [{ name: '4_production', kind: 'production', status: 'running' }],
  }
  await page.route('**/design/oxdna/autorefine/start', (route) =>
    route.fulfill({ json: { autorefine_id: 'm3', state: 'running' } }))
  await page.route(/\/autorefine\/m3\/apply/, (route) => route.fulfill({ json: {} }))
  await page.route('**/design/oxdna/autorefine/m3', (route) => route.fulfill({
    json: { state: 'running', phase: 'iteration', current_job_id: 'jobX', current_period: 48,
            last_event: { period: 48, steering: { bundle_twist_residual_deg: 49 } } } }))
  await page.route('**/oxdna/jobs/jobX', (route) => route.fulfill({ json: jobX }))
  await page.route('**/oxdna/jobs/jobX/progress', (route) => route.fulfill({ json: { frame_index: null } }))
  await page.route(/\/oxdna\/jobs(\?|$)/, (route) => route.fulfill({ json: [jobX] }))   // the LIST
  page.on('dialog', (d) => d.accept())

  await newDesign(page, 'autorefine-ar-tag-test')
  await page.click('#left-tab-strip [data-tab="dynamics"]')
  await page.evaluate(() => {
    const body = document.getElementById('oxdna-jobs-body')
    const heading = document.getElementById('oxdna-jobs-heading')
    if (body && heading && (body.hidden || getComputedStyle(body).display === 'none')) heading.click()
  })
  await loadInto(page, SQUARE_DESIGN)
  // Show ALL jobs so the mocked jobX (no design_source_path) renders regardless of the
  // current-design filter.
  await page.evaluate(() => {
    const t = document.getElementById('oxdna-jobs-show-all')
    if (t && !t.checked) { t.checked = true; t.dispatchEvent(new Event('change')) }
  })

  const btn = page.locator('#oxdna-jobs-autorefine-btn')
  await expect(btn).toBeEnabled({ timeout: 15_000 })
  await btn.click()

  // The in-flight job is auto-selected (selected-row background), tagged [AR], and shows
  // NO stale ⚠ while the run is active.
  const row = page.locator('[data-job-id="jobX"]')
  await expect(row).toBeVisible({ timeout: 10_000 })
  await expect(row).toContainText('[AR]')
  await expect(row).toHaveAttribute('style', /rgb\(42, 58, 74\)/)   // selected highlight (#2a3a4a)
  await expect(row.locator('.oxdna-job-stale-warn')).toHaveCount(0)
})
