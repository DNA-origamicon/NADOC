import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('view volumes add, overlap, edit, persist, and expose validation layers', async ({ page }) => {
  test.setTimeout(60_000)
  const errors = trackConsoleErrors(page)
  const doc = `view-volumes-${Date.now()}`
  await loadScaffoldedPart(page, { doc, name: 'view-volumes' })
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await expect(page.locator('#view-volumes-section')).toBeVisible()

  await page.locator('#view-volume-add').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(1)
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
  await page.mouse.click(60, 100)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.selected())).toBeNull()
  await page.locator('.view-volume-row').click()
  await page.locator('.view-volume-name').fill('Surface focus')
  await page.locator('.view-volume-name').press('Enter')
  await page.locator('.view-volume-representation').selectOption('surface')
  await page.locator('.view-volume-opacity').fill('0.4')
  await page.locator('.view-volume-opacity').dispatchEvent('change')

  await page.locator('#view-volume-add').click()
  await expect(page.locator('.view-volume-row')).toHaveCount(2)
  await page.locator('.view-volume-row').nth(1).locator('.view-volume-representation').selectOption('stick')

  // Selecting a row exposes all eight independently raycastable corner handles.
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.handles().length)).toBe(8)

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
  expect(errors, errors.join('\n')).toEqual([])
})

test('latest persisted volume survives a stale rebuild response during move commit', async ({ page }) => {
  test.setTimeout(60_000)
  const doc = `view-volume-rebuild-race-${Date.now()}`
  await loadScaffoldedPart(page, { doc, name: 'view-volume-rebuild-race' })
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.locator('#view-volume-add').click()
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
