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

it('masks deleted columns in an assembly base layer instead of leaving cylinder slivers', async () => {
  const store = createMockStore({ currentDesign: { helices: [], strands: [] }, currentGeometry: [] })
  const scene = new THREE.Scene(), displays = initViewVolumeDisplays({ scene, store, api: {} })
  // Column 1 has no nucleotide. It is covered by a heavy volume, while 0 and 2
  // belong to the surrounding cylinder base layer. Absence from the mask means
  // global cylinders in the helix renderer, so it must be explicitly hidden.
  await displays.update([{ id: 'base', representation: 'cylinders', keys: ['h:0', 'h:2'], allColumnKeys: ['h:0', 'h:1', 'h:2'], opacity: 1 }])
  const mask = displays.entries.get('base').columns
  expect(mask.get('h:0')).toBe('cylinders')
  expect(mask.get('h:1')).toBe('surface')
  expect(mask.get('h:2')).toBe('cylinders')
  displays.dispose()
})

it('exact nucleotide membership excludes a complementary base and dangling bonds', async () => {
  const store = createMockStore({ currentDesign: { strands: [] }, currentGeometry: [] })
  const display = initViewVolumeDisplays({ scene: new THREE.Scene(), store, api: {}, ensureAtoms: async () => ({
    atoms: [...atoms.atoms, { ...atoms.atoms[0], serial: 1, direction: 'REVERSE' }], bonds: [[0,1]],
  }) })
  await display.update([{ id: 'zoom', representation: 'ballstick', keys: ['h:0'], baseKeys: ['h:0:FORWARD'], opacity: 1 }])
  const found = []
  display.entries.get('zoom').renderer.visitAtoms(a => found.push(a))
  expect(found).toHaveLength(1)
  expect(found[0].direction).toBe('FORWARD')
  display.dispose()
})

it('renders exact extension and linker bases even when their owning domains are absent', async () => {
  const geometry = ['__ext_tail', '__lnk__bridge'].map((helix_id, index) => ({
    helix_id, strand_id: index ? '__lnk__bridge__s' : 's', strand_type: 'staple', domain_index: -1,
    bp_index: 0, direction: 'FORWARD', backbone_position: [index * 3,0,0], base_position: [index * 3,1,0],
    base_normal: [0,1,0], axis_tangent: [0,0,1], base: 'T',
    placement_source: index ? 'native-full-o5-v1' : 'native-full-extension-v1',
    extension_id: index ? undefined : 'tail', is_modification: false,
    slab_position: index ? [3,.67,0] : null, slab_quaternion: index ? [0,0,0,1] : null,
  }))
  const store = createMockStore({ currentDesign: { helices: [], strands: [{ id: 's', domains: [], strand_type: 'staple' }] }, currentGeometry: geometry })
  const display = initViewVolumeDisplays({ scene: new THREE.Scene(), store, api: {} })
  const keys = geometry.map(n => `${n.helix_id}:0`)
  for (const representation of ['full', 'beads', 'cylinders']) {
    await display.update([{ id: 'zoom', representation, keys, baseKeys: keys.map(k => `${k}:FORWARD`), opacity: 1 }])
    const entry = display.entries.get('zoom')
    expect(entry.cg.backboneEntries).toHaveLength(2)
    expect(entry.columns.get('__ext_tail:0')).toBe('full')
    expect(entry.columns.get('__lnk__bridge:0')).toBe('full')
  }
  display.dispose()
})

it('does not connect disjoint selected bases when the source adjacency omits that bond', async () => {
  const geometry = [0, 4].map(bp_index => ({
    helix_id: 'h', bp_index, direction: 'FORWARD', strand_id: 's', strand_type: 'staple', domain_index: 0,
    placement_source: 'native-full-o5-v1', backbone_position: [bp_index,0,0], base_position: [bp_index,.5,0],
    base_normal: [0,1,0], axis_tangent: [0,0,1], slab_position: [bp_index,.67,0], slab_quaternion: [0,0,0,1],
  }))
  const store = createMockStore({ currentDesign: { helices: [], strands: [{ id: 's', domains: [] }] }, currentGeometry: geometry })
  const display = initViewVolumeDisplays({ scene: new THREE.Scene(), store, api: {} })
  await display.update([{ id: 'zoom', representation: 'full', keys: ['h:0', 'h:4'], baseKeys: ['h:0:FORWARD', 'h:4:FORWARD'], backbonePairs: new Set(), opacity: 1 }])
  expect(display.entries.get('zoom').cg.backboneEntries).toHaveLength(2)
  expect(display.entries.get('zoom').cg.coneEntries).toHaveLength(0)
  display.dispose()
})

it('keeps strand-local colors visible while the strand remains selected', async () => {
  const store = createMockStore({ currentDesign: { strands: [] }, currentGeometry: [], strandColors: { s: 0xff0000 } })
  const displays = initViewVolumeDisplays({ scene: new THREE.Scene(), store, api: {}, ensureAtoms: async () => atoms })
  const layer = { id: 's', strandId: 's', representation: 'ballstick', coloring: 'strand', keys: ['h:0'], baseKeys: ['h:0:FORWARD'], opacity: 1 }
  await displays.update([layer])
  const entry = displays.entries.get('s')
  const before = color(entry.root)
  entry.renderer.highlight({ strandIds: ['s'] })
  expect(color(entry.root)).toBe(before)
  await displays.update([{ ...layer, coloring: 'cpk' }])
  const cpk = color(entry.root)
  expect(cpk).not.toBe(before)
  entry.renderer.highlight({ strandIds: ['s'] })
  expect(color(entry.root)).toBe(cpk)
  displays.dispose()
})

it('allows an earlier visibility subscriber to repaint during document teardown', async () => {
  const store = createMockStore({ currentDesign: { strands: [] }, currentGeometry: [] })
  let displays
  // Visibility is registered before the display owner in main.js and repaints
  // synchronously when the document is cleared, before our cleanup subscriber.
  store.subscribe(() => displays.repaint())
  const scene = new THREE.Scene()
  displays = initViewVolumeDisplays({ scene, store, api: {}, ensureAtoms: async () => atoms })
  await displays.update([{ id: 's', strandId: 's', representation: 'ballstick', keys: ['h:0'], opacity: 1 }])
  expect(scene.children.length).toBe(1)
  expect(() => store.setState({ currentDesign: null, currentGeometry: null })).not.toThrow()
  expect(scene.children).toEqual([])
  displays.dispose()
})
