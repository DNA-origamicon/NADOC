import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

// Only __e2e__ parts and their project revisions persist; global-teardown removes
// both. Session caching is disabled; Playwright's reporter removes screenshots.
test('fresh cells form a cluster, mixed continuation keeps its cluster through undo and reload', async ({ page }, info) => {
  test.setTimeout(90000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await loadScaffoldedPart(page, { doc: '__e2e__extrusion-clusters', name: 'extrusion-clusters' })
  const result = await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    await api.createBundle({ cells: [[0, 0]], lengthBp: 42, name: '__e2e__extrusion-clusters', latticeType: 'SQUARE' })
    const original = structuredClone(store.getState().currentDesign)
    await api.addBundleSegment({ cells: [[0, 1], [4, 4]], lengthBp: 21 })
    const fresh = structuredClone(store.getState().currentDesign)
    await api.addBundleContinuation({ cells: [[0, 0], [0, 2]], lengthBp: 21,
      offsetNm: original.helices[0].axis_end.z, sourceFrameId: original.lattice_frames[0].id })
    const mixed = structuredClone(store.getState().currentDesign)
    await api.undo()
    const undone = structuredClone(store.getState().currentDesign)
    await api.redo()
    return { original, fresh, mixed, undone, redone: store.getState().currentDesign }
  })
  expect(result.fresh.cluster_transforms).toHaveLength(2)
  expect(result.fresh.cluster_transforms[0]).toEqual(result.original.cluster_transforms[0])
  expect(result.fresh.cluster_transforms[1].helix_ids).toHaveLength(2)
  expect(result.mixed.cluster_transforms).toHaveLength(2)
  expect(result.mixed.cluster_transforms[0].helix_ids).toHaveLength(2)
  expect(result.mixed.cluster_transforms[1]).toEqual(result.fresh.cluster_transforms[1])
  expect(result.undone.cluster_transforms).toEqual(result.fresh.cluster_transforms)
  expect(result.redone.cluster_transforms).toEqual(result.mixed.cluster_transforms)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.saveDesign('workspace/__e2e__extrusion-clusters-reload.nadoc')
    await api.loadDesign('workspace/__e2e__extrusion-clusters-reload.nadoc')
  })
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.helices.length === 4)
  expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.cluster_transforms)).toEqual(result.mixed.cluster_transforms)
  await page.locator('.right-tab-btn[data-tab="clustering"]').click()
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const axes = Object.values(window.__nadocTest.store.getState().currentHelixAxes)
    const points = axes.flatMap(a => [a.start, a.end]).map(p => new THREE.Vector3(...p))
    const bounds = new THREE.Box3().setFromPoints(points)
    const center = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3()).length()
    window.__nadocTest.applyCameraPoseForTest({ target: center.toArray(),
      position: center.clone().add(new THREE.Vector3(size * .7, -size * 2, size * .5)).toArray(),
      up: [0, 0, 1], fov: 45 })
  })
  await page.waitForTimeout(400)
  expect((await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(80))).length).toBeGreaterThan(0)
  await page.screenshot({ path: process.env.NADOC_REVIEW_SCREENSHOT || info.outputPath('extrusion-clusters.png') })
  expect(errors).toEqual([])
})
