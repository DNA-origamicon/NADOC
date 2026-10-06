import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

// Only __e2e__floating-tools.nadoc and its project history may persist.
// Global teardown removes both after success/failure; server session caching is off.
// Optional NADOC_POPUP_SCREENSHOTS retains review images in .development-artifacts/.
test('extrude, twist and bend float independently of sidebar tabs', async ({ page }) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await loadScaffoldedPart(page, { doc: 'e2e-floating-tools', name: 'floating-tools' })
  await page.locator('#right-tab-strip [data-tab=visualization]').click()
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    window.__nadocTest.openExtrudeAtEnd({ helixId: store.getState().currentDesign.helices[0].id, diskBp: 199 })
  })
  const extrude = page.locator('.tool-popup[data-tool-panel="extrude-panel"]')
  await expect(extrude).toBeVisible()
  await checkPopupSurface(extrude)
  await capturePopup(page, 'extrude')
  await expect(extrude.locator('#slice-length')).toBeVisible()
  await page.locator('#right-tab-strip [data-tab=clustering]').click()
  await expect(extrude).toBeVisible()
  await page.getByRole('button', { name: 'Close Extrude', exact: true }).click()
  await expect(extrude).not.toBeVisible()
  expect(await page.evaluate(() => window.__nadocTest.getSliceState().visible)).toBe(false)

  for (const tool of ['twist', 'bend']) {
    await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      createSelectionController({ store }).clear()
    })
    await page.getByRole('button', { name: 'Tools', exact: true }).hover()
    await page.locator(`#menu-tools-${tool}`).click()
    await expect(page.locator('#def-current-selection')).toBeVisible()
    await expect(page.locator('#def-pick-planes')).toBeDisabled()
    // Canonical preselection, as when launching from a cluster list selection.
    await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const { createSelectionController } = await import('/src/scene/selection_controller.js')
      const cluster = store.getState().currentDesign.cluster_transforms[0]
      createSelectionController({ store }).replace([{ kind: 'cluster', id: cluster.id }])
    })
    await page.locator('#def-pick-planes').click()
    const popup = page.locator('.tool-popup[data-tool-panel="deform-panel"]')
    await expect(popup).toBeVisible()
    await expect(popup.locator('.tool-picking-hint')).toContainText('Select plane A')
    await expect(popup.locator('#def-apply-btn')).toBeDisabled()
    await expect(popup.locator(`#def-${tool}-controls`)).toBeVisible()
    await page.locator('#right-tab-strip [data-tab=visualization]').click()
    await expect(popup).toBeVisible()
    // Exercise dragging through the visible title bar, with the viewport left interactive.
    const before = await popup.boundingBox(), header = await popup.locator('.tool-popup__header').boundingBox()
    await page.mouse.move(header.x + 70, header.y + header.height / 2)
    await page.mouse.down()
    await page.mouse.move(header.x + 105, header.y + header.height / 2 + 20, { steps: 5 })
    await page.mouse.up()
    const after = await popup.boundingBox()
    expect(Math.hypot(after.x - before.x, after.y - before.y)).toBeGreaterThan(5)
    // The same real editor entry point used by a blunt-end action places both planes.
    await page.evaluate(async tool => {
      const { store } = await import('/src/state/store.js')
      const editor = await import('/src/scene/deformation_editor.js')
      editor.exitTool()
      editor.startToolAtBp(tool, store.getState().currentDesign.helices[0].id, 100, 1)
    }, tool)
    await expect(popup.locator('#def-plane-b-bp')).toHaveValue('100')
    await expect(popup.locator('#def-apply-btn')).toBeEnabled()
    await checkPopupSurface(popup)
    await capturePopup(page, tool)
    await page.getByRole('button', { name: `Close ${tool === 'twist' ? 'Twist' : 'Bend'}`, exact: true }).click()
    await expect(popup).not.toBeVisible()
    await expect.poll(() => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().deformToolActive)).toBe(false)
  }
  expect(errors).toEqual([])
})

async function checkPopupSurface(popup) {
  await expect(popup).toHaveCSS('backdrop-filter', 'blur(18px) saturate(1.25)')
  const layout = await popup.evaluate(node => ({
    fits: node.scrollWidth <= node.clientWidth,
    contentFits: node.querySelector('.tool-popup__content').scrollWidth <= node.clientWidth,
    background: getComputedStyle(node).backgroundColor,
  }))
  expect(layout.fits).toBe(true)
  expect(layout.contentFits).toBe(true)
  expect(layout.background).toMatch(/0\.72/)
}

async function capturePopup(page, name) {
  if (process.env.NADOC_POPUP_SCREENSHOTS) {
    // Place real geometry behind the glass to make transparency reviewable.
    await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const points = store.getState().currentGeometry.map(n => n.backbone_position)
      const center = points.reduce((sum, p) => sum.map((v, i) => v + p[i] / points.length), [0, 0, 0])
      window.__nadocTest.applyCameraPoseForTest({ target: center, position: [center[0] + 18, center[1] + 10, center[2] + 3] })
    })
    const popup = page.locator('.tool-popup:visible')
    const box = await popup.boundingBox()
    const canvas = await page.locator('#canvas').boundingBox()
    const header = await popup.locator('.tool-popup__header').boundingBox()
    const x = header.x + 70, y = header.y + header.height / 2
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x + canvas.x + canvas.width / 2 - box.x - box.width / 2,
      y + canvas.y + canvas.height / 2 - box.y - box.height / 2, { steps: 5 })
    await page.mouse.up()
    await page.screenshot({ path: `${process.env.NADOC_POPUP_SCREENSHOTS}/${name}.png` })
  }
}
