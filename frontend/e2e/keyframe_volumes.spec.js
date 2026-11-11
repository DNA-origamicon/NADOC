import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Reads a legacy fixture; changes display metadata only in an isolated session.
// No saves/exports. Session cache is disabled; global teardown/reporter clean artifacts.
test('keyframe volume pickers drive insets and restore working visibility', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto('/?doc=__e2e__keyframe-volumes&debug=1')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async example => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(example)
    document.getElementById('welcome-screen').classList.add('hidden')
    document.getElementById('left-panel').classList.remove('locked-hidden')
    for (const button of document.querySelectorAll('#left-tab-strip button')) button.disabled = false
    for (const id of ['right-panel', 'right-tab-strip']) document.getElementById(id).classList.remove('locked-inactive')
    window.__leftSidebar.refresh()
    const store = window.__nadocTest.store
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    createSelectionController({ store }).replace([{ kind: 'strand', id: store.getState().currentDesign.strands[0].id }])
  }, path.resolve(process.cwd(), '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  await page.locator('#zoom-volume-add').click()
  await expect.poll(() => page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0]?.ready)).toBe(true)
  await page.getByRole('button', { name: 'Zoom in inset', exact: true }).click()
  await page.getByRole('button', { name: 'Zoom in inset', exact: true }).click()
  await expect.poll(() => page.evaluate(async () => {
    const response = await fetch('/api/design', { headers: { 'X-NADOC-Doc': '__e2e__keyframe-volumes' } })
    return (await response.json()).design.zoom_volumes?.[0]?.zoom_step
  })).toBe(2)
  await page.locator('#view-volume-add-box').click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.view_volumes?.length)).toBe(1)
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign.animations?.length)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const d = window.__nadocTest.store.getState().currentDesign
    await api.createKeyframe(d.animations[0].id, { transition_duration_s: 0, hold_duration_s: 0.1 })
  })
  const row = page.locator('.anim-keyframe').first()
  for (const field of ['view_volume_ids', 'zoom_volume_ids']) {
    const picker = row.locator(`[data-field="${field}"]`)
    await picker.locator('summary').click()
    await expect(picker.locator('.anim-annotation-list')).toHaveCSS('max-height', '160px')
    await picker.getByRole('button', { name: 'None', exact: true }).click()
    await expect.poll(() => page.evaluate(field => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes[0][field], field)).toEqual([])
  }
  await row.locator('.anim-keyframe-title').click()
  await expect(page.locator('.zoom-volume-inset')).toBeHidden()
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers())).toEqual([])
  await page.locator('#canvas').click({ position: { x: 10, y: 10 } })
  await expect(page.locator('.zoom-volume-inset')).toBeVisible()
  for (const field of ['view_volume_ids', 'zoom_volume_ids']) await row.locator(`[data-field="${field}"]`).getByRole('button', { name: 'All', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.animations[0].keyframes[0].zoom_volume_ids?.length)).toBe(1)
  await row.locator('.anim-keyframe-title').click()
  await expect(page.locator('.zoom-volume-inset')).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.layers().length)).toBeGreaterThan(0)
  expect(await page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0].zoom)).toBe(1.25 ** 2)
  await page.locator('#canvas').click({ position: { x: 10, y: 10 } })
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.createKeyframe(window.__nadocTest.store.getState().currentDesign.animations[0].id, { transition_duration_s: 0, hold_duration_s: 1 })
  })
  await page.locator('#anim-start-presentation-btn').click()
  await expect(page.locator('#canvas-area')).toHaveClass(/animation-presentation-active/)
  await expect(page.locator('.zoom-volume-inset')).toBeVisible()
  expect(await page.evaluate(() => {
    const inset = document.querySelector('.zoom-volume-inset'), r = inset.getBoundingClientRect()
    return inset.contains(document.elementFromPoint(r.x + 20, r.y + 50))
  })).toBe(true)
  expect(await page.evaluate(() => window.__NADOC_ZOOM_VOLUME__.debug().entries[0].zoom)).toBe(1.25 ** 2)
  await page.keyboard.press('Escape')
  await expect(page.locator('#canvas-area')).not.toHaveClass(/animation-presentation-active/)
  const exported = await page.evaluate(async () => {
    const { settleZoomVolumes, drawZoomVolumes } = await import('/src/scene/zoom_volume_export.js')
    const { scene, camera } = window.__NADOC_DBG__
    await settleZoomVolumes(scene)
    const canvas = document.createElement('canvas'); canvas.width = 1280; canvas.height = 720
    const ctx = canvas.getContext('2d'); drawZoomVolumes(scene, ctx, 1280, 720, camera)
    const alpha = ctx.getImageData(0, 0, 1280, 720).data.filter((_, i) => i % 4 === 3)
    return { pixels: alpha.filter(a => a > 0).length, zoom: window.__NADOC_ZOOM_VOLUME__.debug().entries[0].zoom }
  })
  expect(exported.pixels).toBeGreaterThan(10000)
  expect(exported.zoom).toBe(1.25 ** 2)
  expect(errors, errors.join('\n')).toEqual([])
})
