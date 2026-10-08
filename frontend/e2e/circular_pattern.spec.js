import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

// Persistence inventory: only __e2e__circular-axis*.nadoc, __e2e__circular-confirm*.nadoc and project
// history via loadScaffoldedPart. global-teardown.js removes both on all outcomes.
// Session caching is disabled by the Playwright server config. Screenshots use
// testInfo.outputPath and the cleanup reporter removes them on all outcomes.
test('drag and lattice-snap a circular axis and preview instances without editing the part', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await loadScaffoldedPart(page, { doc: 'e2e-circular-axis', name: 'circular-axis' })
  const before = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    await api.createCluster({ name: 'Axis study cluster', helix_ids: [store.getState().currentDesign.helices[0].id] })
    await api.createCluster({ name: 'Center study cluster', helix_ids: [store.getState().currentDesign.helices[0].id] })
    const design = store.getState().currentDesign
    const id = design.cluster_transforms[0].id
    store.setState({ selection: { context: 'design', level: 'cluster', items: [{ kind: 'cluster', id }], primary: { kind: 'cluster', id } } })
    return JSON.stringify([design.helices, design.strands, design.cluster_transforms, design.nucleotide_transforms, design.feature_log])
  })
  await page.locator('#right-tab-strip [data-tab=visualization]').click()
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-circular-pattern').click()
  await expect(page.locator('.tool-popup #circular-pattern-panel')).toBeVisible()
  await expect(page.locator('#menu-debug-circular-pattern')).toHaveCount(0)
  await expect(page.locator('.modal__overlay')).toHaveCount(0)
  await expect(page.locator('#circular-pattern-panel .tool-picking-hint')).toContainText('Select a cluster')
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('cluster')
  await page.locator('#right-tab-strip [data-tab=clustering]').click()
  // Pick through the real 3D cluster selector, with a side view exposing the bundle.
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const points = store.getState().currentGeometry.map(n => n.backbone_position)
    const center = points.reduce((sum, p) => sum.map((v, i) => v + p[i] / points.length), [0, 0, 0])
    const radius = Math.max(...points.map(p => Math.hypot(...p.map((v, i) => v - center[i]))))
    window.__nadocTest.applyCameraPoseForTest({ target: center, position: [center[0] + radius * 3, center[1] + radius * .6, center[2] + radius * .3] })
  })
  const candidates = await page.evaluate(() => {
    const rects = ['.tool-popup', '#left-panel', '#right-panel', '#menu-bar'].flatMap(selector => [...document.querySelectorAll(selector)].map(node => node.getBoundingClientRect()))
    const canvas = document.getElementById('canvas').getBoundingClientRect()
    return window.__nadocTest.getClusterBeadScreenPositions().filter(p =>
      p.x > canvas.left && p.x < canvas.right && p.y > canvas.top && p.y < canvas.bottom &&
      !rects.some(r => p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom))
  })
  expect(candidates.length).toBeGreaterThan(0)
  for (const point of candidates.slice(0, 12)) {
    await page.mouse.click(point.x, point.y)
    if (await page.locator('.cp-panel-body').isVisible()) break
  }
  await expect(page.locator('.cp-panel-body')).toBeVisible()
  for (const name of ['Cluster', 'Direction', 'Origin', 'Pattern', 'Info']) {
    await expect(page.locator('#circular-pattern-panel').getByRole('group', { name, exact: true })).toHaveCSS('border-top-width', '1px')
  }
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('default')
  await expect(page.locator('#circular-pattern-panel canvas')).toHaveCount(0)
  await expect.poll(() => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const corners = window.__nadocTest.scene.getObjectByName('clusterSelectionCorners')
    return { selected: store.getState().selection.items.length, highlighted: corners?.visible ?? false }
  })).toEqual({ selected: 0, highlighted: false })
  const previewData = () => page.evaluate(() => window.__nadocTest.scene.getObjectByName('circularPatternPreview')?.userData)
  expect((await previewData()).instances).toBe(6)
  await expect(page.getByRole('spinbutton', { name: 'Total angle (degrees)', exact: true })).toHaveValue('360')
  const angle = page.getByRole('spinbutton', { name: 'Total angle (degrees)', exact: true })
  await angle.press('ArrowDown')
  await expect(angle).toHaveValue('359')
  await angle.press('ArrowUp')
  await expect(angle).toHaveValue('360')
  expect((await previewData()).instances).toBe(6)
  const snap = page.getByRole('checkbox', { name: 'Snap to lattice' })
  await expect(snap).toBeEnabled()
  expect((await previewData()).latticeVisible).toBe(true)
  await snap.check()
  await page.locator("#right-tab-toggle").click()
  await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const { circularPatternCluster } = await import('/src/ui/circular_pattern_panel.js')
    const { clusterLattice } = await import('/src/ui/circular_pattern_math.js')
    const d = clusterLattice(store.getState(), circularPatternCluster(store.getState(), window.__nadocTest.scene.getObjectByName('circularPatternPreview').userData.sourceClusterId)).normal.toArray()
    const preview = window.__nadocTest.scene.getObjectByName('circularPatternPreview')
    const target = preview.position.toArray().map((v, i) => v + preview.userData.axisPoint[i])
    window.__nadocTest.applyCameraPoseForTest({ target, position: target.map((v, i) => v + d[i] * 200), up: Math.abs(d[1]) < .9 ? [0, 1, 0] : [1, 0, 0] })
  })
  const bead = page.getByRole('button', { name: 'Move rotation axis', exact: true })
  await bead.click({ trial: true, timeout: 5000 })
  const box = await bead.boundingBox()
  const beforeDrag = await page.getByRole('spinbutton', { name: 'Origin offset (nm) X', exact: true }).inputValue()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 35, box.y + box.height / 2 + 20, { steps: 8 })
  await page.mouse.up()
  expect(await page.getByRole('spinbutton', { name: 'Origin offset (nm) X', exact: true }).inputValue()).not.toBe(beforeDrag)
  // The dragged offset must be a true registered lattice site, not a screen grid.
  const snapError = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const { circularPatternCluster } = await import('/src/ui/circular_pattern_panel.js')
    const { clusterLattice, snapToLattice } = await import('/src/ui/circular_pattern_math.js')
    const state = store.getState(), target = circularPatternCluster(state, window.__nadocTest.scene.getObjectByName('circularPatternPreview').userData.sourceClusterId)
    const point = window.__nadocTest.scene.getObjectByName('circularPatternPreview').userData.axisPoint
    return Math.hypot(...snapToLattice(clusterLattice(state, target), point).map((v, i) => v - point[i]))
  })
  expect(snapError).toBeLessThan(1e-8)
  await page.getByRole('button', { name: 'X', exact: true }).click()
  await expect(snap).toBeDisabled()
  await expect(snap).not.toBeChecked()
  expect((await previewData()).latticeVisible).toBe(false)
  await page.getByRole('button', { name: 'Helices', exact: true }).click()
  await expect(snap).toBeEnabled()
  const source = page.getByRole('combobox', { name: 'Cluster', exact: true })
  const ids = await source.locator('option').evaluateAll(options => options.map(o => o.value))
  expect(ids).toHaveLength(2)
  await expect(source).toHaveValue((await previewData()).sourceClusterId)
  await expect(page.locator('.tool-popup[data-tool-panel="circular-pattern-panel"]')).toHaveCSS('backdrop-filter', 'blur(18px) saturate(1.25)')
  await page.screenshot({ path: testInfo.outputPath('circular-pattern.png') })
  await page.getByRole('button', { name: 'Centered about', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Centered about', exact: true })).toHaveCSS('background-color', 'rgb(31, 111, 235)')
  await expect(page.getByRole('combobox', { name: 'Center cluster', exact: true })).toBeVisible()
  expect((await previewData()).axisPoint).toEqual([0, 0, 0])
  const previousSource = (await previewData()).sourceClusterId
  await source.selectOption(ids.find(id => id !== previousSource))
  expect((await previewData()).centerClusterId).toBe(previousSource)
  await expect(page.getByRole('spinbutton', { name: 'Origin offset (nm) X', exact: true })).not.toBeVisible()
  await page.getByRole('button', { name: 'Offset', exact: true }).click()
  await page.getByRole('spinbutton', { name: 'Origin offset (nm) X', exact: true }).fill('10')
  await expect(page.getByRole('button', { name: 'Centered about', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await page.getByRole('spinbutton', { name: 'Instances', exact: true }).fill('4')
  await page.getByRole('spinbutton', { name: 'Total angle (degrees)', exact: true }).fill('180')
  await expect(page.locator('.cp-readout')).not.toBeVisible()
  expect((await previewData()).instances).toBe(4)
  await page.getByRole('spinbutton', { name: 'Instances', exact: true }).fill('2.5')
  await expect(page.locator('.cp-readout')).toContainText('integer instance count')
  await page.getByRole('spinbutton', { name: 'Instances', exact: true }).fill('1')
  expect((await previewData()).instances).toBe(1)
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.locator('.cp-panel-body')).toHaveCount(0)
  expect(await previewData()).toBeUndefined()
  await expect(page.locator('.cp-bead')).toHaveCount(0)
  expect(await page.evaluate(async () => {
    const { currentDesign: design } = (await import('/src/state/store.js')).store.getState()
    return JSON.stringify([design.helices, design.strands, design.cluster_transforms, design.nucleotide_transforms, design.feature_log])
  })).toBe(before)
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-circular-pattern').click()
  await expect(page.locator('#circular-pattern-panel .tool-picking-hint')).toBeVisible()
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('cluster')
  await page.keyboard.press('Escape')
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('default')
  await expect(page.locator('#circular-pattern-panel')).not.toBeVisible()
  expect(errors).toEqual([])
})

test('confirm creates the displayed BP count and supports undo', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await loadScaffoldedPart(page, { doc: 'e2e-circular-confirm', name: 'circular-confirm' })
  const source = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    return store.getState().currentDesign.cluster_transforms[0].id
  })
  await page.locator('#right-tab-strip [data-tab=clustering]').click()
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-circular-pattern').click()
  await page.locator(`#cluster-list [data-cluster-id="${source}"]`).click()
  await expect(page.locator('.cp-panel-body')).toBeVisible()
  await page.getByRole('spinbutton', { name: 'Instances', exact: true }).fill('3')
  await expect(page.locator('[aria-label="New BP created"]')).toHaveText('400')
  await expect(page.locator('[aria-label="Total after pattern"]')).toHaveText('600')
  await page.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.locator('.cp-panel-body')).toHaveCount(0)
  const result = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    return { bp: d.helices.reduce((sum, h) => sum + h.length_bp, 0), frames: d.lattice_frames.length, op: d.feature_log.at(-1).op_kind }
  })
  expect(result).toEqual({ bp: 600, frames: 2, op: 'circular-pattern' })
  await page.evaluate(async () => { await (await import('/src/api/client.js')).undo() })
  await expect.poll(() => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign.helices.length)).toBe(1)
  expect(errors).toEqual([])
})
