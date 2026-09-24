import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Read the reported design without modifying it. Only the __e2e__ copy may
// autosave; global teardown removes its workspace file and revision store.
const source = new URL('../../workspace/3x6SQ_norm_skips.nadoc', import.meta.url)
test('stick volume hides skipped-column cylinder remnants in 3x6SQ_norm_skips', async ({ page }) => {
  test.skip(!existsSync(source), 'Local reported design is unavailable')
  test.setTimeout(120000)
  const design = JSON.parse(readFileSync(source))
  design.id = 'e2e-volume-skips'; design.metadata.name = '__e2e__volume-skips'
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=e2e-volume-skips')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js')
    if (!await api.importDesign(JSON.stringify(design))) throw new Error('Design import failed')
    if (!await api.getGeometry()) throw new Error('Geometry request failed')
  }, design)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length ?? 0)).toBeGreaterThan(0)
  await page.evaluate(() => window.__nadocTest.setRepresentation('cylinders'))
  await expect.poll(() => page.evaluate(() => {
    const keys = window.__NADOC_VIEW_VOLUMES__.layers()[0]?.keys
    return ['h_XY_0_1:38', 'h_XY_2_1:29', 'h_XY_2_0:27'].every(key => keys?.has(key))
  })).toBe(true)
  await expect.poll(() => page.evaluate(() => {
    let ready = false
    window.__nadocTest.scene.traverse(o => { if (o.name.startsWith('view-volume-display-') && o.children.length) ready = true })
    return ready
  }), { timeout: 60000 }).toBe(true)
  const remnants = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { pointInVolume } = await import('/src/scene/view_volumes.js')
    const volume = window.__NADOC_VIEW_VOLUMES__.volumes()[0], remnants = []
    window.__nadocTest.scene.traverseVisible(o => {
      if (o.name !== 'clippedHelixCylinders') return
      for (let i = 0; i < o.count; i++) {
        if ((o.geometry.attributes.instanceAlpha?.getX(i) ?? 1) <= 0) continue
        const matrix = new THREE.Matrix4(), pos = new THREE.Vector3(), scale = new THREE.Vector3()
        o.getMatrixAt(i, matrix); matrix.decompose(pos, new THREE.Quaternion(), scale)
        pos.applyMatrix4(o.matrixWorld)
        if (scale.y < .5 && pointInVolume(pos.toArray(), volume)) remnants.push(pos.toArray())
      }
    })
    return remnants
  })
  expect(remnants).toEqual([])
  expect(errors).toEqual([])
})
