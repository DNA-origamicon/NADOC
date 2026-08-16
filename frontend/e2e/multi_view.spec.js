import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FIXTURE = readFileSync(fileURLToPath(
  new URL('../../workspace/2hb_1xT.nadoc', import.meta.url)), 'utf8')

test('multi-view controls live inside responsive synchronized viewport panels', async ({ page }) => {
  test.setTimeout(90_000)
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.stack || error.message))

  await page.goto('/?doc=e2e-multi-view')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    // importDesign updates data directly; reveal the normal editing chrome that
    // the full workspace-open lifecycle would otherwise unlock.
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
  }, FIXTURE)

  await page.locator('.right-tab-btn[data-tab="visualization"]').click()
  const section = page.locator('#right-multi-view')
  await expect(section).toBeVisible()
  await section.locator('.mv-layout-btn[data-count="3"]').click()

  const grid = page.locator('.mv-viewport-grid')
  await expect(grid).toHaveAttribute('data-count', '3')
  await expect(grid.locator('.mv-viewport-panel')).toHaveCount(3)
  await expect(section.locator('select')).toHaveCount(0)
  await expect(grid.locator('.mv-representation')).toHaveCount(3)
  await expect(grid.locator('.mv-coloring')).toHaveCount(3)

  // Each Molecular-Audit-style control head must be geometrically inside its panel.
  const contained = await grid.locator('.mv-viewport-panel').evaluateAll(panels => panels.every(panel => {
    const p = panel.getBoundingClientRect()
    const h = panel.querySelector('.mv-panel-head').getBoundingClientRect()
    return h.left >= p.left && h.top >= p.top && h.right <= p.right && h.bottom <= p.bottom
  }))
  expect(contained).toBe(true)

  // Representation changes update that panel's coloring choices in place.
  await grid.locator('.mv-representation').nth(1).selectOption('vdw')
  await expect(grid.locator('.mv-coloring').nth(1)).toHaveValue('cpk')
  await expect(grid.locator('.mv-viewport-panel[data-ready="true"]')).toHaveCount(3, { timeout: 60_000 })

  // One OrbitControls instance drives the camera used by every panel render.
  const poseBefore = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera.position)
  const firstPanel = await grid.locator('.mv-viewport-panel').first().boundingBox()
  await page.mouse.move(firstPanel.x + firstPanel.width * 0.5, firstPanel.y + firstPanel.height * 0.55)
  await page.mouse.down()
  await page.mouse.move(firstPanel.x + firstPanel.width * 0.62, firstPanel.y + firstPanel.height * 0.62, { steps: 8 })
  await page.mouse.up()
  const poseAfter = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera.position)
  expect(poseAfter).not.toEqual(poseBefore)

  // Wheel input is routed through the hovered panel's own OrbitControls bounds,
  // then propagated to the shared navigation state.
  const secondPanel = await grid.locator('.mv-viewport-panel').nth(1).boundingBox()
  const zoomBefore = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera.position)
  await page.mouse.move(secondPanel.x + secondPanel.width * 0.7, secondPanel.y + secondPanel.height * 0.65)
  await page.mouse.wheel(0, -420)
  await expect.poll(async () => {
    const next = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera.position)
    return next.some((value, index) => Math.abs(value - zoomBefore[index]) > 1e-5)
  }).toBe(true)

  // Collapsing the sidebar enlarges the canvas and the panel grid follows it.
  const before = await grid.boundingBox()
  await page.locator('#right-tab-toggle').click()
  await expect(page.locator('#right-panel')).toHaveClass(/hidden/)
  await expect.poll(async () => (await grid.boundingBox()).width).toBeGreaterThan(before.width)
  const [canvasBox, gridBox] = await Promise.all([
    page.locator('#canvas').boundingBox(), grid.boundingBox(),
  ])
  expect(Math.abs(canvasBox.width - gridBox.width)).toBeLessThanOrEqual(1)
  expect(Math.abs(canvasBox.height - gridBox.height)).toBeLessThanOrEqual(1)

  // Multi-overlay is mutually exclusive with Multi-view and keeps its numbered
  // representation/opacity controls in the 3D viewport.
  await page.locator('#right-tab-toggle').click()
  await page.locator('#right-multi-overlay .mo-count-btn[data-count="3"]').click()
  await expect(grid).toHaveAttribute('data-count', '')
  const overlayControls = page.locator('.mo-viewport-controls')
  await expect(overlayControls.locator('.mo-layer-row')).toHaveCount(3)
  await expect(overlayControls.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(3, { timeout: 60_000 })
  await expect(overlayControls.locator('.mo-representation')).toHaveCount(3)
  await expect(overlayControls.locator('.mo-coloring')).toHaveCount(3)
  await expect(overlayControls.locator('.mo-opacity')).toHaveCount(3)
  await overlayControls.locator('.mo-opacity').nth(1).evaluate(input => {
    input.value = '0.35'; input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await expect(overlayControls.locator('.mo-layer-row').nth(1).locator('output')).toHaveText('35%')
  await page.locator('#right-multi-overlay .mo-separation-row input').evaluate(input => {
    input.value = '1'; input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await expect(page.locator('#right-multi-overlay .mo-separation-row output')).toHaveText('100%')

  expect(pageErrors).toEqual([])
})
