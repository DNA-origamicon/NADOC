/**
 * Real-app placement proof for Alpine scheduler warnings.
 *
 * Uses the ordinary NAMD Cluster card and Job Wizard against throwaway dev servers;
 * only the two read-only cluster endpoints are intercepted so the test is deterministic
 * and never needs credentials or touches a queued job.
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const API_ORIGIN = process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'
const API = `${API_ORIGIN}/api`
const DOC = '__e2e__alpine-maintenance-warning'
const DESIGN_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../Examples/2hb_xover_val.nadoc',
)

const AVAILABILITY = {
  cluster: 'alpine',
  checked_at: '2026-08-30T10:49:24',
  maintenance: [{
    name: 'alpine-maint', start: '2026-09-01T06:00:00',
    end: '2026-09-03T06:30:00', active: false,
  }],
  partitions: [{
    partition: 'ah200', gpu_model: 'NVIDIA H200', gres_type: 'h200',
    gpus_total: 16, gpus_free: 1, pending_jobs: 1, pending_gpus: 1,
    wait_min: 5520, wait_label: '~3 d 20 h', wait_basis: 'SLURM backfill estimate',
    slurm_start: '2026-09-03T06:30:00', speed_factor: 2.5, max_walltime_h: 168,
    gpu_resources: [{
      partition: 'ah200', gres_type: 'h200_3g.71gb', label: 'H200 MIG 3g.71gb',
      mig: true, gpus_total: 16, gpus_free: 14, wait_min: 5520,
      wait_label: '~3 d 20 h', wait_basis: 'SLURM backfill estimate',
      slurm_start: '2026-09-03T06:30:00', speed_factor: 1.07143, max_cores: 16,
    }],
  }],
  warnings: [],
}

async function openNAMD(page) {
  await page.goto(`/?doc=${DOC}`)
  await page.waitForSelector('#canvas')
  await page.evaluate(() => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.querySelectorAll('.left-tab-btn').forEach(button => { button.disabled = false })
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    document.querySelectorAll('.tab-content').forEach(element => {
      element.hidden = element.id !== 'tab-content-dynamics'
    })
    document.getElementById('simulate-body')?.style.setProperty('display', 'block')
  })
  await expect(page.locator('#simulate-body')).toBeVisible()
  await page.click('.engine-selector-btn[data-engine="namd"]')
  await expect(page.locator('#md-jobs-new-btn')).toBeVisible()
}

async function broadcastConnected(page) {
  await page.evaluate(() => window.dispatchEvent(new CustomEvent(
    'nadoc:cluster-state-change', { detail: { state: 'connected' } },
  )))
}

test.beforeEach(async ({ request }) => {
  const response = await request.post(`${API}/design/load`, {
    data: { path: DESIGN_PATH },
    headers: { 'Content-Type': 'application/json', 'X-NADOC-Doc': DOC },
  })
  expect(response.ok(), 'POST /design/load failed').toBeTruthy()
})

test('maintenance warning is visible in the Cluster card and beside GPU selection', async ({ page }) => {
  await page.route('**/api/cluster/status', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ state: 'connected', who: 'test@login.rc.colorado.edu' }),
  }))
  await page.route('**/api/cluster/availability*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(AVAILABILITY),
  }))

  await openNAMD(page)

  // The warning is inside the actual Clusters card's Alpine pane, not only in the
  // GPU-availability popup.
  await page.locator('#md-run-target-alpine').check()
  await broadcastConnected(page)
  const clusterWarning = page.locator(
    '#md-jobs-cluster-card #md-jobs-alpine-availability .alpine-scheduler-warning',
  )
  await expect(clusterWarning).toBeVisible()
  await expect(clusterWarning).toContainText('Alpine maintenance affects scheduling')
  await expect(clusterWarning).toContainText('2026-09-03 06:30')

  // The same status remains visible in step 1 while the user is looking at and
  // selecting a concrete GPU resource.
  await page.locator('#md-jobs-new-btn').click()
  const wizard = page.locator('.modal--wizard')
  await expect(wizard).toBeVisible()
  await wizard.locator('.wiz-target-card[data-target="alpine"] > div').first().click()
  await broadcastConnected(page)
  await expect(wizard.locator('.wiz-part-row[data-partition="ah200"]')).toBeVisible()
  const wizardWarning = wizard.locator(
    '#wiz-target-alpine-scheduler-warning .alpine-scheduler-warning',
  )
  await expect(wizardWarning).toBeVisible()
  await expect(wizardWarning).toContainText("SLURM's next available start for ah200")
})
