/** Scientific opt-in: real CPD assignment and managed package, no API mocks.
 * Persistence: __e2e__ fixture/autosaves -> global teardown; queued jobs ->
 * afterEach (also discovers jobs if creation finishes after a test failure).
 * Session cache is disabled by the dedicated-server Playwright configuration.
 */
import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { OxdnaWizardDriver } from './helpers/oxdna_wizard_driver.js'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const name = '__e2e__cpd_oxdna'
const isomers = ['cis-syn', 'cis-anti-I', 'trans-syn-I', 'trans-syn-II']
const jobs = new Set()

test.beforeAll(() => {
  if (process.env.NADOC_CPD_OXDNA_REVIEW !== '1') return
  execFileSync('uv', ['run', 'python', '-c', `from pathlib import Path
from scripts.validate_oxdna_cpd import example
from scripts.agent_structure_guard import publish
for isomer in ${JSON.stringify(['cis-syn', 'cis-anti-I', 'trans-syn-I', 'trans-syn-II'])}:
    name = '${name}_' + isomer
    publish(example(name=name, assign=False), Path('workspace') / (name + '.nadoc'))`], { cwd: root })
})
test.afterEach(async ({ request }) => {
  if (process.env.NADOC_CPD_OXDNA_REVIEW !== '1') return
  const listing = await request.get('/api/oxdna/jobs')
  for (const job of await listing.json()) if (job.design_name?.includes(name)) jobs.add(job.job_id)
  for (const id of jobs) {
    const response = await request.delete(`/api/oxdna/jobs/${id}`)
    expect([200, 404]).toContain(response.status())
  }
  const remaining = await readdir(path.join(root, 'workspace/oxdna_jobs'))
  for (const id of jobs) expect(remaining).not.toContain(id)
  jobs.clear()
})

for (const isomer of isomers) test(`assign ${isomer}, inspect atoms, create and edit a permanent oxDNA package`, async ({ page, request }, testInfo) => {
  test.skip(process.env.NADOC_CPD_OXDNA_REVIEW !== '1', 'Explicit CPD scientific review only')
  test.setTimeout(120000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const fixture = `${name}_${isomer}.nadoc`
  await page.goto(`/?doc=${name}_${isomer}&open=${encodeURIComponent(fixture)}&open-type=design`)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.strands?.length === 2)
  const keys = [6, 7].map(i => `38b9786d-4dcf-4a62-92a6-c90bc301961b:${i}:FORWARD`)
  await page.evaluate(async keys => {
    await window.__nadocTest.setRepresentation('full')
    const { store } = await import('/src/state/store.js')
    const items = keys.map(key => ({ kind: 'base', key }))
    store.setState({ selection: { items, primary: items[0] } })
  }, keys)
  await page.locator('#canvas').click({ button: 'right', position: { x: 300, y: 200 } })
  await page.getByText('Convert to CPD…', { exact: true }).click()
  await page.getByLabel('CPD type').selectOption(isomer)
  const button = page.getByRole('button', { name: 'Convert to CPD', exact: true })
  await expect(button).toBeEnabled()
  await expect(page.getByLabel('3D CPD selection preview')).toBeVisible()
  const converted = page.waitForResponse(r => r.url().endsWith('/photoproducts/convert'))
  await button.click()
  expect((await converted).ok()).toBe(true)
  await expect(button).toBeHidden()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.getObjectByName('cpdSlabBonds')?.count)).toBe(2)
  const design = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign)
  expect(design.photoproduct_junctions[0].stereochemistry).toBe(isomer)
  expect(design.feature_log.at(-1).params.conversion_version).toBe(isomer === 'cis-syn' ? 2 : 3)
  if (process.env.NADOC_CPD_VISUAL_PAUSE === '1') {
    await page.screenshot({ path: testInfo.outputPath('cpd-review.png') })
    // Explicit manual inspection window; output is removed by the cleanup reporter.
    await page.waitForTimeout(30000)
  }
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await expect(page.locator('#oxdna-jobs-new-btn')).toBeEnabled()
  await page.locator('#oxdna-jobs-new-btn').click()
  const driver = new OxdnaWizardDriver(page)
  await driver.tab('Parameters & options')
  await expect(driver.modal.locator('[data-oxdna-field="backend"]')).toHaveValue('CPU')
  await driver.tab('Full configuration')
  await expect(driver.modal.locator('.oxdna-wizard-config')).toContainText('interaction_type = CpdDNA2')
  const created = page.waitForResponse(r => new URL(r.url()).pathname === '/api/oxdna/jobs' && r.request().method() === 'POST')
  await driver.create()
  const response = await created
  expect(response.ok(), await response.text()).toBe(true)
  const job = await response.json(); jobs.add(job.job_id)
  expect(job.backend).toBe('CPU')
  const directory = path.join(root, 'workspace/oxdna_jobs', job.job_id)
  const manifest = JSON.parse(await readFile(path.join(directory, 'cpd_manifest.json'), 'utf8'))
  expect(manifest.endpoints[0].particles).toEqual([6, 7])
  expect(manifest.endpoints[0].stereochemistry).toBe(isomer)
  const edited = await request.put(`/api/oxdna/jobs/${job.job_id}/settings`, { data: { backend: 'CUDA' } })
  expect(edited.ok(), await edited.text()).toBe(true)
  expect((await edited.json()).backend).toBe('CPU')
  const stages = JSON.parse(await readFile(path.join(directory, 'stages_spec.json'), 'utf8'))
  expect(stages.every(s => s.backend === 'CPU' && s.interaction === 'CpdDNA2')).toBe(true)
  const copied = await request.post(`/api/oxdna/jobs/${job.job_id}/copy`, { data: {} })
  expect(copied.ok(), await copied.text()).toBe(true)
  const copy = (await copied.json()).job; jobs.add(copy.job_id)
  expect(JSON.parse(await readFile(path.join(root, 'workspace/oxdna_jobs', copy.job_id, 'cpd_manifest.json'), 'utf8'))).toEqual(manifest)
  expect(errors).toEqual([])
})
