import { test, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('3D and sidebar cluster selection converge without member-strand state', async ({ page }) => {
  test.setTimeout(60_000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: 'e2e-cluster-selection-model', name: 'cluster-selection-model' })
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const design = store.getState().currentDesign
    const strand = design.strands.find(s => s.domains?.length)
    const domain = strand.domains[0]
    await api.createCluster({
      name: 'Selection Cluster',
      helix_ids: [domain.helix_id],
      domain_ids: [{ strand_id: strand.id, domain_index: 0 }],
    })
  })
  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('f')
  await page.waitForFunction(() => window.__nadocTest?.getClusterBeadScreenPositions?.().length > 0)
  // Side view exposes the tint along the helix; the default axial view hides it.
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const mesh = window.__nadocTest.scene.getObjectByName('backboneSpheres')
    const box = new THREE.Box3(), matrix = new THREE.Matrix4(), point = new THREE.Vector3()
    mesh.updateWorldMatrix(true, false)
    for (let i = 0; i < mesh.count; i++) {
      mesh.getMatrixAt(i, matrix)
      box.expandByPoint(point.setFromMatrixPosition(matrix).applyMatrix4(mesh.matrixWorld))
    }
    const center = box.getCenter(new THREE.Vector3()), span = box.getSize(new THREE.Vector3()).length()
    window.__nadocTest.applyCameraPoseForTest({ target: center.toArray(),
      position: center.clone().add(new THREE.Vector3(1.2, .4, .3).multiplyScalar(span)).toArray() })
  })

  await page.evaluate(() => {
    document.getElementById('select-filter-trigger')?.click()
    document.querySelector('#select-filter .sf-btn[data-key="clust"]')?.click()
  })
  const panels = []
  for (const selector of ['#menu-bar', '#left-panel', '#right-panel']) {
    const box = await page.locator(selector).boundingBox().catch(() => null)
    if (box) panels.push(box)
  }
  const points = (await page.evaluate(() => window.__nadocTest.getClusterBeadScreenPositions()))
    .filter(p => !panels.some(r => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height))
  expect(points.length).toBeGreaterThan(0)

  const point = points[0]
  const before = await page.evaluate(() => {
    const mesh = window.__nadocTest.scene.getObjectByName('backboneSpheres')
    return { matrices: [...mesh.instanceMatrix.array], colors: [...mesh.instanceColor.array] }
  })
  await page.mouse.click(point.x, point.y)
  await expect.poll(async () =>
    (await page.evaluate(() => window.__nadocTest.getCanonicalSelection())).items[0]?.kind,
  ).toBe('cluster')
  const state = await page.evaluate(() => ({
    selection: window.__nadocTest.getCanonicalSelection(),
    projected: window.__nadocTest.getMultiSelection(),
  }))
  const picked = { point, ...state }
  expect(picked.selection.items).toEqual([{ kind: 'cluster', id: picked.point.id }])
  expect(picked.projected.strandIds).toEqual([])

  expect(errors, errors.join("\n")).toEqual([])
  const visual = await page.evaluate(() => {
    const scene = window.__nadocTest.scene
    const mesh = scene.getObjectByName('backboneSpheres')
    return {
      tint: [...mesh.geometry.getAttribute('instanceSelection').array].filter(x => x > 0).length,
      corners: scene.getObjectByName('clusterSelectionCorners').visible,
      glow: scene.getObjectByName('selectionGlow')?.count ?? 0,
      matrices: [...mesh.instanceMatrix.array], colors: [...mesh.instanceColor.array],
    }
  })
  expect(visual.tint).toBeGreaterThan(0)
  expect(visual.corners).toBe(true)
  expect(visual.glow).toBe(0)
  expect(visual.matrices).toEqual(before.matrices)
  expect(visual.colors).toEqual(before.colors)
  if (process.env.NADOC_SELECTION_EVIDENCE) {
    await mkdir(process.env.NADOC_SELECTION_EVIDENCE, { recursive: true })
    await page.locator('#canvas').screenshot({ path: path.join(process.env.NADOC_SELECTION_EVIDENCE, 'desktop-selected.png') })
  }

  await page.mouse.click(picked.point.x, picked.point.y)
  await expect.poll(async () =>
    (await page.evaluate(() => window.__nadocTest.getCanonicalSelection())).items.length,
  ).toBe(0)

  expect(await page.evaluate(() => {
    const scene = window.__nadocTest.scene
    const mesh = scene.getObjectByName('backboneSpheres')
    return [...mesh.geometry.getAttribute('instanceSelection').array].every(x => x === 0) &&
      !scene.getObjectByName('clusterSelectionCorners').visible
  })).toBe(true)

  await page.evaluate(() => {
    document.querySelector('.right-tab-btn[data-tab="clustering"]')?.click()
  })
  const row = page.locator(`#cluster-list [data-cluster-id="${picked.point.id}"]`)
  await expect(row).toBeAttached()
  await page.evaluate((id) => {
    document.querySelector(`#cluster-list [data-cluster-id="${CSS.escape(id)}"]`)?.click()
  }, picked.point.id)
  expect(await page.evaluate(() => window.__nadocTest.getCanonicalSelection()))
    .toEqual(picked.selection)
  await page.evaluate(() => window.__nadocTest.setRepresentation('beads'))
  // Re-resolve tint after a representation change, using this scaffold-only
  // fixture's bead representation (it has no duplex cylinder geometry).
  await expect.poll(() => page.evaluate(() => {
    let tinted = 0
    window.__nadocTest.scene.traverse(mesh => {
      if (!mesh.isMesh || mesh.material?.visible === false) return
      for (let parent = mesh; parent; parent = parent.parent) if (!parent.visible) return
      const attr = mesh.geometry.getAttribute('instanceSelection')
      if (attr) for (let i = 0; i < (mesh.isInstancedMesh ? mesh.count : attr.count); i++) tinted += attr.getX(i) > 0
    })
    return tinted > 0
  })).toBe(true)
  if (process.env.NADOC_SELECTION_EVIDENCE)
    await page.locator('#canvas').screenshot({ path: path.join(process.env.NADOC_SELECTION_EVIDENCE, 'desktop-selected-beads.png') })
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  expect(await page.evaluate(() => window.__nadocTest.getCanonicalSelection())).toEqual(picked.selection)
  expect(errors, errors.join("\n")).toEqual([])
})
