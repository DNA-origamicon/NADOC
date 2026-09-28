import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Opt-in native integration check. Run ONLY under the isolated-workspace wrapper:
// all jobs, logs, snapshots, project revisions and __e2e__ autosaves land in that
// disposable workspace. The wrapper terminates its workers and removes it in a
// finally block after Playwright shuts down its servers, including on failure.
for (const copies of [30, 2]) test(`BigO ${copies} copies launch and display real CanDo and SNUPI predictions`, async ({ page, request }) => {
  test.skip(!process.env.NADOC_E2E_FEM_ISOLATED, 'Requires disposable workspace and worker cleanup')
  test.setTimeout(1500000)
  page.setDefaultTimeout(180000)
  const fixture = new URL('../../workspace/BigO-poly.nass', import.meta.url)
  test.skip(!existsSync(fixture), 'Local BigO fixture is not installed')
  const original = readFileSync(fixture, 'utf8'), assembly = JSON.parse(original)
  const doc = `__e2e__bigo_fem_${copies}`
  assembly.id = doc; assembly.metadata.name = doc
  assembly.instances_v2 = assembly.instances_v2.slice(0, copies)
  const ids = new Set(assembly.instances_v2.map(instance => instance.id))
  assembly.joints = assembly.joints.filter(joint => ids.has(joint.instance_a_id) && ids.has(joint.instance_b_id))
  assembly.feature_log = []; assembly.feature_log_cursor = -1
  // Keep original source read-only even under an isolated workspace.
  for (const source of Object.values(assembly.sources ?? {})) {
    if (source.path) source.path = path.resolve(new URL('../../workspace/', import.meta.url).pathname, source.path)
  }
  const errors = trackConsoleErrors(page), preparation = [], partGeometry = []
  page.on('request', req => {
    if (req.url().includes('/flatten/load-as-design')) preparation.push(req.url())
    if (req.url().includes('/design/geometry')) partGeometry.push(req.url())
  })
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async assembly => {
    await (await import('/src/api/client.js')).importAssembly(JSON.stringify(assembly))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, assembly)
  await page.waitForFunction(copies => window.__NADOC_DBG__?.assemblyRenderer.getInstanceCenters().length === copies, copies)
  console.log('BigO rendered')
  while (await page.locator('.sidebar-close').count()) await page.locator('.sidebar-close').first().click()
  await page.evaluate(() => {
    const debug = window.__NADOC_DBG__
    debug.setCameraDist(debug.fitDist(1.3), [1, 1, 1])
  })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  const before = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.id ?? null)
  partGeometry.length = 0
  const apiBase = process.env.NADOC_E2E_API_BASE + '/api'
  const headers = { 'X-NADOC-Doc': doc }
  for (const engine of ['cando', 'snupi']) {
    await page.locator(`.engine-selector-btn[data-engine="${engine}"]`).click()
    // Explicit static solve; full NMA/thermal sampling is a separate expensive option.
    await page.locator(`#${engine}-jobs-adv-toggle`).click()
    await page.locator(`#${engine}-jobs-with-rmsf`).uncheck()
    const launched = page.waitForResponse(r => r.url().endsWith(`/${engine}/jobs`) && r.request().method() === 'POST', { timeout: 180000 })
    await page.locator(`#${engine}-jobs-coarse-btn`).click()
    const response = await launched
    expect(response.ok()).toBe(true)
    const job = await response.json()
    if (copies === 30) expect(job.n_nucleotides).toBe(424144)
    else expect(job.n_nucleotides).toBeGreaterThan(28000)
    console.log(`${engine} submitted ${job.job_id}`)
    let final
    await expect.poll(async () => {
      const result = await request.get(`${apiBase}/${engine}/jobs/${job.job_id}`, { headers, maxRetries: 2 })
      final = await result.json()
      return final.status
    }, { timeout: 300000, intervals: [2000, 5000] }).toBe('completed')
    console.log(`${engine} completed: ${final.sim_seconds}s, ${final.n_nodes} nodes`)
    expect(final.n_nodes).toBe(7056 * copies)
    // Full BigO nucleotide rendering saturates headless SwiftShader (~80 s/frame).
    // Use the regular cylinder result view at 30 copies and verify full snapshot
    // deformation separately on two copies, through the same assembly host.
    const mode = copies === 30 ? 'cando' : 'deform'
    if (engine === 'snupi') {
      await page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`).click()
    }
    const radio = page.locator(`.${engine}-display-mode[value="${mode}"]`)
    await expect(radio).toBeEnabled({ timeout: 60000 })
    const resultPath = copies === 30 ? 'cylinders' : 'snapshot-geometry'
    const resultResponse = page.waitForResponse(r => r.url().includes(`/${engine}/jobs/${job.job_id}/${resultPath}`), { timeout: 180000 })
    await radio.check()
    expect((await resultResponse).ok()).toBe(true)
    const status = copies === 30 ? 'CanDo-style cylinders' : 'Showing predicted shape.'
    await expect(page.locator(`#${engine}-jobs-display-status`)).toContainText(status, { timeout: 180000 })
    if (copies === 2) {
      expect(await page.evaluate(() => window.__NADOC_DBG__.designRenderer.getFemPositions().length)).toBe(job.n_nucleotides)
    }
    console.log(`${engine} ${copies}-copy ${mode} result displayed`)
    await page.locator(`.${engine}-display-mode[value="off"]`).check({ force: true })
    expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.id ?? null)).toBe(before)
  }
  expect(preparation).toHaveLength(1)
  expect(preparation[0]).toContain('simulation_only=true')
  expect(partGeometry).toEqual([])
  expect(readFileSync(fixture, 'utf8')).toBe(original)
  expect(errors, errors.join('\n')).toEqual([])
})
