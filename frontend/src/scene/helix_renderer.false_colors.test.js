import { afterEach, expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'

// False-colour overlays (flex/RMSF map, staple Tm, length heatmap) must survive
// the selection highlight/restore cycle, which writes setEntryColor(e, C_SEL) and
// later setEntryColor(e, e.defaultColor).
let scene
afterEach(() => {
  scene?.traverse(object => {
    if (object.geometry && !object.geometry.userData?.shared) object.geometry.dispose()
    for (const m of Array.isArray(object.material) ? object.material : object.material ? [object.material] : []) m.dispose()
  })
  scene = null
})

function build() {
  const geometry = [0, 1].map(bp => ({
    helix_id: 'h', bp_index: bp, direction: 'FORWARD', copy_k: 0,
    strand_id: 's', strand_type: 'staple', domain_index: 0,
    backbone_position: [bp, 0, 0], base_position: [bp, .5, 0],
    placement_source: 'native-full-o5-v1', slab_position: [bp, .67, 0],
    slab_quaternion: [0, Math.SQRT1_2, Math.SQRT1_2, 0], base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1],
  }))
  scene = new THREE.Scene()
  const design = { helices: [], strands: [{ id: 's', strand_type: 'staple', domains: [] }] }
  return buildHelixObjects(geometry, design, scene)
}
const hexOf = (entry) => { const c = new THREE.Color(); entry.instMesh.getColorAt(entry.id, c); return c.getHex() }

it('a scalar (flex) map survives selecting and deselecting a strand', () => {
  const ctrl = build()
  const [a, b] = ctrl.backboneEntries
  const native = a.defaultColor
  ctrl.applyScalarColors({ 'h:0:FORWARD:0': 0xff0000, 'h:1:FORWARD:0': 0x00ff00 })
  // selection highlight, then restore
  ctrl.setEntryColor(a, 0xffffff)
  expect(hexOf(a)).toBe(0xff0000)
  ctrl.setEntryColor(a, a.defaultColor)
  ctrl.setEntryColor(b, b.defaultColor)
  expect(hexOf(a)).toBe(0xff0000)
  expect(hexOf(b)).toBe(0x00ff00)
  ctrl.clearScalarColors()
  expect(hexOf(a)).toBe(native)
})

it('colour writes under an overlay become the colour revealed when it clears', () => {
  const ctrl = build()
  const [a] = ctrl.backboneEntries
  const [slab] = ctrl.slabEntries
  ctrl.applyScalarColors({ 'h:0:FORWARD:0': 0xff0000 })
  ctrl.setStrandColor('s', 0x123456)
  expect(hexOf(a)).toBe(0xff0000)
  expect(hexOf(slab)).toBe(0xff0000)
  ctrl.clearScalarColors()
  expect(hexOf(a)).toBe(0x123456)
  expect(hexOf(slab)).toBe(0x123456)
  const conn = new THREE.Color()
  slab.connectorMesh.getColorAt(slab.connectorId, conn)
  expect(conn.getHex()).toBe(0x123456)
})

it('named layers stack and clear independently', () => {
  const ctrl = build()
  const [a] = ctrl.backboneEntries
  const native = a.defaultColor
  ctrl.paintFalseColor('stapleTemperature', a, 0x0000ff)
  ctrl.applyScalarColors({ 'h:0:FORWARD:0': 0xff0000 })
  expect(hexOf(a)).toBe(0xff0000)
  ctrl.setEntryColor(a, a.defaultColor)
  ctrl.clearScalarColors()
  expect(hexOf(a)).toBe(0x0000ff)
  ctrl.clearFalseColors('stapleTemperature')
  expect(hexOf(a)).toBe(native)
})


it.each(['scalar', 'stapleTemperature', 'lengthHeatmap'])('%s survives selection and display resets on every entry', layer => {
  const ctrl = build()
  const entries = [...ctrl.backboneEntries, ...ctrl.coneEntries, ...ctrl.slabEntries]
  expect(ctrl.coneEntries.length).toBeGreaterThan(0)
  expect(ctrl.slabEntries.length).toBeGreaterThan(0)
  for (const entry of entries) ctrl.paintFalseColor(layer, entry, 0x12ab34)
  const check = () => {
    for (const entry of entries) {
      expect(hexOf(entry)).toBe(0x12ab34)
      if (entry.connectorMesh) {
        expect(hexOf({ instMesh: entry.connectorMesh, id: entry.connectorId })).toBe(0x12ab34)
      }
    }
  }
  for (const entry of entries) ctrl.setEntryColor(entry, 0xffffff)
  check()
  for (const entry of entries) ctrl.setEntryColor(entry, entry.defaultColor)
  check()
  ctrl.setMode('normal')
  check()
  ctrl.setIsolatedStrand('s')
  check()
  ctrl.setIsolatedStrand(null)
  check()
  ctrl.clearFalseColors(layer)
  for (const entry of entries) expect(hexOf(entry)).toBe(entry.defaultColor)
})
