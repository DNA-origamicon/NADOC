import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Existing molecular fixture is read only. Changes are annotation display metadata
// in the isolated session; no structure files are written. Global teardown removes
// isolated bridge credentials/test artifacts; the reporter removes screenshots/traces.
test('annotation boxes resize, change aspect ratio and rotate without changing font size', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto('/?doc=__e2e__annotation-box')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async example => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(example)
    document.getElementById('welcome-screen').classList.add('hidden')
    for (const id of ['right-panel', 'right-tab-strip']) document.getElementById(id).classList.remove('locked-inactive')
  }, path.resolve(process.cwd(), '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const panel = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await panel.locator('.anno-add').click()
  await panel.locator('.anno-text').fill('A caption with wrapping text for a resizable slide box.')
  const edit = async (label, value) => { const input = panel.getByLabel(label, { exact: true }); await input.fill(value); await input.press('Tab') }
  await edit('Font size', '20')
  await edit('Box width (px)', '300')
  await edit('Box height (px)', '120')
  await edit('Angle (°)', '30')
  await panel.locator('[data-field="manual"]').check()
  const squareHandles = page.locator('.nadoc-anno__handle:not(.nadoc-anno__handle--rotate)')
  const verifySquares = async () => {
    await expect(squareHandles.first()).toBeVisible()
    const measurements = await squareHandles.evaluateAll(nodes => nodes.map(node => {
      const bounds = node.getBoundingClientRect(), css = getComputedStyle(node)
      return { handle: node.dataset.handle, width: node.offsetWidth, height: node.offsetHeight,
        screenWidth: bounds.width, screenHeight: bounds.height, minHeight: css.minHeight }
    }))
    console.log('Resize handle measurements:', JSON.stringify(measurements))
    expect(measurements).toHaveLength(8)
    for (const handle of measurements) {
      expect(handle.width, handle.handle).toBe(16)
      expect(handle.height, handle.handle).toBe(16)
      expect(handle.screenWidth, handle.handle).toBeCloseTo(handle.screenHeight, 3)
    }
  }
  await verifySquares()
  const entry = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.annotations[0])
  const box = page.locator('.nadoc-anno__box')
  await expect(box).toHaveCSS('font-size', '20px')
  await expect.poll(async () => (await entry()).rotation_deg).toBe(30)
  const drag = async (handle, dx, dy, shift = false) => {
    const bounds = await page.locator(`[data-handle="${handle}"]`).boundingBox()
    const x = bounds.x + bounds.width / 2, y = bounds.y + bounds.height / 2
    await page.mouse.move(x, y)
    if (shift) await page.keyboard.down('Shift')
    await page.mouse.down(); await page.mouse.move(x + dx, y + dy, { steps: 8 }); await page.mouse.up()
    if (shift) await page.keyboard.up('Shift')
  }
  await drag('e', 60 * Math.cos(Math.PI / 6), 30)
  await expect.poll(async () => (await entry()).box_size[0]).toBeCloseTo(360, 0)
  expect((await entry()).box_size[1]).toBeCloseTo(120)
  expect((await entry()).size).toBeCloseTo(20 / 13)
  await expect(box).toHaveCSS('font-size', '20px')
  // Rotate the handle 90 degrees around the displayed box center.
  const frame = await box.boundingBox(), handle = await page.locator('[data-handle="rotate-ne"]').boundingBox()
  const cx = frame.x + frame.width / 2, cy = frame.y + frame.height / 2
  const x = handle.x + handle.width / 2, y = handle.y + handle.height / 2
  await drag('rotate-ne', cx - (y - cy) - x, cy + (x - cx) - y, true)
  await expect.poll(async () => (await entry()).rotation_deg).toBe(120)
  await verifySquares()
  const before = await entry()
  await drag('se', -35, 25, true)
  await expect.poll(async () => (await entry()).box_size[0]).not.toBe(before.box_size[0])
  expect((await entry()).box_size[0] / (await entry()).box_size[1]).toBeCloseTo(3, 1)
  expect((await entry()).size).toBeCloseTo(20 / 13)
  // The server round trip keeps dimensions and angle; no molecular file is saved.
  await expect.poll(() => page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    return (await api.getDesign({ metadataOnly: true })).design.annotations[0].rotation_deg
  })).toBe(120)
  await panel.getByRole('button', { name: 'Auto-size box', exact: true }).click()
  await expect.poll(async () => (await entry()).box_size).toBeNull()
  expect((await entry()).rotation_deg).toBe(120)
  await page.locator('#canvas-area').click({ position: { x: 10, y: 10 } })
  await expect(page.locator('.nadoc-anno--editing')).toHaveCount(0)
  await expect(panel.locator('.anno-card.is-selected')).toHaveCount(0)
  await panel.locator('.sidebar-close').click()
  await box.click()
  await expect(panel).toBeVisible()
  await expect(panel.locator('.anno-card.is-selected')).toHaveCount(1)
  await expect(page.locator('.nadoc-anno--editing')).toHaveCount(1)
  await page.locator('#canvas-area').click({ position: { x: 10, y: 10 } })
  await panel.locator('.anno-text').click()
  await expect(page.locator('.nadoc-anno--editing')).toHaveCount(1)
  await expect(page.locator('.nadoc-anno__handle--rotate:visible')).toHaveCount(4)
  await expect(page.locator('.nadoc-anno__handle:not(.nadoc-anno__handle--rotate):visible')).toHaveCount(8)
  await panel.locator('[data-field="manual"]').uncheck()
  await expect(page.locator('.nadoc-anno--editing')).toHaveCount(0)
  await box.click()
  await expect(panel.locator('.anno-card.is-selected')).toHaveCount(1)
  await expect(page.locator('.nadoc-anno--editing')).toHaveCount(0)
  await panel.locator('[data-field="manual"]').check()
  await expect(page.locator('.nadoc-anno--editing')).toHaveCount(1)
  expect(errors).toEqual([])
})
