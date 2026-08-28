import { expect, test } from '@playwright/test'
import { copyFile, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { OxdnaWizardDriver } from './helpers/oxdna_wizard_driver.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const GENERATED = `__e2e__oxdna_engine_${process.pid}.nadoc`
const GENERATED_PATH = path.join(ROOT, 'workspace', GENERATED)

const PREVIEW = {
  sized: true, connected: true, n_atoms: 84,
  gpus: [{ key: 'NVIDIA H200', label: 'H200', vram_gb: 141, available: true,
    eligible: true, usd_per_hour: 2, total_hours: 0.1, total_cost: 0.2 }],
  storage: { output_bytes: 1024, package_bytes: 1024, volume_size_gb: 50,
    used_known: true, free_bytes: 40 * 1024 ** 3, staging: { minutes: 0.1, usd: 0 } },
  volume: { id: 'vol-e2e', name: 'e2e', size_gb: 50 },
  balance: { available: true, balance: 10 }, live_pods: [],
  preflight: { ok: true, checks: [] },
  budget: { budget_usd: 5, estimated_usd: 0.2, over_budget: false },
}

test.beforeAll(async () => {
  // Generate an isolated, minimal duplex design from the checked-in 2-helix seed.
  await copyFile(path.join(ROOT, 'Examples', '2hb_xover_val.nadoc'), GENERATED_PATH)
})

test.afterAll(async () => {
  await rm(GENERATED_PATH, { force: true })
})

async function stubRemotePaths(page) {
  await page.route('**/api/cluster/status', route => route.fulfill({ json: {
    state: 'connected', who: 'e2e@alpine', host: 'login.rc.colorado.edu',
  } }))
  await page.route('**/api/cluster/availability**', route => route.fulfill({ json: {
    partitions: [{ partition: 'ah200', gpu_model: 'NVIDIA H200', gpus_free: 2,
      gpus_total: 8, wait_label: '~0 min', wait_basis: 'free now', speed_factor: 2.5 }],
  } }))
  await page.route('**/api/runpod/job-preview', route => route.fulfill({ json: PREVIEW }))
  await page.route('**/api/runpod/volumes', route => route.fulfill({ json: {
    volumes: [{ id: 'vol-e2e', name: 'e2e', size_gb: 50 }],
  } }))
  await page.route('**/api/runpod/volume', route => route.fulfill({ json: { ok: true } }))
}

test('all wired engine paths create local prepared-job payloads and remote previews stay inert', async ({ page }) => {
  test.setTimeout(180_000)
  await stubRemotePaths(page)
  const payloads = []
  await page.route(/\/api\/oxdna\/jobs$/, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    payloads.push(body)
    await route.fulfill({ status: 201, json: { job_id: `__e2e__${payloads.length}`,
      status: 'queued', backend: body.backend, device: body.device,
      design_name: GENERATED, stages: [], run_config: body } })
  })
  await page.route('**/api/oxdna/jobs/estimate-disk', route => route.fulfill({ json: {
    warn: false, free_bytes: 100 * 1024 ** 3, predicted_bytes: 1024,
    free_after_bytes: 100 * 1024 ** 3,
  } }))

  const engines = [['Automatic', 'auto'], ['NADOC adaptive-memory', 'adaptive-memory'],
    ['Protein-capable DNANM', 'dnanm'], ['Standard upstream oxDNA', 'upstream']]
  let n = 0
  for (const [label, variant] of engines) {
      const driver = new OxdnaWizardDriver(page)
      await driver.open(GENERATED, `__e2e__oxdna-path-local-${variant}`)
      await driver.target('local')
      await driver.engine(label)
      await driver.field('salt_concentration', 0.25)
      await driver.stageValue('Time step', 1, 0.001)
      await driver.create()
      await expect.poll(() => payloads.length).toBe(n + 1)
      const body = payloads[n++]
      expect(body).toMatchObject({ execution_target: 'local', engine_variant: variant,
        salt_concentration: 0.25, autostart: false,
        stage_overrides: { '2_md_relax': { dt: 0.001 } } })
  }
  expect(payloads).toHaveLength(engines.length)

  for (const target of ['alpine', 'runpod']) {
    const driver = new OxdnaWizardDriver(page)
    await driver.open(GENERATED, `__e2e__oxdna-preview-${target}`)
    await driver.target(target)
    await driver.tab('Full configuration')
    await expect(driver.modal.locator('.oxdna-wizard-config'))
      .toContainText(`execution_target = ${target}`)
    if (target === 'alpine')
      await expect(driver.modal.locator('.oxdna-wizard-config')).toContainText('partition = ah200')
    else
      await expect(driver.modal.locator('.oxdna-wizard-config')).toContainText('runpod_gpu_key = NVIDIA H200')
  }
  expect(payloads).toHaveLength(engines.length)
})

test('invalid protocol values block creation and explain the first error', async ({ page }) => {
  const driver = new OxdnaWizardDriver(page)
  await driver.open(GENERATED, '__e2e__oxdna-invalid')
  await driver.tab('Parameters & options')
  await driver.field('salt_concentration', 0)
  await driver.tab('Full configuration')
  await expect(driver.modal.locator('.oxdna-wizard-validation')).toContainText('at least 0.01 M')
  await expect(driver.modal.locator('.modal__actions button', { hasText: 'Create job' })).toBeDisabled()
})

for (const target of ['alpine', 'runpod']) {
  test(`${target} walks every wizard step and submits the prepared remote job`, async ({ page }) => {
    test.setTimeout(120_000)
    await stubRemotePaths(page)
    const requests = []
    await page.route('**/api/oxdna/jobs/estimate-disk', route => route.fulfill({ json: {
      warn: false, free_bytes: 100 * 1024 ** 3, predicted_bytes: 1024,
      free_after_bytes: 100 * 1024 ** 3,
    } }))
    await page.route(/\/api\/oxdna\/jobs$/, async route => {
      if (route.request().method() !== 'POST') return route.continue()
      const body = route.request().postDataJSON()
      requests.push(body)
      await route.fulfill({ status: 201, json: { job_id: `__e2e__remote-${target}`,
        status: 'running', execution_target: target, stages: [], run_config: body } })
    })

    const driver = new OxdnaWizardDriver(page)
    await driver.open(GENERATED, `__e2e__oxdna-submit-${target}`)
    await driver.target(target) // step 1: connected target and hardware selection
    await driver.tab('Parameters & options') // step 2
    await expect(driver.modal.locator('[data-oxdna-field="salt_concentration"]')).toBeVisible()
    await driver.field('salt_concentration', 0.3)
    await driver.tab('Full configuration') // step 3
    await expect(driver.modal.locator('.oxdna-wizard-config'))
      .toContainText(`execution_target = ${target}`)
    await driver.create()

    await expect.poll(() => requests.length).toBe(1)
    expect(requests[0]).toMatchObject({
      execution_target: target, autostart: true, salt_concentration: 0.3,
    })
    if (target === 'alpine') {
      expect(requests[0]).toMatchObject({ cluster_name: 'alpine', partition: 'ah200' })
    } else {
      expect(requests[0]).toMatchObject({ runpod_gpu_key: 'NVIDIA H200',
        runpod_volume_id: 'vol-e2e', runpod_quoted_rate_usd_per_hour: 2 })
    }
  })
}
