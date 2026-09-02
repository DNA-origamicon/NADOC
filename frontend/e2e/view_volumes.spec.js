import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('persisted heavy view-volume representation applies when geometry finishes loading', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = trackConsoleErrors(page)
  let releaseAtoms
  const atomGate = new Promise(resolve => { releaseAtoms = resolve })
  let atomRequests = 0
  await page.route('**/api/design/atomistic*', async route => {
    atomRequests += 1
    await atomGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      atoms: [], bonds: [], element_meta: {}, stats: {},
    }) })
  })
  await page.goto('/?doc=e2e-view-volume-reload')
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.loadDesign('/home/joshua/NADOC/workspace/smallO.nadoc')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive', 'hidden')
  })
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  await expect.poll(() => atomRequests).toBeGreaterThan(0)
  await expect(page.locator('#view-volume-busy')).toBeVisible()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers()[0]?.keys.size ?? 0)).toBeGreaterThan(0)
  releaseAtoms()
  await expect(page.locator('#view-volume-busy')).toBeHidden()
  expect(errors, errors.join('\n')).toEqual([])
})

test('view volumes add, overlap, edit, persist, and expose validation layers', async ({ page }) => {
  test.setTimeout(60_000)
  const errors = trackConsoleErrors(page)
  const doc = `view-volumes-${Date.now()}`
  await loadScaffoldedPart(page, { doc, name: 'view-volumes' })
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await expect(page.locator('#view-volumes-section')).toBeVisible()

  await page.locator('#view-volume-add-box').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  await page.locator('.view-volume-enabled-toggle').click()
  await expect(page.locator('.view-volume-enabled-toggle')).toHaveAttribute('aria-pressed', 'false')
  await expect(page.locator('#view-volume-enable-all')).toHaveAttribute('aria-pressed', 'false')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers().length)).toBe(0)
  await page.locator('#view-volume-enable-all').click()
  await expect(page.locator('.view-volume-enabled-toggle')).toHaveAttribute('aria-pressed', 'true')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers().length)).toBe(1)
  await page.locator('.view-volume-outline-toggle').click()
  await expect(page.locator('.view-volume-outline-toggle')).toHaveAttribute('aria-pressed', 'false')
  await expect(page.locator('#view-volume-toggle-all')).toHaveAttribute('aria-pressed', 'false')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.gizmoVisible())).toBe(false)
  await page.locator('#view-volume-toggle-all').click()
  await expect(page.locator('.view-volume-outline-toggle')).toHaveAttribute('aria-pressed', 'true')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.gizmoVisible())).toBe(true)
  await page.locator('#view-volume-heading').click()
  await expect(page.locator('#view-volume-body')).toBeHidden()
  await expect(page.locator('#view-volume-heading')).toHaveAttribute('aria-expanded', 'false')
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('nadoc.leftSidebar.sections.v1'))
    ?.visualization?.['view-volumes-section'])).toBe(true)
  await page.locator('#view-volume-heading').click()
  await expect(page.locator('#view-volume-body')).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:view-volume-stage', {
    detail: { stage: 'atom-scheduled', viewVolume: true },
  })))
  await expect(page.locator('#view-volume-busy')).toBeVisible()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.representationBusy())).toBe(true)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:view-volume-stage', {
    detail: { stage: 'atom-applied', viewVolume: true },
  })))
  await expect(page.locator('#view-volume-busy')).toBeHidden()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.gizmoVisible())).toBe(true)
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.mode())).toBe('scale')
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.mode())).toBe('rotate')
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.mode())).toBe('translate')
  await page.keyboard.press('Escape')
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).toBeNull()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.gizmoVisible())).toBe(false)
  const outline = await page.evaluate(() => {
    const debug = window.__NADOC_VIEW_VOLUMES__, id = debug.volumes()[0].id
    window.__volumeLeakedPointerDowns = 0
    document.querySelector('#canvas').addEventListener('pointerdown', () => { window.__volumeLeakedPointerDowns += 1 })
    return { id, ...debug.outlinePoint(id) }
  })
  await page.locator('.view-volume-outline-toggle').click()
  await page.mouse.move(outline.x, outline.y)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.hovered())).toBeNull()
  await page.locator('.view-volume-outline-toggle').click()
  await page.mouse.move(outline.x, outline.y)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.hovered())).toBe(outline.id)
  await page.mouse.click(outline.x, outline.y)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).toBe(outline.id)
  expect(await page.evaluate(() => window.__volumeLeakedPointerDowns)).toBe(0)
  await page.keyboard.press('Escape')
  await page.locator('.view-volume-row').click()
  await page.evaluate(() => {
    const debug = window.__NADOC_VIEW_VOLUMES__
    debug.setMode('rotate'); debug.begin(); debug.rotatePreview([0, 0, 1], Math.PI / 6); debug.commit()
  })
  await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[0].rotation[2])).not.toBe(0)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).not.toBeNull()
  await page.locator('.view-volume-row').click()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).toBeNull()
  await page.locator('.view-volume-row').click()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).not.toBeNull()
  const selectedBeforeOrbit = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())
  await page.mouse.move(60, 100)
  await page.mouse.down()
  await page.mouse.move(110, 140, { steps: 4 })
  await page.mouse.up()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).toBe(selectedBeforeOrbit)
  await page.mouse.click(60, 100)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).toBeNull()
  await page.locator('.view-volume-row').click()
  const boxBefore = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[0])
  await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.resizeSelected([1.1, 0.9, 1.2]))
  const boxAfter = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[0])
  for (let axis = 0; axis < 3; axis += 1) {
    expect(boxAfter.max_corner[axis] - boxAfter.min_corner[axis]).toBeCloseTo(
      (boxBefore.max_corner[axis] - boxBefore.min_corner[axis]) * [1.1, 0.9, 1.2][axis],
    )
  }
  await page.locator('.view-volume-name').fill('Surface focus')
  await page.locator('.view-volume-name').press('Enter')
  await page.locator('.view-volume-representation').selectOption('surface')
  await page.locator('.view-volume-opacity').fill('0.4')
  await page.locator('.view-volume-opacity').dispatchEvent('change')

  await page.locator('#view-volume-add-hexagonal').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(2)
  const volumeIds = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes().map(volume => volume.id))
  await page.locator('.view-volume-enabled-toggle').nth(0).click()
  await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers().map(layer => layer.volume.id))).toEqual([volumeIds[1]])
  await page.locator('.view-volume-enabled-toggle').nth(0).click()
  await page.locator('#view-volume-enable-all').click()
  await expect(page.locator('.view-volume-enabled-toggle[aria-pressed="false"]')).toHaveCount(2)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers().length)).toBe(0)
  await page.locator('#view-volume-enable-all').click()
  await expect(page.locator('.view-volume-enabled-toggle[aria-pressed="true"]')).toHaveCount(2)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers().length)).toBe(2)
  await page.locator('#view-volume-toggle-all').click()
  await expect(page.locator('.view-volume-outline-toggle[aria-pressed="false"]')).toHaveCount(2)
  await page.locator('#view-volume-toggle-all').click()
  await expect(page.locator('.view-volume-outline-toggle[aria-pressed="true"]')).toHaveCount(2)
  await page.locator('.view-volume-row').nth(1).locator('.view-volume-representation').selectOption('stick')
  await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.setMode('scale'))
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.scaleGizmoAxes())).toEqual(['X', 'Z'])
  const hexBefore = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[1])
  await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.resizeSelected([1.4, 1, 1]))
  const hexAfter = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[1])
  expect(hexAfter.max_corner[0] - hexAfter.min_corner[0]).toBeCloseTo((hexBefore.max_corner[0] - hexBefore.min_corner[0]) * 1.4)
  expect(hexAfter.max_corner[1] - hexAfter.min_corner[1]).toBeCloseTo((hexBefore.max_corner[1] - hexBefore.min_corner[1]) * 1.4)
  expect(hexAfter.max_corner[2] - hexAfter.min_corner[2]).toBeCloseTo(hexBefore.max_corner[2] - hexBefore.min_corner[2])
  await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.resizeSelected([1, 1, 1.5]))
  const hexLengthened = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[1])
  expect(hexLengthened.max_corner[0] - hexLengthened.min_corner[0]).toBeCloseTo(hexAfter.max_corner[0] - hexAfter.min_corner[0])
  expect(hexLengthened.max_corner[1] - hexLengthened.min_corner[1]).toBeCloseTo(hexAfter.max_corner[1] - hexAfter.min_corner[1])
  expect(hexLengthened.max_corner[2] - hexLengthened.min_corner[2]).toBeCloseTo((hexAfter.max_corner[2] - hexAfter.min_corner[2]) * 1.5)

  // A selected hex volume exposes two length ends and one radius handle.
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.handles().length)).toBe(3)

  await expect.poll(async () => page.evaluate(() => {
    const layers = window.__NADOC_VIEW_VOLUMES__.layers()
    return layers.length === 2 && layers[0].keys.size > 0 && [...layers[0].keys].some(key => layers[1].keys.has(key))
  })).toBe(true)
  await expect.poll(async () => {
    const response = await page.request.get('/api/design', { headers: { 'X-NADOC-Doc': doc } })
    return (await response.json()).design?.view_volumes?.length
  }).toBe(2)

  const persisted = await page.request.get('/api/design', { headers: { 'X-NADOC-Doc': doc } })
  const saved = (await persisted.json()).design.view_volumes
  expect(saved).toHaveLength(2)
  expect(saved[0]).toMatchObject({ name: 'Surface focus', representation: 'surface', opacity: 0.4 })
  await page.locator('.view-volume-delete').nth(1).click()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  await expect.poll(async () => {
    const response = await page.request.get('/api/design', { headers: { 'X-NADOC-Doc': doc } })
    return (await response.json()).design?.view_volumes?.length
  }).toBe(1)
  expect(errors, errors.join('\n')).toEqual([])
})

