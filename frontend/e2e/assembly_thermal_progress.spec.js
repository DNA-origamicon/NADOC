import { readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Artifact inventory: --thermal wrapper owns the unique disposable workspace,
// all __e2e__ sources/assemblies, jobs/results/revisions/logs and bridge credential.
// Its finally block removes them after worker shutdown; reporter removes traces.
test('assembly CanDo thermal prediction reports frames and displays the result', async ({ page, request }) => {
  test.skip(!process.env.NADOC_E2E_THERMAL_FIXTURE, 'Run scripts/verify_assembly_fem.py --thermal')
  test.setTimeout(180000)
  const assembly = JSON.parse(readFileSync(process.env.NADOC_E2E_THERMAL_FIXTURE, 'utf8'))
  const doc = '__e2e__thermal_progress'
  assembly.id = doc; assembly.metadata.name = doc
  const errors = trackConsoleErrors(page)
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async assembly => {
    await (await import('/src/api/client.js')).importAssembly(JSON.stringify(assembly))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, assembly)
  await page.waitForFunction(() => window.__NADOC_DBG__.assemblyRenderer.getInstanceCenters().length === 3)
  while (await page.locator('.sidebar-close').count()) await page.locator('.sidebar-close').first().click()
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="cando"]').click()
  const launch = page.waitForResponse(r => r.url().endsWith('/cando/jobs') && r.request().method() === 'POST')
  await page.locator('#cando-jobs-coarse-btn').click()
  const response = await launch
  expect(response.ok()).toBe(true)
  const job = await response.json()
  expect(job.with_rmsf).toBe(true)
  expect(job.with_thermal_fluctuations).toBe(true)
  await expect(page.locator('#simulate-jobs-status')).toContainText(/thermal.*\d+\/48 frames/i, { timeout: 120000 })
  const api = process.env.NADOC_E2E_API_BASE + '/api'
  const headers = { 'X-NADOC-Doc': doc }
  await expect.poll(async () => (await (await request.get(`${api}/cando/jobs/${job.job_id}`, { headers })).json()).status,
    { timeout: 120000 }).toBe('completed')
  const progress = await (await request.get(`${api}/cando/jobs/${job.job_id}/progress`, { headers })).json()
  expect(progress.overall).toBe(1)
  expect(progress.phases.at(-1).label).toBe('Results saved')
  const thermal = await (await request.get(`${api}/cando/jobs/${job.job_id}/thermal-trajectory`, { headers })).json()
  expect(thermal.n_frames).toBe(48)
  expect(thermal.frames).toHaveLength(48)
  expect(thermal.frames[0]).toHaveLength(3 * thermal.keys.length)
  await page.locator('.cando-display-mode[value="deform"]').check()
  await expect(page.locator('#cando-jobs-display-status')).toContainText('representative 298 K thermal conformation', { timeout: 30000 })
  expect(await page.evaluate(() => window.__NADOC_DBG__.designRenderer.getFemPositions().length)).toBeGreaterThan(2000)
  await page.locator('.cando-display-mode[value="off"]').check()
  expect(errors, errors.join('\n')).toEqual([])
})
