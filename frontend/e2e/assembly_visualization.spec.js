import { existsSync, readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Only __e2e__ copies can be saved; global teardown removes files and history.
// BigO source files are read-only. No downloads or artifacts outside test output.
test('BigO assembly visualization owns independent views, overlays and persisted world-space volumes', async ({ page }) => {
  test.setTimeout(360000)
  page.setDefaultTimeout(30000)
  await page.setViewportSize({ width: 1280, height: 720 })
  const errors = trackConsoleErrors(page)
  page.on('response', response => { if (response.status() >= 400) console.log('HTTP error', response.status(), response.url()) })
  const fixture = new URL('../../workspace/BigO-poly.nass', import.meta.url)
  test.skip(!existsSync(fixture), 'Local BigO scale fixture is not installed')
  const assembly = JSON.parse(readFileSync(fixture))
  assembly.id = '__e2e__assembly_visualization'; assembly.metadata.name = '__e2e__assembly_visualization'
  assembly.view_volumes = []
  await page.goto('/?doc=__e2e__assembly_visualization')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async assembly => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(JSON.stringify(assembly))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, assembly)
  await page.waitForFunction(() => window.__NADOC_VIEW_VOLUMES__.backboneTargets(1).length > 0)
  const initial = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentAssembly.instances))
  while (await page.locator('#right-panel .sidebar-close').count()) await page.locator('#right-panel .sidebar-close').first().click()
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.evaluate(() => window.__nadocTest.configureMultiView({ count: 2, representations: ['hull-prism', 'cylinders'] }))
  await expect(page.locator('.mv-viewport-panel[data-ready="true"]')).toHaveCount(2)
  const snapshots = () => page.evaluate(() => {
    const { views, overlays } = window.__nadocTest.comparisonScenesForTest()
    const summarize = list => list.filter(p => p.renderScene).map(p => {
      let meshes = 0; const names = [], materials = []
      p.renderScene.traverseVisible(o => { if (o.isMesh && (!o.isInstancedMesh || o.count > 0)) { meshes++; names.push(o.name); materials.push(o.material.uuid) } })
      return { meshes, names, materials, bounds: p.renderScene.visualizationBounds?.toArray?.() ?? p.renderScene.visualizationBounds?.min.toArray(), x: p.renderScene.position.x }
    })
    return { views: summarize(views), overlays: summarize(overlays) }
  })
  let data = await snapshots()
  expect(data.views.every(p => p.meshes > 0)).toBe(true)
  expect(data.views[0].names).not.toEqual(data.views[1].names)
  expect(data.views[0].materials.some(m => data.views[1].materials.includes(m))).toBe(false)
  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({ count: 2, representations: ['hull-prism', 'cylinders'], opacities: [1, .4], separation: .4 }))
  await expect(page.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(2)
  data = await snapshots()
  expect(data.overlays.every(p => p.meshes > 0)).toBe(true)
  expect(data.overlays[1].x - data.overlays[0].x).toBeGreaterThan(10)
  while (await page.locator('#right-panel .sidebar-close').count()) await page.locator('#right-panel .sidebar-close').first().click()
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.locator('.mo-count-btn[data-count="2"]').click()
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentAssembly.instances))).toBe(initial)
  await page.evaluate(() => document.getElementById('unhide-all-btn').click())
  await page.locator('#view-volume-add-box').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  // Move a small box onto one actual backbone point; repeated source helix IDs
  // must remain independently addressable after each instance transform.
  await page.evaluate(() => {
    const debug = window.__NADOC_VIEW_VOLUMES__
    debug.resizeSelected([.08, .08, .08]); debug.moveToBackbone()
  })
  await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing().counters.persisted), { timeout: 60000 }).toBeGreaterThanOrEqual(3)
  await expect(page.locator('#view-volume-busy')).toBeHidden({ timeout: 60000 })
  await page.locator('.view-volume-representation').selectOption('cylinders')
  await expect.poll(() => page.evaluate(() => {
    const layers = window.__NADOC_VIEW_VOLUMES__.layers()
    return layers[0]?.keys.size ?? 0
  })).toBeGreaterThan(0)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.children.some(o => o.name === 'assembly-visualization')), { timeout: 60000 }).toBe(true)
  await expect(page.locator('#view-volume-busy')).toBeHidden({ timeout: 60000 })
  const saved = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    return JSON.parse(await api.getAssemblyContent())
  })
  expect(saved.view_volumes).toHaveLength(1)
  expect(saved.view_volumes[0].representation).toBe('cylinders')
  await page.locator('.view-volume-enabled-toggle').click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.children.some(o => o.name === 'assembly-visualization'))).toBe(false)
  await page.locator('.view-volume-enabled-toggle').click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.children.some(o => o.name === 'assembly-visualization')), { timeout: 60000 }).toBe(true)
  await page.locator('.view-volume-delete').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.children.some(o => o.name === 'assembly-visualization'))).toBe(false)
  expect(errors, errors.join('\n')).toEqual([])
})

