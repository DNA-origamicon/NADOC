import { existsSync, readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Persistence inventory: only the __e2e__ assembly (including inline source data)
// may autosave to workspace. global-teardown removes it after success/failure.
// No original fixture is opened or written. Screenshots remain in test output.
test('assembly annotations: individual copy and overhang gestures, transforms, controls, reload and export', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const errors = trackConsoleErrors(page)
  const design = JSON.parse(readFileSync(new URL('../../Examples/hingeV4.nadoc', import.meta.url)))
  design.id = '__e2e__annotation_source'; design.metadata.name = '__e2e__annotation_source'
  design.annotations = []
  const assembly = { id: '__e2e__annotations', metadata: { name: '__e2e__annotations' }, instances: [0, 1].map(i => ({
    id: `copy-${i}`, name: `Copy ${i + 1}`, source: { type: 'inline', design }, representation: 'hull-prism',
    transform: { values: [1,0,0,130*i, 0,1,0,0, 0,0,1,0, 0,0,0,1] },
  })) }
  await page.goto('/?doc=__e2e__annotations')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async assembly => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(JSON.stringify(assembly))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, assembly)
  await page.waitForFunction(() => window.__NADOC_DBG__?.assemblyRenderer.getInstanceCenters().length === 2)
  await page.keyboard.press('f')
  while (await page.locator('#right-panel .sidebar-close').count()) await page.locator('#right-panel .sidebar-close').first().click()
  await page.locator('.right-tab-btn[data-tab="annotations"]').click()
  const column = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await expect(column.locator('.anno-add')).toBeVisible()
  // Scan the real picker to find an unoccluded point on the second copy.
  const hit = await page.evaluate(() => {
    const t = window.__nadocTest, rect = document.getElementById('canvas').getBoundingClientRect()
    for (let y = rect.top + 70; y < rect.bottom - 50; y += 12)
      for (let x = rect.left + 50; x < rect.right - 50; x += 12)
        if (t.pickAssemblyInstanceAt(x, y)?.id === 'copy-1') return { x, y }
  })
  expect(hit).toBeTruthy()
  await page.mouse.click(hit.x, hit.y)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getActiveInstanceId())).toBe('copy-1')
  await column.locator('.anno-add').click()
  const card = column.locator('.anno-card').first()
  await card.locator('[data-field="useSelection"]').click()
  await expect(card.locator('.anno-target')).toContainText('Copy 2')
  await card.locator('[data-field="text"]').fill('Only this copy')
  await expect(page.locator('.nadoc-anno:not([hidden])')).toHaveCount(1)
  const highlights = () => page.evaluate(() => window.__nadocTest.scene.getObjectByName('Annotation highlights').children.filter(o => o.isPoints).map(o => ({ id: o.name, count: o.geometry.attributes.position.count, first: Array.from(o.geometry.attributes.position.array.slice(0, 3)) })))
  await expect.poll(async () => (await highlights()).length).toBe(1)
  const before = (await highlights())[0]
  expect(before.count).toBeGreaterThan(100)
  // Changing only copy 2's transform must move its annotation highlight by 25 nm.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.patchInstance('copy-1', { transform: { values: [1,0,0,155, 0,1,0,0, 0,0,1,0, 0,0,0,1] } })
  })
  await expect.poll(async () => (await highlights())[0]?.first[0] - before.first[0]).toBeCloseTo(25, 3)
  // Real overhang click on copy 1, including unnamed overhangs.
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('o')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().toolFilters.overhangLocations)).toBe(true)
  const anchor = await page.evaluate(() => {
    const { assemblyRenderer: r, camera } = window.__NADOC_DBG__
    const rect = document.getElementById('canvas').getBoundingClientRect()
    return r.getOverhangAnchors().filter(a => a.instanceId === 'copy-0').map(a => {
      const p = a.world.clone().project(camera)
      return { x: rect.left + (p.x / 2 + .5) * rect.width, y: rect.top + (.5 - p.y / 2) * rect.height, id: a.overhangId }
    }).find(p => p.x > rect.left + 50 && p.x < rect.right - 50 && p.y > rect.top + 50 && p.y < rect.bottom - 50)
  })
  expect(anchor).toBeTruthy()
  await page.mouse.click(anchor.x, anchor.y)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().assemblyOverhangSelection.length)).toBe(1)
  await column.locator('.anno-add').click()
  const ohCard = column.locator('.anno-card').nth(1)
  await ohCard.locator('[data-field="useSelection"]').click()
  await expect(ohCard.locator('.anno-target')).toContainText('Overhang · Copy 1')
  await ohCard.locator('[data-field="text"]').fill('This overhang')
  await ohCard.locator('[data-field="calloutType"]').selectOption('rounded')
  await ohCard.locator('[data-field="color"]').fill('#ff4d4d')
  await ohCard.locator('[data-field="manual"]').check()
  await expect(page.locator('.nadoc-anno:not([hidden])')).toHaveCount(2)
  await expect.poll(async () => (await highlights()).length).toBe(2)
  expect((await highlights())[1].count).toBeLessThan(before.count)
  await column.locator('.anno-enable input').uncheck()
  await expect(page.locator('.nadoc-anno-layer')).toBeHidden()
  await column.locator('.anno-enable input').check()
  await expect(page.locator('.nadoc-anno-layer')).toBeVisible()
  // Wait for debounced metadata acknowledgement, then inspect the actual .nass payload.
  await expect.poll(() => page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const saved = JSON.parse(await api.getAssemblyContent())
    return saved.annotations_enabled && saved.annotations?.[1]?.manual ? saved.annotations.length : 0
  })).toBe(2)
  const saved = await page.evaluate(async () => JSON.parse(await (await import('/src/api/client.js')).getAssemblyContent()))
  expect(saved.annotations[0].refs).toEqual([{ kind: 'assembly-part', instanceId: 'copy-1' }])
  expect(saved.annotations[1].refs[0]).toMatchObject({ kind: 'assembly-overhang', instanceId: 'copy-0' })
  expect(await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    return Promise.all(['copy-0', 'copy-1'].map(async id => (await api.getInstanceDesign(id)).design.annotations))
  })).toEqual([[], []])
  const shared = await page.evaluate(async () => {
    const { captureSceneAnnotations } = await import('/src/scene/annotation_overlay.js')
    return captureSceneAnnotations(window.__nadocTest.scene)
  })
  expect(shared).toHaveLength(2)
  expect(shared.every(a => a.targets.length > 0)).toBe(true)
  await page.evaluate(async saved => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(JSON.stringify({ ...saved, id: '__e2e__annotations_reloaded' }))
  }, saved)
  await expect(column.locator('.anno-card')).toHaveCount(2)
  await expect(column.locator('.anno-card').nth(1).locator('[data-field="text"]')).toHaveValue('This overhang')
  await expect(page.locator('.nadoc-anno:not([hidden])')).toHaveCount(2)
  await page.screenshot({ path: testInfo.outputPath('assembly-annotations.png') })
  await column.locator('.anno-card').nth(1).locator('[data-field="delete"]').click()
  await expect(column.locator('.anno-card')).toHaveCount(1)
  expect(errors, errors.join('\n')).toEqual([])
})


