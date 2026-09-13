// @vitest-environment jsdom
import { it, expect, vi, afterEach } from 'vitest'
import { initGrapheneDisplayControls } from './graphene_display_controls.js'

afterEach(() => { document.body.innerHTML = ''; localStorage.clear() })
it('changes both renderers and remembers preferences without touching simulation inclusion', () => {
  document.body.innerHTML = '<input id="md-surface-enable" type="checkbox" checked><input id="md-graphene-show" type="checkbox"><select id="md-graphene-representation"><option value="plane">Plane</option><option value="ball">Ball</option><option value="stick">Stick</option></select>'
  const preview = { setDisplay: vi.fn() }, simulation = { setGrapheneDisplay: vi.fn() }
  const inclusion = document.getElementById('md-surface-enable'), onInclude = vi.fn()
  inclusion.addEventListener('change', onInclude)
  const ctrl = initGrapheneDisplayControls({ preview, simulation })
  const show = document.getElementById('md-graphene-show'), rep = document.getElementById('md-graphene-representation')
  show.click(); rep.value = 'stick'; rep.dispatchEvent(new Event('change'))
  expect(preview.setDisplay).toHaveBeenLastCalledWith({ visible: false, representation: 'stick' })
  expect(simulation.setGrapheneDisplay).toHaveBeenLastCalledWith({ visible: false, representation: 'stick' })
  expect(inclusion.checked).toBe(true); expect(onInclude).not.toHaveBeenCalled()
  ctrl.dispose()
  const restored = initGrapheneDisplayControls({ preview, simulation })
  expect(show.checked).toBe(false); expect(rep.value).toBe('stick')
  restored.dispose()
})

it('changes the ion-path membrane in place without resurrecting the design preview', async () => {
  const THREE = await import('three')
  const { initGrapheneNanoporeOverlay } = await import('../scene/graphene_nanopore_overlay.js')
  const { initMdIonPaths } = await import('../scene/md_ion_paths.js')
  document.body.innerHTML = '<input id="md-graphene-show" type="checkbox"><select id="md-graphene-representation"><option value="plane">Plane</option><option value="ball">Ball</option><option value="stick">Stick</option></select>'
  localStorage.setItem('nadoc.grapheneDisplay', JSON.stringify({ visible: true, representation: 'ball' }))
  const scene = new THREE.Scene(), center = new THREE.Vector3(3, 8, -2)
  const preview = initGrapheneNanoporeOverlay(scene)
  const spec = { enabled: true, surface: { dir: [0, 1, 0], positionNm: -5 } }
  preview.update(spec)
  const ionPaths = initMdIonPaths(scene, () => center, {
    onActiveChange: active => preview.setSimulationActive(active, 'ion-paths'),
  })
  const simulation = { setGrapheneDisplay: vi.fn() }
  const ctrl = initGrapheneDisplayControls({ preview, simulation, ionPaths })
  const graphene = Array.from({ length: 6 }, (_, i) => [Math.cos(i * Math.PI / 3) * 0.142, 0, Math.sin(i * Math.PI / 3) * 0.142]).flat()
  const data = { paths: [{ species: 'NA', positions: [0, -1, 0, 0, 1, 0] }],
    origami: { display_transform: new THREE.Matrix4().makeTranslation(3, 8, -2).toArray() }, graphene, pore: { radius_nm: 1, normal: [0, 1, 0] } }
  ionPaths.setData(data)
  const group = scene.getObjectByName('mdIonPaths')
  const path = group.getObjectByName('ionPaths-NA'), average = new THREE.Group()
  scene.add(average)
  expect(group.getObjectByName('Graphene nanopore').userData.grapheneRepresentation).toBe('ball')
  expect(preview.mesh().visible).toBe(false)
  const rep = document.getElementById('md-graphene-representation')
  for (const mode of ['stick', 'plane', 'ball']) {
    rep.value = mode; rep.dispatchEvent(new Event('change'))
    // A repeated solvent "off" and a preview edit must not release the active
    // ion-path owner's suppression, even though the preview mesh is rebuilt.
    preview.setSimulationActive(false)
    preview.update(spec)
    expect(preview.mesh().visible).toBe(false)
    const membrane = group.getObjectByName('Graphene nanopore')
    expect(membrane.userData.grapheneRepresentation).toBe(mode)
    expect(membrane.getWorldPosition(new THREE.Vector3()).toArray()).toEqual([3, 8, -2])
    expect(group.getObjectByName('ionPaths-NA')).toBe(path)
    expect(group.getObjectByName('origamiRmsfAverage')).toBeUndefined()
    expect(membrane.visible).toBe(true)
    expect(group.children.filter(c => c.name === 'Graphene nanopore')).toHaveLength(1)
  }
  const show = document.getElementById('md-graphene-show')
  show.click()
  expect(group.getObjectByName('Graphene nanopore').visible).toBe(false)
  expect(group.getObjectByName('nanoporeAperture').visible).toBe(false)
  expect(preview.mesh().visible).toBe(false)
  expect(average.visible).toBe(true)
  expect(path.visible).toBe(true)
  // Reloading a frame window retains the display preference and scene anchor.
  center.set(20, 20, 20)
  ionPaths.setData(data)
  expect(group.getWorldPosition(new THREE.Vector3()).toArray()).toEqual([3, 8, -2])
  expect(group.getObjectByName('Graphene nanopore').visible).toBe(false)
  ionPaths.clear()
  expect(preview.mesh().visible).toBe(false) // current Show preference wins
  show.click()
  expect(preview.mesh().visible).toBe(true)
  expect(preview.mesh().userData.grapheneRepresentation).toBe('ball')
  expect(group.children).toHaveLength(0)
  ctrl.dispose(); ionPaths.dispose(); preview.dispose()
})