test('assembly comparison supports all part representations and heavy volume layers survive reload', async ({ page }) => {
  test.setTimeout(360000)
  page.setDefaultTimeout(30000)
  const errors = trackConsoleErrors(page)
  page.on('response', response => { if (response.status() >= 400) console.log('HTTP error', response.status(), response.url()) })
  const design = JSON.parse(readFileSync(new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)))
  design.id = '__e2e__assembly_viz_part'; design.metadata.name = '__e2e__assembly_viz_part'
  await page.goto('/?doc=__e2e__assembly_viz_representations')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js')
    await api.importDesign(JSON.stringify(design)); await api.getGeometry()
    await api.saveDesign('workspace/__e2e__assembly_viz_part.nadoc')
    await api.createAssembly('__e2e__assembly_viz_representations')
    for (let i = 0; i < 2; i++) await api.addInstance({ source: { type: 'file', path: '__e2e__assembly_viz_part.nadoc' }, representation: 'hull-prism', transform: { values: [1,0,0,25*i, 0,1,0,0, 0,0,1,0, 0,0,0,1] } })
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, design)
  for (const representation of ['hull-prism', 'cylinders', 'beads', 'full', 'vdw', 'ballstick', 'stick', 'surface', 'mrdna-coarse', 'mrdna-fine', 'oxdna']) {
    await page.evaluate(representation => window.__nadocTest.configureMultiView({ count: 2, representations: ['hull-prism', representation] }), representation)
    await expect(page.locator('.mv-viewport-panel[data-ready="true"]')).toHaveCount(2)
    expect(await page.evaluate(() => {
      let count = 0
      window.__nadocTest.comparisonScenesForTest().views[1].renderScene.traverseVisible(o => { if (o.isMesh && (!o.isInstancedMesh || o.count > 0)) count++ })
      return count
    }), representation).toBeGreaterThan(0)
  }
  await page.evaluate(() => window.__nadocTest.configureMultiView({ count: 1 }))
  while (await page.locator('#right-panel .sidebar-close').count()) await page.locator('#right-panel .sidebar-close').first().click()
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.evaluate(() => document.getElementById('unhide-all-btn').click())
  await page.locator('#view-volume-add-box').click()
  await page.evaluate(() => { const v = window.__NADOC_VIEW_VOLUMES__; v.resizeSelected([.2,.4,.3]); v.moveToBackbone() })
  for (const representation of ['stick', 'surface']) {
    const applied = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing().events.filter(e => e.type === 'assembly-applied').length)
    await page.locator('.view-volume-representation').selectOption(representation)
    await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.timing().events.filter(e => e.type === 'assembly-applied').length), { timeout: 60000 }).toBeGreaterThan(applied)
    await expect(page.locator('#view-volume-busy')).toBeHidden({ timeout: 60000 })
    await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[0].representation)).toBe(representation)
  }
  const saved = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    return api.getAssemblyContent()
  })
  expect(JSON.parse(saved).view_volumes[0].representation).toBe('surface')
  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({ count: 2, representations: ['hull-prism', 'cylinders'] }))
  expect(await page.evaluate(() => window.__nadocTest.comparisonScenesForTest().overlays.slice(0, 2).every(p => p.renderScene.visualizationLayers?.some(l => l.representation === 'surface')))).toBe(true)
  await page.evaluate(() => window.__nadocTest.configureMultiOverlay({ count: 0 }))
  await page.locator('.view-volume-delete').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(0)
  await page.evaluate(async content => { const api = await import('/src/api/client.js'); await api.importAssembly(content) }, saved)
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  await expect(page.locator('.view-volume-representation')).toHaveValue('surface')
  await expect(page.locator('#view-volume-busy')).toBeHidden({ timeout: 60000 })
  expect(errors, errors.join('\n')).toEqual([])
})
