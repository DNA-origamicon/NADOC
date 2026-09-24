import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Import a copy with a test-owned name/id. Autosaves and revision stores use the
// __e2e__ prefix and global teardown; no production files are edited.
const design = JSON.parse(readFileSync(new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)))
design.id = 'e2e-volume-colors'; design.metadata.name = '__e2e__volume-colors'

test('volume coloring, hull windows, sharing, and current-representation overlay defaults', async ({ page }) => {
  test.setTimeout(150000)
  page.setDefaultTimeout(15000)
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=e2e-volume-colors')
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js')
    await api.importDesign(JSON.stringify(design)); await api.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('right-panel')?.classList.remove('locked-inactive', 'hidden')
    document.getElementById('right-tab-strip')?.classList.remove('locked-inactive', 'hidden')
  }, design)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length ?? 0)).toBeGreaterThan(0)
  await page.evaluate(() => document.querySelector('.right-tab-btn[data-tab="visualization"]').click())
  await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.add())
  await expect(page.locator('.view-volume-coloring')).toHaveCount(1)
  await page.evaluate(() => { const select = document.querySelector('.view-volume-coloring'); select.value = 'base'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  const colors = () => page.evaluate(() => {
    const group = window.__nadocTest.scene.children.find(o => o.name.startsWith('view-volume-display-'))
    const colors = []
    group?.traverse(o => { if (o.name === 'backboneSpheres' && o.instanceColor) colors.push(...o.instanceColor.array) })
    return colors
  })
  await expect.poll(async () => (await colors()).length).toBeGreaterThan(0)
  const baseColors = await colors()
  await page.evaluate(() => window.__nadocTest.store.setState({ coloringMode: 'cluster' }))
  expect(await colors()).toEqual(baseColors)
  expect(await page.evaluate(() => window.__NADOC_VIEW_VOLUMES__.volumes()[0].coloring)).toBe('base')

  await page.evaluate(() => window.__nadocTest.setRepresentation('hull-prism'))
  const countCutouts = () => page.evaluate(() => {
    let count = 0
    window.__nadocTest.scene.traverseVisible(o => { if (o.material?.userData?.hullCutouts?.length) count++ })
    return count
  })
  await expect.poll(countCutouts).toBeGreaterThan(0)
  const roundTrip = await page.evaluate(async () => {
    const { prepareScene, loadPreparedScene } = await import('/src/viewer/prepared_scene.js')
    const scene = window.__nadocTest.scene
    const bytes = prepareScene({ scene, camera: { position: [10,10,40], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } })
    const guest = await loadPreparedScene(bytes)
    const version = guest.data.version; guest.dispose(); return version
  })
  expect(roundTrip).toBe(6)
  await page.evaluate(() => document.querySelector('.view-volume-enabled-toggle').click())
  await expect.poll(countCutouts).toBe(0)
  await page.evaluate(() => document.querySelector('.view-volume-enabled-toggle').click())
  await expect.poll(countCutouts).toBeGreaterThan(0)

  await page.evaluate(() => window.__nadocTest.setRepresentation('oxdna'))
  await page.evaluate(() => document.querySelector('.mo-count-btn[data-count="3"]').click())
  await expect(page.locator('.mo-layer-row[data-ready="true"]')).toHaveCount(3)
  expect(await page.locator('.mo-representation').evaluateAll(selects => selects.map(s => s.value))).toEqual(['oxdna', 'cylinders', 'cylinders'])
  expect(errors).toEqual([])
})

test('a hull aperture reveals a completely enclosed volume and survives sharing', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await page.goto('/viewer.html?test=1')
  const pixels = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { applyHullCutouts, hullCutoutSpec } = await import('/src/scene/hull_volume_cutouts.js')
    const { prepareScene, loadPreparedScene } = await import('/src/viewer/prepared_scene.js')
    const scene = new THREE.Scene(), material = new THREE.MeshBasicMaterial({ color: 0x00ff00 })
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(6,6,6), material))
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(.8,16,16), new THREE.MeshBasicMaterial({ color: 0xff0000 })))
    const camera = new THREE.PerspectiveCamera(55,1,.1,100); camera.position.z = 10; camera.lookAt(0,0,0)
    const renderer = window.__preparedViewer.runtime.renderer, target = new THREE.WebGLRenderTarget(32,32)
    const pixel = root => { renderer.setRenderTarget(target); renderer.render(root, camera); const bytes = new Uint8Array(4); renderer.readRenderTargetPixels(target,16,16,1,1,bytes); renderer.setRenderTarget(null); return [...bytes] }
    const before = pixel(scene)
    applyHullCutouts(material, hullCutoutSpec([{ min_corner: [-1,-1,-1], max_corner: [1,1,1] }]))
    const after = pixel(scene)
    applyHullCutouts(material, []); const disabled = pixel(scene)
    applyHullCutouts(material, hullCutoutSpec([{ min_corner: [4,-1,-1], max_corner: [6,1,1] }]))
    const moved = pixel(scene)
    applyHullCutouts(material, hullCutoutSpec([{ min_corner: [-1,-1,-1], max_corner: [1,1,1] }]))
    const guest = await loadPreparedScene(prepareScene({ scene, camera: { position: [0,0,10], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } }))
    const shared = pixel(guest.scene)
    guest.dispose(); target.dispose(); scene.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
    return { before, after, disabled, moved, shared }
  })
  expect(pixels.before[1]).toBeGreaterThan(200); expect(pixels.before[0]).toBeLessThan(10)
  expect(pixels.after[0]).toBeGreaterThan(200); expect(pixels.after[1]).toBeLessThan(10)
  expect(pixels.disabled).toEqual(pixels.before); expect(pixels.moved).toEqual(pixels.before)
  expect(pixels.shared).toEqual(pixels.after)
  expect(errors).toEqual([])
})
