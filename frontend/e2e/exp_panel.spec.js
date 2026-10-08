import { expect, test } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persistence inventory: helper-created __e2e__exp-* parts + their project histories
// are removed by global-teardown. Session caches are disabled by the smoke config.
// The real-model test creates one memory-only Exp job; no job/model files are written.
// Contract fixtures intercept HTTP only. No NAMD jobs are created.
// Screenshots go exclusively to Playwright's configured test output directory.
test('Exp runs the installed CPU model and retains ordinary engine controls', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await loadScaffoldedPart(page, { doc: '__e2e__exp-empty', name: 'exp-empty' })
  while (await page.locator('.sidebar-close').count()) await page.locator('.sidebar-close').first().click()
  await page.evaluate(() => {
    const entries = window.__nadocTest.getDesignRenderer().getBackboneEntries()
    const positions = entries.map(e => Array.from(e.instMesh.instanceMatrix.array.slice(e.id * 16 + 12, e.id * 16 + 15)))
    const lo = [0, 1, 2].map(i => Math.min(...positions.map(p => p[i])))
    const hi = [0, 1, 2].map(i => Math.max(...positions.map(p => p[i])))
    const target = lo.map((v, i) => (v + hi[i]) / 2)
    const span = Math.max(...lo.map((v, i) => hi[i] - v))
    window.__nadocTest.applyCameraPoseForTest({ target, position: target.map((v, i) => v + span * [1.2, .5, .5][i]), up: [0, 0, 1], fov: 45 })
  })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('[data-engine="exp"]').click()
  await expect(page.locator('#exp-jobs-panel')).toBeVisible()
  await expect(page.locator('#simulate-jobs')).toBeHidden()
  const completedResponse = page.waitForResponse(async response => response.url().includes('/api/exp/jobs/') && response.request().method() === 'GET' && (await response.json()).status === 'completed')
  await page.locator('#exp-run').click()
  await expect(page.locator('#exp-status')).toContainText('0×T all-atom strain pilot')
  await expect(page.locator('#exp-run')).toHaveText('Run')
  await expect(page.locator('#exp-viz')).toBeEnabled()
  await expect(page.locator('#exp-progress')).toHaveAttribute('value', '1')
  const prediction = (await (await completedResponse).json()).result
  expect(prediction.atoms.includes_hydrogens).toBe(true)
  expect(prediction.atoms.elements).toContain('H')
  expect(prediction.positions_nm.length).toBeGreaterThan(20 * prediction.full.keys.length)
  const display = () => page.evaluate(() => {
    const renderer = window.__nadocTest.getDesignRenderer()
    return {
      updates: renderer.getFemPositions(),
      positions: renderer.getBackboneEntries().map(e => Array.from(e.instMesh.instanceMatrix.array.slice(e.id * 16 + 12, e.id * 16 + 15))),
      colors: window.__nadocTest.nativeBackboneColorCensus(),
      pointCloud: !!window.__nadocTest.scene.getObjectByName('exp-screening-preview'),
    }
  })
  const native = await display()
  const nativePixels = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
  await page.locator('#exp-viz').check()
  const predicted = await display()
  expect(predicted.updates.length).toBe(prediction.full.keys.length)
  expect(predicted.positions).not.toEqual(native.positions)
  expect(predicted.colors).toEqual(native.colors)
  expect(predicted.pointCloud).toBe(false)
  const predictedPixels = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
  expect(predictedPixels.colorful).toBeGreaterThan(200)
  expect(predictedPixels.pixelHash).not.toBe(nativePixels.pixelHash)
  // Negative visibility control: the colored pixels must belong to the DNA.
  const hiddenPixels = await page.evaluate(() => {
    window.__nadocTest.getDesignRenderer().setDesignVisible(false)
    const census = window.__nadocTest.renderedPixelCensus()
    window.__nadocTest.getDesignRenderer().setDesignVisible(true)
    return census
  })
  expect(hiddenPixels.colorful).toBeLessThan(predictedPixels.colorful / 2)
  await page.locator('#exp-viz').uncheck()
  expect((await display()).positions).toEqual(native.positions)
  await page.locator('#exp-viz').check()
  await page.evaluate(() => window.__nadocTest.setRepresentation('cylinders'))
  await expect(page.locator('#exp-viz')).toBeDisabled()
  await expect(page.locator('#exp-viz')).not.toBeChecked()
  expect((await display()).updates).toBeNull()
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  await expect(page.locator('#exp-viz')).toBeEnabled()
  expect((await display()).positions).toEqual(native.positions)
  await page.locator('#exp-viz').check()
  await page.screenshot({ path: testInfo.outputPath('exp-controls.png') })
  await page.locator('[data-engine="namd"]').click()
  await expect(page.locator('#exp-jobs-panel')).toBeHidden()
  await expect(page.locator('#simulate-jobs')).toBeVisible()
  expect(errors, errors.join('\n')).toEqual([])
})

