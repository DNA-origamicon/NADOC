/** Real native CPU-MC / GPU-MD smoke workflows; no engine or job API mocks. */
import { expect, test } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { OxdnaWizardDriver } from './helpers/oxdna_wizard_driver.js'

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../workspace')
const jobs = new Set()
const dnaCopy = 'playwright_tests/__e2e__physics_DNA.nadoc'

test.beforeAll(async () => {
  await fs.mkdir(path.join(workspace, 'playwright_tests'), { recursive: true })
  const design = JSON.parse(await fs.readFile(path.join(workspace, '2hb_1xT.nadoc'), 'utf8'))
  design.id = randomUUID()
  design.metadata.name = '__e2e__physics_DNA'
  delete design.metadata.identity_last_known_path
  delete design.metadata.identity_confirmed_at
  design.chain_sim_projects = []
  await fs.writeFile(path.join(workspace, dnaCopy), JSON.stringify(design))
})

test.afterEach(async ({ request }) => {
  for (const id of jobs) {
    await request.post(`/api/oxdna/jobs/${id}/stop`)
    await expect.poll(async () => {
      const response = await request.get(`/api/oxdna/jobs/${id}`)
      if (response.status() === 404) return true
      return ['completed', 'failed', 'stopped', 'queued'].includes((await response.json()).status)
    }, { timeout: 15000 }).toBe(true)
    const deleted = await request.delete(`/api/oxdna/jobs/${id}`)
    expect([200, 404]).toContain(deleted.status())
  }
  jobs.clear()
})
test.afterAll(async () => { await fs.rm(path.join(workspace, dnaCopy), { force: true }) })

async function openNewWizard(page) {
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await expect(page.locator('#oxdna-jobs-new-btn')).toBeEnabled({ timeout: 20000 })
  await page.locator('#oxdna-jobs-new-btn').click()
  const driver = new OxdnaWizardDriver(page)
  await expect(driver.modal).toBeVisible()
  return driver
}

async function runPrepared(page, driver, { hybrid = false } = {}) {
  await driver.tab('Parameters & options')
  await expect(driver.modal.locator('[data-oxdna-field="backend"]')).toHaveValue('CUDA')
  for (const [name, value] of Object.entries({ mc_steps: 1000, md_relax_steps: 10000, equil_steps: 1000, min_bp_retained: 0, max_relax_retries: 0 }))
    await driver.field(name, value)
  if (hybrid) {
    await driver.stageValue('Thermostat', 2, 'john')
    await expect(driver.modal.locator('.modal__actions button', { hasText: 'Create job' })).toBeDisabled()
    await driver.stageValue('Diffusion coefficient', 2, '0.1')
    await driver.stageValue('Refresh velocities', 2, 'false')
    const config = driver.modal.locator('.oxdna-wizard-config')
    await expect(config).toContainText('interaction_type = DNANM')
    await expect(config).toContainText('dt = 0.0001')
  }
  const created = page.waitForResponse(r => new URL(r.url()).pathname === '/api/oxdna/jobs' && r.request().method() === 'POST')
  await driver.create()
  const response = await created
  expect(response.ok(), await response.text()).toBe(true)
  const job = await response.json(); jobs.add(job.job_id)
  expect(job.backend).toBe('CUDA')
  await expect(driver.modal).toBeHidden()
  await expect(page.locator('#oxdna-jobs-run-btn')).toBeEnabled({ timeout: 20000 })
  await page.locator('#oxdna-jobs-run-btn').click()
  let result
  await expect.poll(async () => {
    result = await page.evaluate(async id => {
      const api = await import('/src/api/client.js')
      return api.getOxdnaJob(id)
    }, job.job_id)
    return result?.status
  }, { timeout: 120000, intervals: [500, 1000] }).toMatch(/completed|failed/)
  expect(result.status, JSON.stringify(result)).toBe('completed')
  const root = path.join(workspace, 'oxdna_jobs', job.job_id)
  for (const stage of ['1_mc_relax', '2_md_relax', '3_equil']) {
    const input = await fs.readFile(path.join(root, stage, 'input.txt'), 'utf8')
    expect(input).toContain(`backend = ${stage === '1_mc_relax' ? 'CPU' : 'CUDA'}`)
    if (hybrid) {
      expect(input).toContain('interaction_type = DNANM')
      expect(input).toContain('fix_diffusion = false')
      if (stage === '3_equil') {
        expect(input).toContain('thermostat = john')
        expect(input).toContain('diff_coeff = 0.1')
        expect(input).toContain('refresh_vel = false')
      }
    } else {
      expect(input).toContain('use_average_seq = false')
      expect(input).toContain('oxDNA2_average_sequence_parameters.txt')
    }
    const conf = await fs.readFile(path.join(root, stage, 'last_conf.dat'), 'utf8')
    const rows = conf.trim().split('\n').slice(3).map(line => line.trim().split(/\s+/).map(Number))
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.every(row => row.length === 15 && row.every(Number.isFinite))).toBe(true)
    if (hybrid) expect(rows.length).toBe(500)
  }
  if (!await page.locator('#oxdna-jobs-viz-body').isVisible()) await page.locator('#oxdna-jobs-viz-toggle').click()
  await page.locator('#oxdna-jobs-display-toggle').check()
  await expect(page.locator('#oxdna-jobs-display-toggle')).toBeChecked()
  await expect(page.locator('#oxdna-jobs-display-status')).toContainText('Showing relaxed positions', { timeout: 30000 })
  return job
}

test('DNA-only: create, run default GPU stages, and display native output', async ({ page }) => {
  test.setTimeout(180000)
  const driver = new OxdnaWizardDriver(page)
  await driver.open(dnaCopy)
  await runPrepared(page, driver)
})

test('gold/strep/DNA: conjugate, configure local bath, run default GPU, display', async ({ page }) => {
  test.setTimeout(240000)
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__physics_gold_strep_DNA')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles))
  await page.evaluate(async () => {
    const t = window.__nadocTest
    await t.nanoparticles.create(10)
    await t.nanoparticles.conjugation.open(t.store.getState().currentDesign.nanoparticles[0].id)
  })
  await page.selectOption('#np-conj-scheme', 'streptavidin')
  await page.fill('#strep-count', '1')
  await page.click('#strep-apply')
  await expect(page.locator('#nanoparticle-conjugate-overlay')).toHaveCount(0, { timeout: 60000 })
  await page.evaluate(async () => {
    const t = window.__nadocTest
    await t.nanoparticles.conjugation.open(t.store.getState().currentDesign.nanoparticles[0].id)
  })
  await page.fill('#strep-dna-sequence', 'ACGTACGTACGTACGT')
  await page.click('#strep-dna-create')
  await expect(page.locator('#strep-dna-current')).toContainText('1 attached', { timeout: 60000 })
  await page.click('#strep-apply')
  await expect(page.locator('#nanoparticle-conjugate-overlay')).toHaveCount(0, { timeout: 60000 })
  await runPrepared(page, await openNewWizard(page), { hybrid: true })
})
