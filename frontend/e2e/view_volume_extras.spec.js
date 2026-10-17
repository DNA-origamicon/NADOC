import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Only the imported __e2e__ copy can persist; global teardown removes its design
// and revision store. Pixel buffers stay in memory; no captures are written.
const design = JSON.parse(readFileSync(new URL('../../Examples/2hb_xover_atoms_test.nadoc', import.meta.url)))
design.id = 'e2e-volume-extras'; design.metadata.name = '__e2e__volume-extras'

test('all volume representations retain their supported crossover-extra geometry', async ({ page }) => {
  test.setTimeout(150000)
  await page.goto('/?doc=e2e-volume-extras')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js')
    await api.importDesign(JSON.stringify(design)); await api.getGeometry()
  }, design)
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const api = await import('/src/api/client.js')
    const { initViewVolumeDisplays } = await import('/src/scene/view_volume_displays.js')
    const { segmentsForKeys } = await import('/src/scene/view_volumes.js')
    const { filterAtomData } = await import('/src/scene/atom_filter.js')
    const store = window.__nadocTest.store, state = store.getState()
    const response = await fetch('/api/design/atomistic', { headers: { 'X-NADOC-Doc': api.captureViewVolumeContext().docId } })
    if (!response.ok) throw new Error(`Atoms: ${response.status}`)
    const atoms = await response.json()
    const keys = [...new Set(state.currentGeometry.map(n => `${n.helix_id}:${n.bp_index}`))]
    const scene = new THREE.Scene(); scene.add(new THREE.AmbientLight(0xffffff, 3))
    const displays = initViewVolumeDisplays({ scene, store, api, ensureAtoms: async () => atoms,
      onError: error => { throw error } })
    const renderer = new THREE.WebGLRenderer({ antialias: false }); renderer.setSize(128, 128)
    const target = new THREE.WebGLRenderTarget(128, 128)
    const camera = new THREE.OrthographicCamera(-3, 3, 3, -3, .01, 100)
    const pixels = () => {
      renderer.setRenderTarget(target); renderer.render(scene, camera)
      const bytes = new Uint8Array(128 * 128 * 4)
      renderer.readRenderTargetPixels(target, 0, 0, 128, 128, bytes)
      return bytes.reduce((sum, value, i) => sum + (i % 4 !== 3 && value > 0 ? 1 : 0), 0)
    }
    const result = {}
    try {
      for (const representation of ['full', 'beads', 'cylinders', 'vdw', 'ballstick', 'stick', 'surface']) {
        await displays.update([{ id: 'v', representation, keys, segments: segmentsForKeys(keys), opacity: 1 }])
        const entry = displays.entries.get('v')
        if (!entry.ready) throw new Error(`${representation} did not finish`)
        if (entry.extras) {
          // Isolate the actual volume's insert meshes to rule out duplex pixels.
          for (const child of entry.root.children) child.visible = child === entry.extras.group
          const bounds = new THREE.Box3().setFromObject(entry.extras.group), center = bounds.getCenter(new THREE.Vector3())
          camera.position.copy(center).add(new THREE.Vector3(0, -10, 5)); camera.lookAt(center)
          const shown = pixels()
          entry.extras.group.visible = false
          const hidden = pixels()
          result[representation] = { shown, hidden, beads: entry.extras.beadsMesh.count,
            slabsVisible: entry.extras.slabsMesh.visible }
        } else if (representation === 'cylinders') {
          result[representation] = { extras: !!entry.root.getObjectByName('xoverExtraBeads') }
        } else {
          const bounds = new THREE.Box3().setFromObject(entry.root), center = bounds.getCenter(new THREE.Vector3())
          camera.position.copy(center).add(new THREE.Vector3(0, -15, 5)); camera.lookAt(center)
          result[representation] = { shown: pixels(), extraAtoms: filterAtomData(atoms, new Set(keys), true).atoms.filter(a => a.crossover_id != null).length }
        }
      }
    } finally { displays.dispose(); target.dispose(); renderer.dispose() }
    return result
  })
  // Exercise the normal volume manager with a coarse global representation.
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const store = window.__nadocTest.store
    window.__nadocTest.setRepresentation('cylinders')
    const volumes = [{ id: 'extras-ui', name: 'Extras', shape: 'box',
      min_corner: [-100,-100,-100], max_corner: [100,100,100],
      representation: 'full', coloring: 'strand', opacity: 1, enabled: true }]
    await api.saveViewVolumes(volumes)
    store.setState({ currentDesign: { ...store.getState().currentDesign, view_volumes: volumes } })
  })
  for (const rep of ['full', 'beads']) {
    await page.evaluate(rep => {
      const select = document.querySelector('.view-volume-representation')
      select.value = rep; select.dispatchEvent(new Event('change', { bubbles: true }))
    }, rep)
    await expect.poll(() => page.evaluate(() => {
      let count = 0
      for (const root of window.__nadocTest.scene.children.filter(o => o.name.startsWith('view-volume-display-'))) {
        root.traverseVisible(o => {
          if (o.name === 'xoverExtraBeads') for (let i = 0; i < o.count; i++) {
            if (o.geometry.attributes.instanceAlpha.getX(i) > 0) count++
          }
        })
      }
      return count
    })).toBeGreaterThan(0)
  }
  console.log('crossover-extra representation audit', JSON.stringify(result))
  for (const rep of ['full', 'beads']) {
    expect(result[rep].beads).toBeGreaterThan(0)
    expect(result[rep].shown).toBeGreaterThan(20)
    expect(result[rep].hidden).toBe(0)
    expect(result[rep].slabsVisible).toBe(rep === 'full')
  }
  expect(result.cylinders.extras).toBe(false)
  for (const rep of ['vdw', 'ballstick', 'stick', 'surface']) {
    expect(result[rep].extraAtoms).toBeGreaterThan(0)
    expect(result[rep].shown).toBeGreaterThan(20)
  }
})
