import { it, expect, vi, afterEach } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initSweepPanel } from './sweep_panel.js'

let panel
function setup() {
  document.body.innerHTML = '<button id="menu-tools-sweep"></button>'
  vi.useFakeTimers()
  const store = createMockStore({ currentDesign: { id: 'part', helices: [], lattice_type: 'SQUARE' } })
  let selection
  const slicePlane = { show: vi.fn(), hide: vi.fn(), setPreviewEnabled: vi.fn(), setExtrudeUiOpen: vi.fn(),
    setSelectedCells: vi.fn(), subscribeSelection: fn => { selection = fn; return vi.fn() } }
  const api = { previewSweep: vi.fn(async () => ({ revision: 7, length_nm: 10, length_bp: 31, path_nm: [[0,0,0],[0,0,10]], points_nm: [[0,0,0],[0,0,10]] })), createSweep: vi.fn(async () => ({})), editFeature: vi.fn(async () => ({})) }
  const scene = new THREE.Scene()
  panel = initSweepPanel({ store, api, slicePlane, scene, extrudePanel: { hide: vi.fn() } })
  return { api, store, slicePlane, scene, selection: cells => selection(cells) }
}
afterEach(() => { panel?.dispose(); vi.useRealTimers(); document.body.innerHTML = '' })

it('previews without mutation, commits one path, and disposes the scene preview', async () => {
  const { api, scene, selection } = setup()
  panel.activate()
  selection([[0,0],[0,1]])
  await vi.advanceTimersByTimeAsync(130)
  expect(api.previewSweep).toHaveBeenCalledWith(expect.objectContaining({ cells: [[0,0],[0,1]], points_nm: [[0,0,0],[0,0,10]] }))
  expect(api.createSweep).not.toHaveBeenCalled()
  expect(document.getElementById('sweep-path').hidden).toBe(true)
  expect(scene.getObjectByName('sweep-control-points').children.length).toBe(0)
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(130)
  expect(document.getElementById('sweep-step').textContent).toContain('2/2')
  expect(document.getElementById('sweep-footprint').hidden).toBe(true)
  expect(document.getElementById('sweep-info').hidden).toBe(false)
  expect(document.getElementById('sweep-total-bp').textContent).toBe('62')
  expect(scene.getObjectByName('sweep-control-points').children.length).toBe(2)
  expect(api.createSweep).not.toHaveBeenCalled()
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(0)
  expect(api.createSweep).toHaveBeenCalledTimes(1)
  expect(panel.isActive()).toBe(false)
  expect(scene.getObjectByName('sweep-control-points').children.length).toBe(0)
})

it('restores points for editing and commits through feature history', async () => {
  const { api } = setup()
  panel.edit({ params: { cells: [[0,0]], plane: 'XY', points_nm: [[0,0,0],[5,3,12]], ligate_adjacent: false } }, 4)
  await vi.advanceTimersByTimeAsync(130)
  expect(document.querySelector('[aria-label="Point X (nm)"]').value).toBe('5')
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(0)
  expect(api.editFeature).toHaveBeenCalledWith(4, expect.objectContaining({ points_nm: [[0,0,0],[5,3,12]], ligate_adjacent: false }))
  expect(api.createSweep).not.toHaveBeenCalled()
})

it('discards an obsolete preview after cancel', async () => {
  const { api, scene, selection } = setup()
  let resolve
  api.previewSweep.mockImplementation(() => new Promise(done => { resolve = done }))
  panel.activate(); selection([[0,0]])
  await vi.advanceTimersByTimeAsync(130)
  panel.hide()
  resolve({ path_nm: [[0,0,0],[0,0,10]], points_nm: [[0,0,0],[0,0,10]], length_nm: 10, length_bp: 31 })
  await vi.advanceTimersByTimeAsync(0)
  expect(scene.getObjectByName('sweep-control-points').children.length).toBe(0)
  expect(panel.isActive()).toBe(false)
})


