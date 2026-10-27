/**
 * oxDNA relaxation setup, stopping at the launch boundary.
 *
 * These tests exercise the real Dynamics UI and request construction, but intercept
 * job creation so no oxDNA process is started and no job directory is created.
 */
import { expect, test } from '@playwright/test'

const DOC = '__e2e__oxdna-setup'
const OPEN_URL = `/?doc=${DOC}&open=2hb_1xT.nadoc&open-type=design`

async function openOxdna(page) {
  await page.goto(OPEN_URL)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await expect(page.locator('#oxdna-jobs-body')).toBeVisible()
  await expect(page.locator('#oxdna-jobs-new-btn')).toBeEnabled({ timeout: 15_000 })
}

test('oxDNA setup controls are accessible and do not create or start a job', async ({ page }) => {
  test.setTimeout(90_000)
  let creates = 0
  let starts = 0
  page.on('request', request => {
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST' && path === '/api/oxdna/jobs') creates++
    if (request.method() === 'POST' && /\/api\/oxdna\/jobs\/[^/]+\/start$/.test(path)) starts++
  })

  await openOxdna(page)
  await page.locator('#oxdna-jobs-adv-toggle').click()
  await expect(page.locator('#oxdna-jobs-adv-body')).toBeVisible()

  await page.selectOption('#oxdna-jobs-backend', 'CPU')
  await page.fill('#oxdna-jobs-device', '2')
  await page.fill('#oxdna-jobs-salt', '0.25')
  await page.fill('#oxdna-jobs-mc-steps', '500')
  await page.fill('#oxdna-jobs-md-steps', '250000')
  await page.fill('#oxdna-jobs-equil-steps', '25000')
  await page.fill('#oxdna-jobs-bp-gate', '0.7')

  await page.locator('#oxdna-floor-toggle').click()
  await page.check('#oxdna-floor-enable')
  await page.fill('#oxdna-floor-offset', '12.5')
  await page.fill('#oxdna-floor-stiff', '7.5')

  // Configuration alone is inert: it must not prepare or start anything.
  await page.waitForTimeout(500)
  expect(creates).toBe(0)
  expect(starts).toBe(0)
  await expect(page.locator('#oxdna-jobs-run-btn')).toHaveText(/Run/)
})

test('New job assembles a prepared payload without running oxDNA', async ({ page }) => {
  test.setTimeout(90_000)
  const payloads = []
  let starts = 0

  await page.route('**/api/simulate/recommendation**', route => route.fulfill({
    json: { gpu: { busy: false }, recommendation: { engine: 'oxdna', backend: 'CUDA' }, free_cores: 4 },
  }))
  await page.route('**/api/oxdna/jobs/estimate-disk', async route => {
    payloads.push({ kind: 'estimate', body: route.request().postDataJSON() })
    await route.fulfill({ json: {
      warn: false, free_bytes: 100 * 1024 ** 3, predicted_bytes: 1024,
      free_after_bytes: 100 * 1024 ** 3,
    } })
  })
  await page.route(/\/api\/oxdna\/jobs$/, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    payloads.push({ kind: 'create', body: route.request().postDataJSON() })
    await route.fulfill({ status: 201, json: {
      job_id: '__e2e__prepared-only', status: 'queued', backend: 'CPU', device: '3',
      design_name: '2hb_1xT', stages: [], run_config: route.request().postDataJSON(),
    } })
  })
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/oxdna\/jobs\/[^/]+\/start$/.test(new URL(request.url()).pathname)) starts++
  })

  await openOxdna(page)
  await page.locator('#oxdna-jobs-adv-toggle').click()
  await page.selectOption('#oxdna-jobs-backend', 'CPU')
  await page.fill('#oxdna-jobs-device', '3')
  await page.fill('#oxdna-jobs-salt', '0.35')
  await page.fill('#oxdna-jobs-mc-steps', '750')
  await page.fill('#oxdna-jobs-md-steps', '350000')
  await page.fill('#oxdna-jobs-equil-steps', '35000')
  await page.fill('#oxdna-jobs-bp-gate', '0.65')

  await page.locator('#oxdna-jobs-new-btn').click()
  const wizard = page.locator('.modal--oxdna-wizard')
  await expect(wizard).toBeVisible()
  await wizard.locator('.wizard-tab', { hasText: 'Full configuration' }).click()
  await wizard.locator('.modal__actions button', { hasText: 'Create job' }).click()
  await expect.poll(() => payloads.filter(entry => entry.kind === 'create').length).toBe(1)
  await expect(wizard).toBeHidden()

  const estimate = payloads.find(entry => entry.kind === 'estimate').body
  const create = payloads.find(entry => entry.kind === 'create').body
  expect(estimate).toEqual(create)
  expect(create).toMatchObject({
    backend: 'CPU', device: '3', salt_concentration: 0.35,
    mc_steps: 750, md_relax_steps: 350000, equil_steps: 35000,
    min_bp_retained: 0.65, autostart: false, design_source_path: '2hb_1xT.nadoc',
  })
  expect(starts).toBe(0)

  // The POST above was intercepted: the isolated backend must still have no such job.
  const jobs = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    return await api.listOxdnaJobs()
  })
  expect(jobs.some(job => job.job_id === '__e2e__prepared-only')).toBe(false)
})

