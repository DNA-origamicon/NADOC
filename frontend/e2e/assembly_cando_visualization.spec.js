import { readFileSync } from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Artifact inventory: wrapper --visualization copies only completed result inputs
// into a unique /tmp workspace. All caches, __e2e__ assembly/revisions/autosaves,
// logs and bridge credentials are deleted by its finally block after server exit.
// Playwright's global teardown/reporter remove __e2e__ documents and reports.
test('completed BigO CanDo views retain all data and remain responsive', async ({ page }) => {
  const job = process.env.NADOC_E2E_VISUALIZATION_JOB
  test.skip(!job, 'Use scripts/verify_assembly_fem.py --visualization JOB_DIR')
  test.setTimeout(360000)
  page.setDefaultTimeout(30000)
  const fixture = new URL('../../workspace/BigO-poly.nass', import.meta.url)
  const original = readFileSync(fixture, 'utf8'), assembly = JSON.parse(original)
  const doc = '__e2e__cando_visualization'
  assembly.id = doc; assembly.metadata.name = doc
  assembly.feature_log = []; assembly.feature_log_cursor = -1
  // Native cylinders alone take ~1 s/frame on SwiftShader. Keep setup/Off
  // bounded; the completed job's physical data and all result modes are unchanged.
  for (const instance of assembly.instances_v2) instance.representation = 'hull-prism' 
  for (const source of Object.values(assembly.sources)) {
    if (source.path) source.path = path.resolve(new URL('../../workspace/', import.meta.url).pathname, source.path)
  }
  const errors = trackConsoleErrors(page), requests = []
  page.on('request', r => { if (r.url().includes(`/cando/jobs/${job}/`)) requests.push(r.url()) })
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async assembly => {
    await (await import('/src/api/client.js')).importAssembly(JSON.stringify(assembly))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, assembly)
  await page.waitForFunction(() => window.__NADOC_DBG__.assemblyRenderer.getInstanceCenters().length === 30)
  console.log('BigO native assembly loaded')
  while (await page.locator('.sidebar-close').count()) await page.locator('.sidebar-close').first().click()
  await page.evaluate(() => {
    const d = window.__NADOC_DBG__; d.setCameraDist(d.fitDist(1.3), [1,1,1])
  })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="cando"]').click()
  await page.locator(`#simulate-jobs-list [data-job-id="${job}"]`).click()
  const status = page.locator('#cando-jobs-display-status')
  const initial = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentAssembly))
  for (const mode of ['deform', 'flex', 'deviation', 'cando']) {
    const start = Date.now()
    await page.evaluate(() => {
      window.__vizFrames = []
      let previous = performance.now()
      window.__vizTimer = setInterval(() => {
        const now = performance.now(); window.__vizFrames.push(now-previous); previous=now
      }, 50)
    })
    await page.locator(`.cando-display-mode[value="${mode}"]`).check()
    await expect(status).toContainText(({ deform: 'Predicted solution shape', flex: 'Flexibility (RMSF)', deviation: 'Deviation from design', cando: 'CanDo-style cylinders' })[mode], { timeout: 120000 })
    await expect(status).toContainText('Large-result view:')
    console.log(`${mode} compact result loaded`)
    const result = await page.evaluate(() => {
      const object = window.__nadocTest.scene.getObjectByName('cando-large-result')
      return { points: object?.children[0]?.isPoints === true, count: object?.userData.count,
        coords: [...object.children[0].geometry.attributes.position.array.slice(0,3)] }
    })
    if (mode !== 'cando') expect(result.count).toBe(424144)
    else expect(result.count).toBeGreaterThan(420000)
    expect(result.points).toBe(mode !== 'cando')
    const pixels = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
    expect(pixels.colorful).toBeGreaterThan(100)
    const loadingTiming = await page.evaluate(() => {
      const maxGap = Math.max(...window.__vizFrames)
      window.__vizFrames.length = 0
      return { maxGap }
    })
    // Camera interaction must repaint without rebuilding the result.
    await page.evaluate(() => window.__NADOC_DBG__.setCameraDist(window.__NADOC_DBG__.fitDist(1.4), [-1,1,1]))
    if (mode !== 'deform') {
      await page.locator('#flex-scale-cmap').click()
      await page.locator('#flex-scale-cmap-popup [data-cmap="viridis"]').click()
      await page.locator('#flex-scale-max').fill('12')
      await page.locator('#flex-scale-max').press('Enter')
      expect(await page.evaluate(() => window.__nadocTest.scene.getObjectByName('cando-large-result').children[0].material.uniforms.span.value)).toBeGreaterThan(0)
    }
    await page.waitForTimeout(1000)
    const timing = await page.evaluate(() => {
      clearInterval(window.__vizTimer)
      return { maxGap: Math.max(...window.__vizFrames), ticks: window.__vizFrames.length,
        gpu: { ...window.__NADOC_DBG__.renderer.info.render },
        visible: window.__nadocTest.scene.children.filter(o => o.visible).map(o => o.name) }
    })
    console.log(JSON.stringify({ mode, loadMs: Date.now()-start, loadingMaxGap: loadingTiming.maxGap, ...result, ...timing }))
    expect(timing.ticks).toBeGreaterThan(3)
    expect.soft(timing.maxGap).toBeLessThan(500)
    expect.soft(timing.gpu.triangles).toBeLessThan(10000)
  }
  await page.locator('#cando-metrics-toggle').click()
  for (const metric of ['rmsf', 'dev']) {
    await page.locator(`#cando-metrics-${metric}-display`).click()
    await expect(page.locator(`#cando-metrics-${metric}-status`)).not.toContainText('Loading', { timeout: 30000 })
    console.log('Graph', metric, await page.locator(`#cando-metrics-${metric}-status`).textContent(), errors)
    await expect(page.locator('#cando-metric-popup-canvas')).toBeVisible({ timeout: 30000 })
    await expect(page.locator(`#cando-metrics-${metric}-status`)).toContainText('base pairs')
    await page.locator('#cando-metric-popup-close').click()
  }
  // Deliberately finish an older request after a newer view selection, then Off.
  await page.route(`**/cando/jobs/${job}/visualization-bin?mode=deform`, async route => {
    const response = await route.fetch()
    await new Promise(resolve => setTimeout(resolve, 500))
    await route.fulfill({ response }).catch(() => {})
  })
  await page.locator('.cando-display-mode[value="deform"]').check()
  await page.locator('.cando-display-mode[value="flex"]').check()
  await expect(status).toContainText('Flexibility (RMSF)')
  await page.waitForTimeout(600)
  await expect(page.locator('.cando-display-mode[value="flex"]')).toBeChecked()
  await page.locator('.cando-display-mode[value="off"]').check()
  expect(await page.evaluate(() => !!window.__nadocTest.scene.getObjectByName('cando-large-result'))).toBe(false)
  await page.locator('.cando-display-mode[value="deform"]').check()
  await page.locator('.cando-display-mode[value="off"]').check()
  await page.waitForTimeout(600)
  expect(await page.evaluate(() => !!window.__nadocTest.scene.getObjectByName('cando-large-result'))).toBe(false)
  await expect(status).toBeEmpty()
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentAssembly))).toBe(initial)
  expect(requests.filter(url => /snapshot-geometry|thermal-trajectory|thermal-representative|\/display$|\/deviation$|\/cylinders$/.test(url))).toEqual([])
  expect(errors, errors.join('\n')).toEqual([])
  expect(readFileSync(fixture, 'utf8')).toBe(original)
})
