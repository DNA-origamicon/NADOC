import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { initViewVolumeDisplays } from './view_volume_displays.js'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const atoms = { atoms: [{ serial: 0, element: 'C', strand_id: 's', helix_id: 'h', bp_index: 0, direction: 'FORWARD', x: 0, y: 0, z: 0 }], bonds: [] }
const color = root => {
  let result
  root.traverse(o => { if (o.isInstancedMesh && o.instanceColor && o.count) { const c = new THREE.Color(); o.getColorAt(0, c); result = c.getHex() } })
  return result
}
it('keeps overlapping atom layers independently colored and disposes only removed layers', async () => {
  const store = createMockStore({ currentDesign: { strands: [{ id: 's', strand_type: 'staple', domains: [] }] }, currentGeometry: [], strandColors: { s: 0xff0000 } })
  const scene = new THREE.Scene(), displays = initViewVolumeDisplays({ scene, store, api: {}, ensureAtoms: async () => atoms })
  const a = { id: 'a', representation: 'vdw', coloring: 'strand', keys: ['h:0'], opacity: .4 }
  const b = { ...a, id: 'b', coloring: 'cpk', opacity: .8 }
  await displays.update([a,b])
  const red = scene.children[0], cpk = scene.children[1], cpkColor = color(cpk)
  expect(color(red)).toBe(0xff0000); expect(cpkColor).not.toBe(0xff0000)
  const global = initAtomisticRenderer(new THREE.Scene())
  global.setColorMode('strand', new Map([['s', 0x0000ff]]))
  store.setState({ coloringMode: 'cpk' })
  await displays.update([a,b])
  expect(scene.children[0]).toBe(red); expect(color(red)).toBe(0xff0000); expect(color(cpk)).toBe(cpkColor)
  await displays.update([b]); expect(scene.children).toEqual([cpk])
  displays.dispose(); global.dispose(); expect(scene.children).toEqual([])
})
it('drops stale surface completions after removing a volume', async () => {
  let finish
  const store = createMockStore({ currentDesign: { strands: [] }, currentGeometry: [] })
  const scene = new THREE.Scene(), displays = initViewVolumeDisplays({ scene, store, ensureAtoms: async () => atoms,
    api: { getRegionSurface: () => new Promise(resolve => { finish = resolve }) } })
  const pending = displays.update([{ id: 'v', representation: 'surface', keys: ['h:0'], segments: [], opacity: 1 }])
  await displays.update([]); finish({ vertices: [], faces: [] }); await pending
  expect(scene.children).toEqual([]); displays.dispose()
})

it('keeps overlapping surfaces colored independently without rebuilding on global color changes', async () => {
  const store = createMockStore({ currentDesign: { strands: [{ id: 's', strand_type: 'staple', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 1, direction: 'FORWARD' }] }],
    cluster_transforms: [{ id: 'c', helix_ids: ['h'], color: '#0000ff' }] }, currentGeometry: [], strandColors: { s: 0xff0000 } })
  const mesh = { vertices: [0,0,0, 1,0,0, 0,1,0], faces: [0,1,2], vertex_strand_index_table: ['s'], vertex_strand_index: [0,0,0] }
  const api = { getRegionSurface: vi.fn(async () => mesh) }, scene = new THREE.Scene()
  const displays = initViewVolumeDisplays({ scene, store, api })
  const a = { id: 'a', representation: 'surface', coloring: 'strand', opacity: .4, keys: ['h:0'], segments: [] }
  const b = { ...a, id: 'b', coloring: 'cluster', opacity: .8 }
  await displays.update([a,b])
  const surface = id => displays.entries.get(id).renderer.getMesh()
  expect([...surface('a').geometry.attributes.color.array.slice(0,3)]).toEqual([1,0,0])
  expect([...surface('b').geometry.attributes.color.array.slice(0,3)]).toEqual([0,0,1])
  store.setState({ coloringMode: 'cpk' }); await displays.update([a,b])
  expect(api.getRegionSurface).toHaveBeenCalledTimes(2)
  expect(surface('a').material.opacity).toBe(.4); expect(surface('b').material.opacity).toBe(.8)
  expect([...surface('a').geometry.attributes.color.array.slice(0,3)]).toEqual([1,0,0])
  displays.dispose()
})