test('BigO assembly annotations remain scoped to one of thirty copies', async ({ page }) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(30000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const fixture = new URL('../../workspace/BigO-poly.nass', import.meta.url)
  test.skip(!existsSync(fixture), 'Local BigO fixture is not installed')
  const original = readFileSync(fixture, 'utf8')
  const sourcePath = new URL('../../workspace/BigO.nadoc', import.meta.url)
  const sourceBefore = existsSync(sourcePath) ? readFileSync(sourcePath, 'utf8') : null
  const assembly = JSON.parse(original)
  assembly.id = '__e2e__bigo_annotations'; assembly.metadata.name = '__e2e__bigo_annotations'
  assembly.annotations = []
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=__e2e__bigo_annotations')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async assembly => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(JSON.stringify(assembly))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await window.__nadocTest.enterAssemblyMode()
  }, assembly)
  console.log('BigO entered assembly mode')
  await page.waitForFunction(() => {
    const state = window.__nadocTest.store.getState()
    const instance = state.currentAssembly?.instances?.[17]
    return instance && window.__NADOC_DBG__?.assemblyRenderer.getInstanceBackboneEntries(instance.id).nucleotides?.length > 0
  }, null, { timeout: 60000 })
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentAssembly.instances.length)).toBe(30)
  console.log('BigO renderer ready')
  await page.locator('.right-tab-btn[data-tab="annotations"]').click()
  await page.evaluate(() => {
    const store = window.__nadocTest.store
    store.setState({ activeInstanceId: store.getState().currentAssembly.instances[17].id })
  })
  const column = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await column.locator('.anno-add').click()
  await column.locator('[data-field="useSelection"]').click()
  await column.locator('[data-field="text"]').fill('Only copy 18')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.getObjectByName('Annotation highlights').children.filter(o => o.isPoints).length)).toBe(1)
  await expect.poll(() => page.evaluate(async () => {
    const saved = JSON.parse(await (await import('/src/api/client.js')).getAssemblyContent())
    return saved.annotations?.[0]?.refs?.length
  })).toBe(1)
  expect(readFileSync(fixture, 'utf8')).toBe(original)
  if (sourceBefore !== null) expect(readFileSync(sourcePath, 'utf8')).toBe(sourceBefore)
  expect(errors, errors.join('\n')).toEqual([])
})