test('latest persisted volume survives a stale rebuild response during move commit', async ({ page }) => {
  test.setTimeout(60_000)
  const doc = `view-volume-rebuild-race-${Date.now()}`
  await loadScaffoldedPart(page, { doc, name: 'view-volume-rebuild-race' })
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.locator('#view-volume-add-box').click()
  await expect.poll(() => page.evaluate(() =>
    window.__NADOC_VIEW_VOLUMES__.timing().counters.persisted)).toBeGreaterThanOrEqual(1)

  let releaseSave
  let markRequestSeen
  const saveGate = new Promise(resolve => { releaseSave = resolve })
  const requestSeen = new Promise(resolve => { markRequestSeen = resolve })
  await page.route('**/api/design/view-volumes', async route => {
    markRequestSeen()
    await saveGate
    await route.continue()
  })

  const before = await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[0].min_corner[0])
  await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.moveSelected([3, 0, 0]))
  await requestSeen

  // Model the stale full-design response that used to land during a rebuild.
  await page.evaluate(() => {
    const store = window.__nadocTest.store
    store.setState({ currentDesign: { ...store.getState().currentDesign, view_volumes: [] } })
  })
  await expect(page.locator('.view-volume-row')).toHaveCount(0)

  releaseSave()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
  await expect.poll(() => page.evaluate(() =>
    window.__NADOC_VIEW_VOLUMES__.volumes()[0].min_corner[0])).toBeCloseTo(before + 3)
  await page.unroute('**/api/design/view-volumes')

  await expect.poll(async () => {
    const response = await page.request.get('/api/design', { headers: { 'X-NADOC-Doc': doc } })
    return (await response.json()).design?.view_volumes?.[0]?.min_corner?.[0]
  }).toBeCloseTo(before + 3)
})