it('selects an existing start end using the keyed helix-axis store', async () => {
  const { api, store, slicePlane } = setup()
  store.setState({ currentDesign: { id: 'part', helices: [{ id: 'h_XY_0_0', grid_pos: [0,0], axis_start: {x:0,y:0,z:0}, axis_end: {x:0,y:0,z:7} }], lattice_type: 'SQUARE' },
    currentHelixAxes: { h_XY_0_0: { samples: [[0,0,0],[0,0,7]] } } })
  panel.activate()
  const source = document.getElementById('sweep-source')
  source.value = '0'; source.dispatchEvent(new Event('change'))
  await vi.advanceTimersByTimeAsync(130)
  expect(api.previewSweep).toHaveBeenCalledWith(expect.objectContaining({ cells: [[0,0]], source_helix_id: 'h_XY_0_0', source_end: 'start', points_nm: [[0,0,0],[-0,-0,-10]] }))
  expect(slicePlane.setSelectedCells).toHaveBeenLastCalledWith([[0,0]])
})

it('Previous preserves the path and footprint and cannot accidentally commit', async () => {
  const { api, selection, slicePlane } = setup()
  panel.activate(); selection([[0,0], [0,1]])
  await vi.advanceTimersByTimeAsync(130)
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(130)
  const x = document.querySelector('[aria-label="Point X (nm)"]')
  x.value = '9'; x.dispatchEvent(new Event('input'))
  document.getElementById('sweep-cancel').click()
  await vi.advanceTimersByTimeAsync(130)
  expect(slicePlane.setSelectedCells).toHaveBeenLastCalledWith([[0,0],[0,1]])
  expect(document.getElementById('sweep-step').textContent).toContain('1/2')
  expect(document.getElementById('sweep-path').hidden).toBe(true)
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(130)
  expect(x.value).toBe('9')
  expect(api.createSweep).not.toHaveBeenCalled()
})

it('opens the blunt-end source in step one and rejects interior ends', async () => {
  const { store, api } = setup()
  store.setState({ currentDesign: { id: 'part', helices: [{ id: 'h_XY_0_0', grid_pos: [0,0], bp_start: 3, length_bp: 21, axis_start: {x:0,y:0,z:1}, axis_end: {x:0,y:0,z:8} }] } })
  panel.activateFromEnd({ helixId: 'h_XY_0_0', bp: 15, openSide: 1 })
  expect(panel.isActive()).toBe(false)
  panel.activateFromEnd({ helixId: 'h_XY_0_0', bp: 23, openSide: 1 })
  await vi.advanceTimersByTimeAsync(130)
  expect(api.previewSweep).toHaveBeenCalledWith(expect.objectContaining({ source_helix_id: 'h_XY_0_0', source_end: 'end' }))
  expect(document.getElementById('sweep-step').textContent).toContain('1/2')
})

it('updates the local path immediately while a changed point awaits the server', async () => {
  const { api, scene, selection } = setup()
  panel.activate(); selection([[0,0]])
  await vi.advanceTimersByTimeAsync(130)
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(130)
  const geometry = scene.getObjectByName('sweep-geometry')
  expect(geometry.children.length).toBeGreaterThan(0)
  api.previewSweep.mockImplementation(() => new Promise(() => {}))
  const x = document.querySelector('[aria-label="Point X (nm)"]')
  x.value = '4'; x.dispatchEvent(new Event('input'))
  await vi.advanceTimersByTimeAsync(130)
  expect(geometry.children.length).toBeGreaterThan(0)
  expect(scene.getObjectByName('sweep-point-1').position.x).toBe(4)
  const path = scene.getObjectByName('sweep-live-path')
  expect(scene.getObjectByName('sweep-live-preview').visible).toBe(true)
  expect(path.geometry.attributes.position.getX(path.geometry.drawRange.count-1)).toBeCloseTo(4)
  expect(geometry.visible).toBe(false)
  expect(document.getElementById('sweep-apply').disabled).toBe(true)
})

it('refreshes the guarded preview when workspace metadata advances the revision', async () => {
  const { api, selection } = setup()
  panel.activate(); selection([[0,0]])
  await vi.advanceTimersByTimeAsync(130)
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(130)
  api.currentRevisionWatermark = () => 8
  api.previewSweep.mockResolvedValue({revision:8,length_nm:10,length_bp:31})
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(0)
  expect(api.createSweep).toHaveBeenCalledWith(expect.objectContaining({expected_revision:8}))
  expect(api.previewSweep.mock.lastCall[0]).not.toHaveProperty('expected_revision')
})