test('surface deposition is a saved toggle on a queued job and only Run starts it', async ({ page }) => {
  test.setTimeout(90_000)
  const job = { job_id: '__e2e__deposition-toggle', parent_job_id: '__e2e__relaxed',
    design_source_path: '2hb_1xT.nadoc', design_name: '2hb_1xT', status: 'queued', backend: 'CPU',
    created_at: 1, stages: [{ name: '1_production', kind: 'production', status: 'pending', steps: 1000 }],
    run_config: { kind: 'run', surface: { dir: [0, 1, 0], position_nm: -10, stiff: 5 },
      surface_anchors: [{ kind: 'strand', id: 'test-anchor' }], anchors: [] } }
  const patches = [], starts = []
  await page.route(/\/api\/oxdna\/jobs(?:\?.*)?$/, route => route.fulfill({ json: [job] }))
  await page.route(`**/api/oxdna/jobs/${job.job_id}`, route => route.fulfill({ json: job }))
  await page.route(`**/api/oxdna/jobs/${job.job_id}/settings`, async route => {
    const patch = route.request().postDataJSON(); patches.push(patch)
    Object.assign(job.run_config, patch, { kind: patch.surface_deposition ? 'surface_deposition' : 'run' })
    await route.fulfill({ json: job })
  })
  await page.route(`**/api/oxdna/jobs/${job.job_id}/start`, async route => {
    starts.push(route.request().postDataJSON())
    job.status = 'running'
    await route.fulfill({ json: { ok: true, job_id: job.job_id, status: 'running' } })
  })
  await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [{ ...job, engine: 'oxdna', kind: job.run_config.kind }] }))
  await page.route('**/api/jobs/active', route => route.fulfill({ json: { jobs: [] } }))
  await openOxdna(page)
  await page.locator(`[data-job-id="${job.job_id}"]:visible`).first().click()
  await page.locator('#oxdna-anchors-toggle').click()
  const toggle = page.getByRole('checkbox', { name: 'Surface deposition', exact: true })
  await expect(toggle).toBeEnabled()
  await toggle.check()
  await expect.poll(() => patches.length).toBeGreaterThan(0)
  expect(patches.at(-1).surface_deposition).toBe(true)
  expect(starts).toHaveLength(0)
  await toggle.uncheck()
  await expect.poll(() => patches.at(-1).surface_deposition).toBe(false)
  await toggle.check()
  await page.locator('#oxdna-jobs-run-btn').click()
  await expect.poll(() => starts.length).toBe(1)
  expect(patches.at(-1).surface_deposition).toBe(true)
  await expect(toggle).toBeDisabled()
})
