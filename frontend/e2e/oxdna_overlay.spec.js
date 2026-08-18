import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DESIGN = readFileSync(fileURLToPath(new URL('../../workspace/VoltronCoreArm.nadoc', import.meta.url)), 'utf8')

test('oxDNA colors pixels and follows reference visibility across the Simulations tab', async ({ page }) => {
  test.setTimeout(900_000)
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.stack || error.message))
  await page.goto('/?doc=e2e-oxdna-overlay')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(button => { button.disabled = false })
    window.__leftSidebar?.refresh?.()
  }, DESIGN)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length ?? 0), { timeout: 120_000 })
    .toBeGreaterThan(0)
  const repairedClusters = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.cluster_transforms
    .map(cluster => ({ name: cluster.name, helices: cluster.helix_ids.length, domains: cluster.domain_ids.length })))
  expect(repairedClusters).toEqual([
    { name: 'Scaffold Cluster 1', helices: 9, domains: 0 },
    { name: 'Geometry Cluster 1', helices: 9, domains: 0 },
  ])
  await page.evaluate(() => document.getElementById('repr-color-cluster').click())
  const fullClusterColors = await page.evaluate(() => window.__nadocTest.nativeBackboneColorCensus())
  expect(fullClusterColors.active).toEqual([0xffd93d])
  const counts = await page.evaluate(() => {
    const state = window.__nadocTest.store.getState()
    const refs = new Set(state.currentDesign.strands.filter(strand => strand.is_reference).map(strand => strand.id))
    return {
      total: state.currentGeometry.length,
      active: state.currentGeometry.filter(nucleotide => !refs.has(nucleotide.strand_id)).length,
    }
  })
  expect(counts.active).toBeLessThan(counts.total)

  const primitiveCount = () => page.evaluate(() => {
    let count = 0
    window.__nadocTest.scene.traverse(object => {
      if (object.userData?.oxdnaPrimitive === 'backbone') count += object.count
    })
    return count
  })
  await page.evaluate(() => window.__nadocTest.setRepresentation('oxdna'))
  await expect.poll(primitiveCount, { timeout: 120_000 }).toBe(counts.total)
  await page.evaluate(() => document.getElementById('repr-color-cluster').click())
  const colorContracts = await page.evaluate(() => {
    const contracts = []
    window.__nadocTest.scene.traverse(object => {
      if (!object.userData?.oxdnaPrimitive) return
      contracts.push({
        primitive: object.userData.oxdnaPrimitive,
        materialColor: object.material.color.getHex(),
        vertexColors: object.material.vertexColors,
        geometryColor: !!object.geometry.getAttribute('color'),
        instanceColor: !!object.instanceColor,
      })
    })
    return contracts
  })
  expect(colorContracts).toHaveLength(4)
  expect(colorContracts.every(contract => contract.materialColor === 0xffffff)).toBe(true)
  expect(colorContracts.every(contract => !contract.vertexColors && !contract.geometryColor)).toBe(true)
  expect(colorContracts.every(contract => contract.instanceColor)).toBe(true)
  const oxdnaClusterColors = await page.evaluate(() => {
    const colors = new Set()
    window.__nadocTest.scene.traverse(object => {
      if (object.userData?.oxdnaPrimitive !== 'backbone') return
      const THREEColor = object.material.color.constructor
      const sample = new THREEColor()
      for (let i = 0; i < object.count; i++) {
        object.getColorAt(i, sample)
        colors.add(sample.getHex())
      }
    })
    return [...colors]
  })
  expect(oxdnaClusterColors).toContain(0xffd93d)
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const box = new THREE.Box3(), position = new THREE.Vector3()
    const quaternion = new THREE.Quaternion(), scale = new THREE.Vector3()
    window.__nadocTest.scene.traverse(object => {
      if (object.userData?.oxdnaPrimitive !== 'backbone') return
      const matrix = new THREE.Matrix4()
      for (let i = 0; i < object.count; i++) {
        object.getMatrixAt(i, matrix)
        matrix.decompose(position, quaternion, scale)
        box.expandByPoint(position)
      }
    })
    const center = box.getCenter(new THREE.Vector3())
    const extent = box.getSize(new THREE.Vector3()).length()
    window.__nadocTest.applyCameraPoseForTest({
      position: [center.x + extent * 0.8, center.y + extent * 0.5, center.z + extent * 1.8],
      target: center.toArray(),
    })
  })
  const outsidePixels = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
  expect(outsidePixels.visible).toBeGreaterThan(100)
  expect(outsidePixels.colorful, JSON.stringify(outsidePixels)).toBeGreaterThan(100)
  expect(outsidePixels.black).toBeLessThan(outsidePixels.visible * 0.1)

  await page.evaluate(() => [...document.querySelectorAll('#left-tab-strip .left-tab-btn')]
    .find(button => button.textContent.trim() === 'Simulations')?.click())
  await expect(page.locator('#tab-content-dynamics')).toBeVisible()
  await expect.poll(primitiveCount, { timeout: 120_000 }).toBe(counts.active)
  const simulationPixels = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
  expect(simulationPixels.colorful).toBeGreaterThan(100)
  expect(simulationPixels.black).toBeLessThan(simulationPixels.visible * 0.1)
  expect(pageErrors).toEqual([])
})