it('shows downstream conflicts in the live edit preview without disabling Apply', async () => {
  const { api } = setup()
  const response = await api.previewSweep()
  api.previewSweep.mockResolvedValue({...response, edit_warnings:['Review crossover register.']})
  panel.edit({ params: { cells:[[0,0]], plane:'XY', points_nm:[[0,0,0],[0,0,10]], ligate_adjacent:false } }, 0)
  await vi.advanceTimersByTimeAsync(130)
  expect(document.getElementById('sweep-conflicts').textContent).toContain('Review crossover register.')
  expect(document.getElementById('sweep-apply').disabled).toBe(false)
})

it('coalesces input into one local frame and rejects out-of-order server previews', async () => {
  const {api,scene,selection}=setup()
  panel.activate();selection([[0,0]])
  await vi.advanceTimersByTimeAsync(130)
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(130)
  const resolved=await api.previewSweep(), pending=[]
  api.previewSweep.mockImplementation(()=>new Promise(resolve=>pending.push(resolve)))
  const x=document.querySelector('[aria-label="Point X (nm)"]')
  const change=value=>{x.value=String(value);x.dispatchEvent(new Event('input'))}
  change(2);await vi.advanceTimersByTimeAsync(130)
  change(3);change(8);await vi.advanceTimersByTimeAsync(20)
  const live=scene.getObjectByName('sweep-live-path'),attribute=live.geometry.attributes.position
  expect(attribute.getX(live.geometry.drawRange.count-1)).toBeCloseTo(8)
  pending[0]({...resolved,points_nm:[[0,0,0],[2,0,10]]})
  await vi.advanceTimersByTimeAsync(0)
  expect(scene.getObjectByName('sweep-live-preview').visible).toBe(true)
  expect(document.getElementById('sweep-apply').disabled).toBe(true)
  await vi.advanceTimersByTimeAsync(120)
  pending[1]({...resolved,points_nm:[[0,0,0],[8,0,10]]})
  await vi.advanceTimersByTimeAsync(0)
  expect(scene.getObjectByName('sweep-live-preview').visible).toBe(false)
  expect(document.getElementById('sweep-apply').disabled).toBe(false)
  change(9);panel.hide();await vi.advanceTimersByTimeAsync(20)
  expect(scene.getObjectByName('sweep-live-preview').visible).toBe(false)
})


it('moving an attached origin detaches it, and returning to zero does not silently reconnect it', async () => {
  const { api, store } = setup()
  store.setState({ currentDesign: { id: 'part', helices: [{ id: 'h_XY_0_0', grid_pos: [0,0], axis_start: {x:0,y:0,z:0}, axis_end: {x:0,y:0,z:7} }], lattice_type: 'SQUARE' } })
  panel.edit({ params: { cells: [[0,0]], plane: 'XY', source_helix_id: 'h_XY_0_0', source_end: 'end', points_nm: [[0,0,0],[0,0,10]] } }, 1)
  await vi.advanceTimersByTimeAsync(130)
  document.querySelector('[role=option]').click()
  const x = document.querySelector('[aria-label="Point X (nm)"]')
  expect(x.disabled).toBe(false)
  x.value = '4'; x.dispatchEvent(new Event('input'))
  await vi.advanceTimersByTimeAsync(130)
  expect(api.previewSweep).toHaveBeenLastCalledWith(expect.objectContaining({detach_source: true, points_nm: [[4,0,0],[0,0,10]]}), 1)
  x.value = '0'; x.dispatchEvent(new Event('input'))
  await vi.advanceTimersByTimeAsync(130)
  document.getElementById('sweep-apply').click()
  await vi.advanceTimersByTimeAsync(0)
  expect(api.editFeature).toHaveBeenCalledWith(1, expect.objectContaining({detach_source: true, points_nm: [[0,0,0],[0,0,10]]}))
})
