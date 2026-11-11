import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Only the harness's recorded __e2e__ part/project is persisted. Global teardown
// removes both; session caching is disabled. No extra captures or exported files.
test('independent zoom entries share view volume controls and release deleted insets', async ({ page }) => {
  test.setTimeout(120000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await loadScaffoldedPart(page, { doc: '__e2e__zoom-entries', name: 'zoom-entries', extraQuery: '&debug=1' })
  await page.evaluate(async () => {
    const store = window.__nadocTest.store
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'strand', id: store.getState().currentDesign.strands[0].id }])
    document.querySelector('.right-tab-btn[data-tab="visualization"]').click()
  })
  await page.locator('#zoom-volume-add').click()
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0]?.ready)).toBe(true)
  await page.locator('#zoom-volume-add').click()
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[1]?.ready)).toBe(true)
  const rows = page.locator('.zoom-volume-row'), insets = page.locator('.zoom-volume-inset')
  await expect(rows).toHaveCount(2); await expect(insets.nth(0)).toBeVisible(); await expect(insets.nth(1)).toBeVisible()
  const painted = await insets.locator('canvas[aria-label]').evaluateAll(canvases => canvases.map(canvas => {
    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    for (let i = 4; i < pixels.length; i += 4) if (pixels[i] !== pixels[0] || pixels[i + 1] !== pixels[1] || pixels[i + 2] !== pixels[2]) return true
    return false
  }))
  expect(painted).toEqual([true, true])
  const zoomGroups = page.locator('.zoom-volume-zoom-controls')
  const plus = zoomGroups.nth(0).getByRole('button', { name: 'Zoom in inset', exact: true })
  const minus = zoomGroups.nth(0).getByRole('button', { name: 'Zoom out inset', exact: true })
  const beforeZoom = await page.evaluate(() => ({ camera: window.__NADOC_DBG__.camera.toJSON(), bounds: window.__NADOC_ZOOM_VOLUME__.debug().entries.map(e => e.bounds) }))
  const originalImage = await insets.nth(0).locator('canvas[aria-label]').evaluate(canvas => canvas.toDataURL())
  await plus.click()
  await zoomGroups.nth(1).getByRole('button', { name: 'Zoom out inset', exact: true }).click()
  expect(await page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries.map(e => e.zoom))).toEqual([1.25, .8])
  expect(await insets.nth(0).locator('canvas[aria-label]').evaluate(canvas => canvas.toDataURL())).not.toBe(originalImage)
  await plus.evaluate(button => { for (let i = 0; i < 7; i++) button.click() })
  await expect(plus).toBeDisabled()
  expect(await page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0].zoom)).toBe(1.25 ** 8)
  await minus.evaluate(button => { for (let i = 0; i < 16; i++) button.click() })
  await expect(minus).toBeDisabled()
  expect(await page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0].zoom)).toBe(1.25 ** -8)
  await plus.evaluate(button => { for (let i = 0; i < 9; i++) button.click() })
  expect(await page.evaluate(() => ({ camera: window.__NADOC_DBG__.camera.toJSON(), bounds: window.__NADOC_ZOOM_VOLUME__.debug().entries.map(e => e.bounds) }))).toEqual(beforeZoom)
  const first = rows.nth(0), second = rows.nth(1)
  await first.locator('.zoom-volume-options summary').click()
  for (const corner of ['tl', 'bl', 'br', 'tr']) {
    await first.locator('[data-control="position"]').selectOption(corner)
    await expect.poll(async () => {
      const inset = await insets.nth(0).boundingBox(), controls = await zoomGroups.nth(0).boundingBox()
      return controls.x + controls.width <= inset.x || controls.x >= inset.x + inset.width
    }).toBe(true)
  }
  await first.locator('.zoom-volume-options summary').click()
  await second.locator('.zoom-volume-options summary').click()
  await second.locator('[data-control="size"]').fill('200')
  await second.locator('[data-control="size"]').dispatchEvent('input')
  await expect.poll(async () => Math.round((await insets.nth(1).boundingBox()).width)).toBe(200)
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries.every(e => e.triangles > 0))).toBe(true)
  await second.locator('.zoom-volume-options summary').click()
  await first.locator('[data-control="representation"]').selectOption('beads')
  await first.locator('[data-control="coloring"]').selectOption('base')
  await expect(second.locator('[data-control="coloring"]')).toHaveValue('strand')
  expect(await page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries.map(e => e.zoom))).toEqual([1.25, .8])
  await first.locator('[data-control="name"]').fill('Detail A')
  await first.locator('[data-control="name"]').press('Tab')
  await expect(insets.nth(0)).toContainText('Detail A')
  await first.locator('[data-control="enabled"]').click()
  await expect(insets.nth(0)).toBeHidden(); await expect(insets.nth(1)).toBeVisible()
  await expect(zoomGroups.nth(0)).toBeHidden(); await expect(zoomGroups.nth(1)).toBeVisible()
  await page.locator('#zoom-volume-enable-all').click()
  await expect(insets.nth(0)).toBeVisible()
  await page.evaluate(async () => {
    const store = window.__nadocTest.store
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'domain', strandId: store.getState().currentDesign.strands[0].id, domainIndex: 0 }])
  })
  await second.locator('[data-control="set"]').click()
  const kinds = await page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries.map(e => e.targets[0].refs[0].kind))
  expect(kinds).toEqual(['strand', 'domain'])
  const styling = await page.evaluate(() => ({
    eye: document.querySelector('.zoom-volume-row [data-control="box"]').innerHTML,
    viewEye: document.querySelector('#view-volume-toggle-all').innerHTML,
    scroll: getComputedStyle(document.querySelector('#zoom-volume-list')).overflowY,
    overflows: document.querySelector('#zoom-volume-list').scrollHeight > document.querySelector('#zoom-volume-list').clientHeight,
  }))
  expect(styling.eye).toBe(styling.viewEye); expect(styling.scroll).toBe('auto'); expect(styling.overflows).toBe(true)
  await first.locator('[data-control="delete"]').click()
  await expect(rows).toHaveCount(1); await expect(insets).toHaveCount(1)
  await expect(insets).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0]?.ready)).toBe(true)
  await rows.locator('[data-control="delete"]').click()
  await expect(insets).toHaveCount(0)
  await expect(zoomGroups).toHaveCount(0)
  expect(errors).toEqual([])
})
