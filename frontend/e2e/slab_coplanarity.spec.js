import { test, expect } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url))
const DESIGN = path.resolve(FRONTEND_DIR, '../../workspace/2hbx1.nadoc')

test('live full-representation pair keeps both largest faces coplanar', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/?doc=slab-coplanarity')
  await page.waitForSelector('#canvas')
  await page.evaluate(async (path) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
  }, DESIGN)
  await expect.poll(() => page.evaluate(() => {
    const { scene } = window.__NADOC_DBG__
    let slabs = null
    scene.traverse((o) => { if (o.name === 'baseSlabs' && o.count >= 2) slabs = o })
    return slabs?.count ?? 0
  }), { timeout: 60_000 }).toBeGreaterThanOrEqual(2)

  const result = await page.evaluate(() => {
    const { scene, THREE, store, designRenderer } = window.__NADOC_DBG__
    let slabs = null
    let cubes = null
    scene.traverse((o) => { if (o.name === 'baseSlabs' && o.count >= 2) slabs = o })
    scene.traverse((o) => { if (o.name === 'backboneCubes' && o.count >= 2) cubes = o })
    slabs.updateMatrixWorld(true)
    cubes.updateMatrixWorld(true)

    const geometry = (store.getState().currentGeometry ?? [])
      .filter((n) => n.strand_id && !n.is_modification && !n.is_flexible_segment)
    const first = geometry[0]
    const mateIndex = geometry.findIndex((n, i) => i > 0
      && n.helix_id === first.helix_id
      && n.bp_index === first.bp_index
      && n.direction !== first.direction)
    const tangent = new THREE.Vector3(...first.axis_tangent).normalize()
    const instance = new THREE.Matrix4()
    const world = new THREE.Matrix4()
    const planes = { bottom: [], top: [] }
    const slabCenters = []

    for (const index of [0, mateIndex]) {
      slabs.getMatrixAt(index, instance)
      world.multiplyMatrices(slabs.matrixWorld, instance)
      slabCenters.push(new THREE.Vector3().setFromMatrixPosition(world).toArray())
      for (const [name, y] of [['bottom', -0.5], ['top', 0.5]]) {
        for (const x of [-0.5, 0.5]) {
          for (const z of [-0.5, 0.5]) {
            const corner = new THREE.Vector3(x, y, z).applyMatrix4(world)
            planes[name].push(corner.dot(tangent))
          }
        }
      }
    }

    const expectedAxial = (
      new THREE.Vector3(...first.base_position).dot(tangent)
      + new THREE.Vector3(...geometry[mateIndex].base_position).dot(tangent)
    ) * 0.5

    const beadInstance = new THREE.Matrix4()
    cubes.getMatrixAt(0, beadInstance)
    const beadWorld = new THREE.Matrix4().multiplyMatrices(cubes.matrixWorld, beadInstance)
    const beadBefore = new THREE.Vector3().setFromMatrixPosition(beadWorld)
    const expectedBead = new THREE.Vector3(...first.backbone_position)

    const slabBefore = new THREE.Matrix4()
    slabs.getMatrixAt(0, slabBefore)
    designRenderer.getHelixCtrl().setBeadOverrides([{
      helix_id: first.helix_id,
      bp_index: first.bp_index,
      direction: first.direction,
      backbone_position: [
        first.backbone_position[0] + 4,
        first.backbone_position[1] - 3,
        first.backbone_position[2] + 2,
      ],
    }])
    const slabAfter = new THREE.Matrix4()
    slabs.getMatrixAt(0, slabAfter)
    const beadAfterInstance = new THREE.Matrix4()
    cubes.getMatrixAt(0, beadAfterInstance)
    const beadAfterWorld = new THREE.Matrix4().multiplyMatrices(cubes.matrixWorld, beadAfterInstance)
    const beadAfter = new THREE.Vector3().setFromMatrixPosition(beadAfterWorld)

    const spread = (xs) => Math.max(...xs) - Math.min(...xs)
    return {
      bottomSpread: spread(planes.bottom),
      topSpread: spread(planes.top),
      slabAxials: slabCenters.map((p) => new THREE.Vector3(...p).dot(tangent)),
      expectedAxial,
      beadInitialError: beadBefore.distanceTo(expectedBead),
      beadMoveDistance: beadAfter.distanceTo(beadBefore),
      slabMatrixDelta: Math.max(...slabBefore.elements.map((v, i) => Math.abs(v - slabAfter.elements[i]))),
    }
  })

  expect(result.bottomSpread).toBeLessThan(1e-9)
  expect(result.topSpread).toBeLessThan(1e-9)
  expect(result.slabAxials[0]).toBeCloseTo(result.expectedAxial, 9)
  expect(result.slabAxials[1]).toBeCloseTo(result.expectedAxial, 9)
  // Instanced matrices are Float32-backed, so payload-to-GPU roundoff is ~1e-7 nm.
  expect(result.beadInitialError).toBeLessThan(1e-6)
  expect(result.beadMoveDistance).toBeGreaterThan(5)
  // Bead-only overrides must re-run the same contact solve instead of snapping
  // slabs back to a legacy center or leaving them disconnected.
  expect(result.slabMatrixDelta).toBeGreaterThan(1)
})
