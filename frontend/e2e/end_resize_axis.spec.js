import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

// Persistence inventory: __e2e__ parts + hidden project revisions are removed
// by global-teardown; session caching is disabled by the isolated config.
// Screenshots stay in Playwright output and its cleanup reporter removes them.
for (const type of ['bend', 'twist']) test(`${type}: end trim preview follows transformed axis and Escape preserves geometry`, async ({ page }, info) => {
  test.setTimeout(90000)
  const errors = []
  page.on('pageerror', e => errors.push(String(e)))
  const doc = `__e2e__end-resize-axis-${type}`
  await loadScaffoldedPart(page, { doc, name: `end-resize-axis-${type}` })
  await page.evaluate(async type => {
    const api = await import('/src/api/client.js')
    const created = await api.createBundle({ cells: [[0, 0], [1, 0]], lengthBp: 200, name: `__e2e__axis-${type}`, latticeType: 'SQUARE' })
    if (created?.design?.helices?.length !== 2) throw new Error('Two-helix bundle creation failed')
    const deformed = await api.addDeformation(type, 0, 199, type === 'bend'
      ? { kind: 'bend', curvature_deg_per_bp: 100 / 199, direction_deg: 0 }
      : { kind: 'twist', total_degrees: 180 })
    if (deformed?.design?.deformations?.length !== 1) throw new Error('Fixture deformation failed')
  }, type)
  const originalGeometry = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentGeometry))
  const pose = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { store } = await import('/src/state/store.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    const state = store.getState()
    const n = state.currentGeometry.find(n => n.is_three_prime && n.direction === 'FORWARD')
    if (!n) throw new Error('No forward 3-prime fixture end')
    createSelectionController({ store }).replace([{ kind: 'end', key: `${n.helix_id}:${n.bp_index}:${n.direction}` }])
    const samples = state.currentHelixAxes[n.helix_id].samples
    const box = new THREE.Box3().setFromPoints(samples.map(p => new THREE.Vector3(...p)))
    const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length()
    const pose = { position: center.clone().add(new THREE.Vector3(size * .15, -size * 1.8, size * .1)).toArray(), target: center.toArray(), up: [0, 0, 1], fov: 45 }
    window.__nadocTest.applyCameraPoseForTest(pose)
    return pose
  })
  await page.waitForTimeout(300)
  const points = await page.evaluate(async pose => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const rect = document.getElementById('canvas').getBoundingClientRect()
    const camera = new THREE.PerspectiveCamera(pose.fov, rect.width / rect.height, .1, 10000)
    camera.position.fromArray(pose.position); camera.up.fromArray(pose.up); camera.lookAt(...pose.target); camera.updateMatrixWorld()
    const arrow = window.__nadocTest.scene.getObjectByName('endExtrudeArrows').children[0]
    arrow.updateWorldMatrix(true, true)
    const grab = arrow.children[0].getWorldPosition(new THREE.Vector3())
    const target = arrow.userData.dragMeta.resizeAxis.point(100)
    const screen = p => { const q = p.clone().project(camera); return { x: rect.left + (q.x + 1) * rect.width / 2, y: rect.top + (1 - q.y) * rect.height / 2 } }
    return { grab: screen(grab), target: screen(target), extend: screen(arrow.userData.dragMeta.resizeAxis.point(219)), original: arrow.position.toArray() }
  }, pose)
  await page.mouse.move(points.grab.x, points.grab.y)
  await page.mouse.down()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.controlsEnabled())).toBe(false)
  await page.mouse.move(points.extend.x, points.extend.y, { steps: 8 })
  const extension = await page.evaluate(() => {
    const meshes = window.__nadocTest.scene.getObjectByName('endExtrudeArrowsPreview').children
    return { count: meshes.length, cyan: meshes.every(m => m.material.color.getHex() === 0x00e5ff) }
  })
  expect(extension.count).toBeGreaterThan(0)
  expect(extension.cyan).toBe(true)
  await page.mouse.move(points.target.x, points.target.y, { steps: 20 })
  const preview = await page.evaluate(() => {
    const scene = window.__nadocTest.scene
    const meshes = scene.getObjectByName('endExtrudeArrowsPreview').children
    const arrow = scene.getObjectByName('endExtrudeArrows').children[0]
    return { count: meshes.length, trim: meshes.every(m => m.material.color.getHex() === 0xff4400), position: arrow.position.toArray(), directions: meshes.map(m => m.quaternion.toArray()) }
  })
  expect(preview.count).toBeGreaterThan(3)
  expect(preview.trim).toBe(true)
  expect(new Set(preview.directions.map(q => q.map(v => v.toFixed(3)).join(','))).size).toBeGreaterThan(2)
  expect(preview.position).not.toEqual(points.original)
  await page.screenshot({ path: info.outputPath(`${type}-preview.png`) })
  if (process.env.NADOC_REVIEW_HOLD) await page.waitForTimeout(Number(process.env.NADOC_REVIEW_HOLD))
  await page.keyboard.press('Escape')
  await page.mouse.up()
  expect(await page.evaluate(() => window.__nadocTest.scene.getObjectByName('endExtrudeArrowsPreview').children.length)).toBe(0)
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentGeometry))).toBe(originalGeometry)
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.helices[0].length_bp)).toBe(200)
  expect(errors).toEqual([])
})