test('Exp contract fixture exercises progress, Stop, and isolated preview teardown', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__exp-preview', name: 'exp-preview' })
  let stopped = false, complete = false
  const keys = await page.evaluate(() => window.__nadocTest.getDesignRenderer().getBackboneEntries().map(({ nuc }) => [nuc.helix_id, nuc.bp_index, nuc.direction, 0]))
  const result = { full: { keys, frame: keys.flatMap((_, i) => [0, 0, i, 1, 0, 0, 0, 0, 1, 1, 0, i]) }, label: 'UI test fixture only' }
  await page.route('**/api/exp/**', async route => {
    const url = new URL(route.request().url())
    let payload
    if (url.pathname.endsWith('/status')) payload = { available: true }
    else {
      if (url.pathname.endsWith('/stop')) stopped = true
      payload = { job_id: 'fixture', status: stopped ? 'stopped' : complete ? 'completed' : 'running',
        progress: complete ? 1 : .35, message: stopped ? 'Stopped' : complete ? 'Complete' : 'Predicting',
        result: complete ? result : null }
    }
    await route.fulfill({ json: payload })
  })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('[data-engine="exp"]').click()
  await page.locator('#exp-run').click()
  await expect(page.locator('#exp-progress')).toHaveAttribute('value', '0.35')
  await expect(page.locator('#exp-run')).toHaveText('Stop')
  await page.locator('#exp-run').click()
  await expect(page.locator('#exp-run')).toHaveText('Run')
  expect(stopped).toBe(true)
  stopped = false; complete = true
  await page.locator('#exp-run').click()
  await expect(page.locator('#exp-viz')).toBeEnabled()
  const previewPresent = () => page.evaluate(() => !!window.__nadocTest.getDesignRenderer().getFemPositions())
  expect(await previewPresent()).toBe(false)
  await page.locator('#exp-viz').check()
  expect(await previewPresent()).toBe(true)
  await page.locator('[data-engine="namd"]').click()
  expect(await previewPresent()).toBe(false)
  expect(errors, errors.join('\n')).toEqual([])
})

test('Exp assembly prediction displays a frozen Full model and restores the authored assembly', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__exp-assembly', name: 'exp-assembly-source' })
  await page.evaluate(async () => {
    const design = window.__nadocTest.store.getState().currentDesign
    const api = await import('/src/api/client.js')
    await api.importAssembly(JSON.stringify({ id: '__e2e__exp-assembly', metadata: { name: '__e2e__exp-assembly' },
      instances: [{ id: 'source', name: 'Source', source: { type: 'inline', design }, representation: 'full' }] }))
    await window.__nadocTest.enterAssemblyMode()
  })
  await page.waitForFunction(() => window.__NADOC_DBG__.assemblyRenderer.getInstanceCenters().length === 1)
  const original = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentAssembly))
  while (await page.locator('.sidebar-close').count()) await page.locator('.sidebar-close').first().click()
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('[data-engine="exp"]').click()
  await page.locator('#exp-run').click()
  await expect(page.locator('#exp-viz')).toBeEnabled({ timeout: 30000 })
  await page.locator('#exp-viz').check()
  const preview = await page.evaluate(() => ({ count: window.__nadocTest.getDesignRenderer().getFemPositions()?.length,
    cgVisible: window.__nadocTest.isCGVisible(), authoring: JSON.stringify(window.__nadocTest.store.getState().currentAssembly) }))
  expect(preview.count).toBe(200)
  expect(preview.cgVisible).toBe(true)
  expect(preview.authoring).toBe(original)
  await page.locator('#exp-viz').uncheck()
  expect(await page.evaluate(() => window.__nadocTest.getDesignRenderer().getFemPositions())).toBeNull()
  expect(await page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(false)
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentAssembly))).toBe(original)
  expect(errors, errors.join('\n')).toEqual([])
})
