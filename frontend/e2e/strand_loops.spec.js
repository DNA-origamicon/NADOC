/** Isolated smoke server only. __e2e__ parts are removed by global-teardown;
 * session cache is disabled. Screenshots/traces stay in Playwright output. */
import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('3D right-click adds a scaffold loop and consumes its sequence', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__strand_loop_3d', name: 'strand_loop_3d' })
  await page.evaluate(() => {
    const t = window.__nadocTest
    const beads = t.getDesignRenderer().getBackboneEntries().map(e => e.nuc.backbone_position)
    const center = [0, 1, 2].map(i => beads.reduce((sum, p) => sum + p[i], 0) / beads.length)
    t.applyCameraPoseForTest({ target: center, position: [center[0] + 70, center[1] + 40, center[2] + 10], up: [0, 0, 1] })
  })
  await page.waitForTimeout(200)
  await page.screenshot({ path: testInfo.outputPath('before-loop-3d.png') })
  const points = await page.evaluate(() => window.__nadocTest.getFlexibleMarkScreenPositions())
  expect(points.length).toBeGreaterThan(0)
  for (const point of points.filter(p => p.y > 220 && p.y < 460 && p.x > 330 && p.x < 940)) {
    await page.mouse.click(point.x, point.y, { button: 'right' })
    if (await page.getByText('Add loop here', { exact: true }).isVisible().catch(() => false)) break
    await page.keyboard.press('Escape')
  }
  await page.getByText('Add loop here', { exact: true }).click()
  await expect(page.locator('#strand-loop-dialog .input')).toHaveCount(3)
  await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('loop-options.png') })
  await page.locator('#strand-loop-dialog [name="length"]').fill('30')
  await page.getByRole('button', { name: 'Add loop', exact: true }).click()
  await expect(page.locator('#strand-loop-dialog')).toHaveCount(0)
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign.strands.some(s => s.loops?.length))
  const info = await page.evaluate(() => {
    const t = window.__nadocTest
    const s = t.store.getState().currentDesign.strands.find(s => s.loops?.length)
    return { length: s.sequence.length, loop: s.loops[0], count: t.getDesignRenderer().getBackboneEntries().filter(e => e.nuc.loop_order > 0).length }
  })
  expect(info.loop.length).toBe(30)
  expect(info.length).toBe(230)
  expect(info.count).toBe(30)
  await page.locator('#menu-seq-assign-scaffold').evaluate(el => el.click())
  const target = page.getByLabel('Scaffold sequence target', { exact: true })
  const dialog = page.locator('.modal__overlay').filter({ has: target })
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(target).toBeHidden()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign.strands
    .find(s => s.loops?.length)?.sequence?.match(/^[ACGT]{230}$/))
  await page.evaluate(() => {
    const t = window.__nadocTest
    const loop = t.getDesignRenderer().getBackboneEntries().map(e => e.nuc).filter(n => n.loop_order > 0)
    const center = [0, 1, 2].map(i => loop.reduce((sum, n) => sum + n.backbone_position[i], 0) / loop.length)
    const radius = Math.max(...loop.map(n => Math.hypot(...n.backbone_position.map((v, i) => v - center[i]))))
    t.applyCameraPoseForTest({ target: center, position: [center[0] + radius * 3.5, center[1] + radius * 2, center[2] + radius * .2], up: [0, 0, 1] })
  })
  await page.waitForTimeout(200)
  await page.screenshot({ path: testInfo.outputPath('loop-3d.png') })
  expect(errors).toEqual([])
})

