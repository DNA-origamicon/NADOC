import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

// Only __e2e__floating-tools.nadoc and its project history may persist.
// Global teardown removes both after success/failure; server session caching is off.
// Screenshots stay in testInfo.outputPath and the cleanup reporter removes them.
test('design tools use grouped controls and preserve their selection and cancel flows', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  await page.setViewportSize({ width: 2400, height: 1200 })
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
  await checkSections(extrude, ['Source', 'Length', 'Direction', 'Strands', 'Info'])
  await capturePopup(page, testInfo, 'extrude')
  await expect(extrude.locator('#slice-length')).toBeVisible()
  await page.locator('#right-tab-strip [data-tab=clustering]').click()
  await expect(extrude).toBeVisible()
  await page.getByRole('button', { name: 'Close Extrude', exact: true }).click()
  await expect(extrude).not.toBeVisible()
  expect(await page.evaluate(() => window.__nadocTest.getSliceState().visible)).toBe(false)

  // Multiple named scopes expose the optional cluster picker and its scroll box.
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const api = await import('/src/api/client.js')
    const helix = store.getState().currentDesign.helices[0].id
    for (let i = 1; i <= 7; i++) await api.createCluster({ name: `Tool scope ${i}`, helix_ids: [helix] })
  })

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
    await popup.locator('.tool-popup__header').hover()
    const before = await popup.boundingBox(), header = await popup.locator('.tool-popup__header').boundingBox()
    await page.mouse.move(header.x + 70, header.y + header.height / 2)
    await page.mouse.down()
    await page.mouse.move(header.x + 105, header.y + header.height / 2 + 20, { steps: 5 })
    await page.mouse.up()
    const after = await popup.boundingBox()
    if (Math.hypot(after.x - before.x, after.y - before.y) <= 5) console.log('Popup drag bounds', { before, after, header, canvas: await page.locator('#canvas').boundingBox() })
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
    await checkSections(popup, ['Clusters', 'Planes', tool === 'bend' ? 'Bend' : 'Twist', 'Info'])
    if (tool === 'bend') {
      for (const height of [720, 480]) {
        await page.setViewportSize({ width: 1280, height })
        await expect(popup.locator('#def-cancel-btn')).toBeInViewport({ ratio: 1 })
        await expect(popup.locator('#def-apply-btn')).toBeInViewport({ ratio: 1 })
        const fields = popup.locator('.def-fields')
        await fields.evaluate(node => { node.scrollTop = node.scrollHeight })
        await expect(popup.locator('#def-apply-btn')).toBeInViewport({ ratio: 1 })
        await fields.evaluate(node => { node.scrollTop = 0 })
      }
      const angle = await popup.locator('#def-bend-angle').boundingBox()
      const curvature = await popup.locator('#def-bend-radius').boundingBox()
      expect(Math.abs(angle.y - curvature.y)).toBeLessThan(1)
      expect(curvature.x).toBeGreaterThan(angle.x)
      await expect(popup.getByLabel('Curvature (nm)', { exact: true })).toBeVisible()
      await expect(popup.getByText('Plane 1 stays fixed; the deformation spans the two planes.')).toHaveCount(0)
      await capturePopup(page, testInfo, 'bend-compact')
      await page.setViewportSize({ width: 2400, height: 1200 })
    }
    await expect(popup.locator('#def-cluster-list')).toHaveCSS('overflow-y', 'auto')
    expect(await popup.locator('#def-cluster-list').evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true)
    await expect(popup.locator(`#def-${tool === 'bend' ? 'twist' : 'bend'}-controls`)).toBeHidden()
    await capturePopup(page, testInfo, tool)
    await page.getByRole('button', { name: `Close ${tool === 'twist' ? 'Twist' : 'Bend'}`, exact: true }).click()
    await expect(popup).not.toBeVisible()
    await expect.poll(() => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().deformToolActive)).toBe(false)
  }
  // The same sections also fit the narrower Move/Rotate sidebar.
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const cluster = store.getState().currentDesign.cluster_transforms.find(c => c.helix_ids.length)
    const item = { kind: 'cluster', id: cluster.id }
    store.setState({ selection: { context: 'design', level: 'cluster', items: [item], primary: item } })
  })
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-translate-rotate').click()
  const move = page.locator('#move-rotate-panel')
  await expect(move).toBeVisible()
  await expect(move.locator('#mr-tx')).toBeEnabled()
  await checkSections(move, ['Selection', 'Reference', 'Translation (nm)', 'Rotation (°)', 'Info'])
  await expect(move.locator('#mr-joint-angle-section')).toBeHidden()
  await expect(move.locator('#mr-current-selection')).toHaveCSS('overflow-y', 'auto')
  expect(await move.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
  await move.locator('#mr-tx').fill('7.5')
  await move.locator('#mr-tx').press('Tab')
  await capturePopup(page, testInfo, 'move-rotate')
  await move.locator('#mr-cancel-btn').click()
  await expect(move).toBeHidden()
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

async function checkSections(panel, titles) {
  for (const name of titles) await expect(panel.getByRole('group', { name, exact: true })).toHaveCSS('border-top-width', '1px')
}

async function capturePopup(page, testInfo, name) {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`) })
}
