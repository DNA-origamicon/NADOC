import { existsSync, readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { trackConsoleErrors, loadScaffoldedPart } from './helpers/scene_harness.js'

// Artifact inventory: __e2e__ assembly autosaves only (global-teardown removes
// these on failure too); session cache disabled by config. No jobs are launched,
// originals stay read-only, screenshots/traces use the configured output folder.
test('BigO simulation tabs browse without materializing the assembly', async ({ page }) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(30000)
  await page.setViewportSize({ width: 1280, height: 720 })
  const fixture = new URL('../../workspace/BigO-poly.nass', import.meta.url)
  test.skip(!existsSync(fixture), 'Local BigO fixture is not installed')
  const original = readFileSync(fixture, 'utf8')
  const assembly = JSON.parse(original)
  assembly.id = '__e2e__bigo_simulations'; assembly.metadata.name = '__e2e__bigo_simulations'
  const flatten = []
  // Fail safely on the old behavior without blocking the isolated server with a
  // full BigO projection. Requests are observed before any response interception.
  await page.route('**/api/assembly/flatten/load-as-design', async route => {
    flatten.push(route.request().url())
    await route.fulfill({ json: {} })
  })
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=__e2e__bigo_simulations')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async assembly => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(JSON.stringify(assembly))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, assembly)
  console.log('BigO import complete')
  await page.waitForFunction(() => window.__NADOC_DBG__?.assemblyRenderer.getInstanceCenters().length === 30, null, { timeout: 60000 })
  console.log('BigO renderer ready')
  while (await page.locator('.sidebar-close').count()) await page.locator('.sidebar-close').first().click()
  await page.keyboard.press('f')
  const initial = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.id ?? null)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  for (const engine of ['oxdna', 'mrdna', 'cando', 'snupi', 'namd']) {
    const button = page.locator(`.engine-selector-btn[data-engine="${engine}"]`)
    const start = Date.now()
    await button.click()
    await expect(button).toHaveAttribute('aria-selected', 'true')
    console.log(`${engine} tab interactive in ${Date.now() - start} ms`)
  }
  expect(flatten).toEqual([])
  const facts = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const recommendation = await api.simulateRecommendation()
    const jobs = await api.listSimJobs(null, false, { waitForIdle: false })
    return { recommendation, jobs, designId: window.__nadocTest.store.getState().currentDesign?.id ?? null }
  })
  expect(flatten).toEqual([])
  expect(facts.recommendation.n_nucleotides).toBeGreaterThan(100000)
  expect(facts.jobs).toEqual([])
  expect(facts.designId).toBe(initial)
  expect(readFileSync(fixture, 'utf8')).toBe(original)
  expect(errors, errors.join('\n')).toEqual([])
})


test('standard part simulation tabs and recommendation still work', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__part_simulations', name: 'part_simulations' })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  for (const engine of ['cando', 'snupi', 'mrdna', 'oxdna', 'namd']) {
    const button = page.locator(`.engine-selector-btn[data-engine="${engine}"]`)
    await button.click()
    await expect(button).toHaveAttribute('aria-selected', 'true')
  }
  const facts = await page.evaluate(async () => (await import('/src/api/client.js')).simulateRecommendation())
  expect(facts.n_nucleotides).toBe(200)
  expect(errors, errors.join('\n')).toEqual([])
})