test('cadnano right-click creates, edits and removes a staple loop', async ({ page, request }, testInfo) => {
  test.setTimeout(60000)
  const errors = trackConsoleErrors(page)
  const api = process.env.NADOC_E2E_API_BASE
  const headers = { 'X-NADOC-Doc': '__e2e__strand_loop_cadnano' }
  const response = await request.post(`${api}/api/design/bundle`, { headers, data: {
    name: '__e2e__strand_loop_cadnano', cells: [[0,0]], length_bp: 42, lattice_type: 'HONEYCOMB', ligate_adjacent: false,
  } })
  expect(response.ok()).toBe(true)
  await page.route('**/src/cadnano-editor/pathview.js', async route => {
    const source = await route.fetch()
    await route.fulfill({ response: source, body: (await source.text()).replace('  // ── Public interface', `
  window.__strandLoopPoint = () => {
    const strand = _design.strands.find(s => s.strand_type === 'staple'), d = strand.domains[0], row = _rowMap.get(d.helix_id)
    const rect = canvasEl.getBoundingClientRect()
    return {x: rect.left + _bpCenterX(20)*_zoom + _panX,
      y: rect.top + (d.direction === 'FORWARD' ? row.fwdY : row.revY)*_zoom + _panY}
  }
  // ── Public interface`) })
  })
  await page.goto('/cadnano-editor.html?doc=__e2e__strand_loop_cadnano')
  await page.waitForFunction(() => window.__strandLoopPoint)
  const point = await page.evaluate(() => window.__strandLoopPoint())
  await page.mouse.click(point.x, point.y, { button: 'right' })
  await page.getByText('Add loop here', { exact: true }).click()
  await expect(page.locator('#strand-loop-dialog .input')).toHaveCount(3)
  await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('loop-options.png') })
  await page.locator('#strand-loop-dialog [name="length"]').fill('30')
  await page.getByRole('button', { name: 'Add loop', exact: true }).click()
  await expect(page.locator('#strand-loop-dialog')).toHaveCount(0)
  let design = (await (await request.get(`${api}/api/design`, { headers })).json()).design
  expect(design.strands.find(s => s.strand_type === 'staple').sequence).toBe('N'.repeat(72))
  await page.screenshot({ path: testInfo.outputPath('loop-cadnano.png') })
  await page.mouse.click(point.x, point.y, { button: 'right' })
  await page.getByText('Edit loop…', { exact: true }).click()
  await page.setViewportSize({ width: 390, height: 640 })
  await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('loop-options-edit-narrow.png') })
  await page.getByRole('button', { name: 'Remove loop', exact: true }).click()
  await expect(page.locator('#strand-loop-dialog')).toHaveCount(0)
  design = (await (await request.get(`${api}/api/design`, { headers })).json()).design
  expect(design.strands.every(s => !s.loops.length)).toBe(true)
  expect(errors).toEqual([])
})

test('3D staple right-click adds a loop without prior selection', async ({ page, request }) => {
  test.setTimeout(45000)
  const errors = trackConsoleErrors(page)
  const headers = { 'X-NADOC-Doc': '__e2e__strand_loop_staple' }
  const api = process.env.NADOC_E2E_API_BASE
  expect((await request.post(`${api}/api/design/bundle`, { headers, data: {
    name: '__e2e__strand_loop_staple', cells: [[0,0]], length_bp: 42, lattice_type: 'HONEYCOMB', ligate_adjacent: false,
  } })).ok()).toBe(true)
  await page.goto('/?doc=__e2e__strand_loop_staple&readiness=simulation')
  await page.waitForFunction(() => window.__nadocTest?.getDesignRenderer()?.getBackboneEntries()?.length > 0)
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [25, 15, 7], target: [0,0,7], up: [0,0,1] }))
  await page.waitForTimeout(200)
  const points = await page.evaluate(async () => {
    const t = window.__nadocTest, box = document.getElementById('canvas').getBoundingClientRect()
    return t.getDesignRenderer().getBackboneEntries().filter(e => e.nuc.strand_type === 'staple' && e.nuc.bp_index > 8 && e.nuc.bp_index < 33).map(e => {
      const m = e.instMesh.matrix.clone()
      e.instMesh.getMatrixAt(e.id, m)
      const p = t.camera.position.clone().setFromMatrixPosition(m).applyMatrix4(e.instMesh.matrixWorld).project(t.camera)
      const x = box.left + (p.x + 1) * box.width / 2, y = box.top + (1 - p.y) * box.height / 2
      return { x, y, id: e.nuc.strand_id }
    }).filter(p => t.pickBeadAt(p.x, p.y)?.strand_id === p.id)
  })
  expect(points.length).toBeGreaterThan(0)
  await page.mouse.click(points[0].x, points[0].y, { button: 'right' })
  await page.getByText('Add loop here', { exact: true }).click()
  await page.locator('#strand-loop-dialog [name="rotation"]').fill('90')
  await page.getByRole('button', { name: 'Add loop', exact: true }).click()
  await expect(page.locator('#strand-loop-dialog')).toHaveCount(0)
  const design = (await (await request.get(`${api}/api/design`, { headers })).json()).design
  const strand = design.strands.find(s => s.loops.length)
  expect(strand.strand_type).toBe('staple')
  expect(strand.sequence).toBe('N'.repeat(72))
  expect(strand.loops[0].rotation_deg).toBe(90)
  expect(errors).toEqual([])
})
