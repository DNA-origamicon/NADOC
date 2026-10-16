// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { buildPartDnaComparisonLayer } from './part_dna_comparison_layer.js'
import { buildHelixObjects } from './helix_renderer.js'
import * as palette from './helix_renderer/palette.js'
import { dnaComponent, dnaRecord, dnaRow } from '../test-helpers/part_dna_comparison.js'
import { decodeDnaComparisonRecords } from '../features/part_dna_comparison_codec.js'

const owned = []
function build(component) {
  const scene = new THREE.Scene(), layer = buildPartDnaComparisonLayer(component, scene)
  owned.push(layer); return { ...layer, scene }
}
function objects(root) { const values = []; root.traverse(node => { if (node.geometry) values.push(node) }); return values }
function mesh(root, name) { return objects(root).find(node => node.name === name) }
function instance(mesh, index) { const value = new THREE.Matrix4(); mesh.getMatrixAt(index, value); return value }
afterEach(() => { for (const item of owned.splice(0)) item.dispose(); vi.restoreAllMocks() })

describe('isolated complete native DNA scene', () => {
  it('preserves native bead/slab matrices and does not mutate the display packet', () => {
    const component = dnaComponent(), before = JSON.stringify(component), layer = build(component)
    const nativeScene = new THREE.Scene(), data = decodeDnaComparisonRecords(component.nucleotides)
    const native = buildHelixObjects(data, { ...component.display_topology, id: 'test-native-parity' }, nativeScene)
    for (const field of ['backboneEntries', 'slabEntries']) for (const entry of native[field]) {
      const actual = mesh(layer.root, entry.instMesh.name)
      expect(instance(actual, entry.id).elements).toEqual(instance(entry.instMesh, entry.id).elements)
    }
    expect(JSON.stringify(component)).toBe(before)
    for (const node of objects(nativeScene)) {
      if (!node.geometry.userData.shared) node.geometry.dispose()
      node.material.dispose(); if (node.isInstancedMesh) node.dispose()
    }
    palette._resetStapleColorPins('test-native-parity')
  })

  it('uses posed axis segments instead of falling back to straight topology axes', () => {
    const component = dnaComponent(), axis = component.helix_axes[0]
    axis.start = [4, 2, 0]; axis.end = [4, 2, .34]
    axis.segments[0].start = axis.start; axis.segments[0].end = axis.end
    const warn = vi.spyOn(console, 'warn')
    const layer = build(component)
    expect(warn).not.toHaveBeenCalled()
    const axisMeshes = objects(layer.root).filter(node => node.name === 'axisLine')
    expect(axisMeshes.length).toBeGreaterThan(0)
    expect(axisMeshes.some(node => Math.abs(node.position.x - 4) < 1e-8 && Math.abs(node.position.y - 2) < 1e-8)).toBe(true)
  })

  it('draws an explicit native crossover with the unchanged normal line endpoint samples', () => {
    const component = dnaComponent()
    component.display_topology.crossovers = [{ id: 'x', half_a: { helix_id: 'h', index: 0, strand: 'FORWARD' },
      half_b: { helix_id: 'h', index: 1, strand: 'FORWARD' }, extra_bases: null }]
    const layer = build(component), line = mesh(layer.root, 'xoverArcMerged_comparison')
    expect(line.userData.arcCount).toBe(1)
    expect([...line.geometry.attributes.position.array.slice(0, 3)]).toEqual([...new Float32Array(dnaRecord().backbone_position)])
    expect([...line.geometry.attributes.position.array.slice(-3)]).toEqual([...new Float32Array(dnaRecord(1).backbone_position)])
  })

  it('refuses metadata-only ligation absent from native topology and releases the entire incomplete scene', () => {
    const component = dnaComponent(), scene = new THREE.Scene()
    component.display_topology.forced_ligations = [{ id: 'f', three_prime_helix_id: 'h', three_prime_bp: 0,
      three_prime_direction: 'FORWARD', five_prime_helix_id: 'h', five_prime_bp: 0,
      five_prime_direction: 'FORWARD', extra_bases: null, is_periodic_seam: false }]
    const disposed = vi.spyOn(THREE.Material.prototype, 'dispose')
    expect(() => buildPartDnaComparisonLayer(component, scene)).toThrow(/authored ligation/)
    expect(scene.children).toHaveLength(0); expect(disposed).toHaveBeenCalled()
  })

  it('disposes private buffers/instances and reference alpha clones once while retaining native templates and live palette pins', () => {
    const component = dnaComponent()
    component.display_topology.strands[0].is_reference = true
    component.nucleotides = [dnaRow({ ...dnaRecord(), is_reference: true }), dnaRow({ ...dnaRecord(1), is_reference: true })]
    const liveDesign = { id: 'live-palette', strands: [{ id: 'live', strand_type: 'staple' }] }
    const geometry = [{ strand_id: 'live', strand_type: 'staple' }]
    const before = palette.buildStapleColorMap(geometry, liveDesign).get('live')
    const reset = vi.spyOn(palette, '_resetStapleColorPins')
    const layer = build(component), nodes = objects(layer.root)
    const clones = new Set(nodes.filter(n => n._instanceAlpha).map(n => n.geometry))
    expect(clones.size).toBeGreaterThan(0)
    const privateGeometry = new Set(nodes.filter(n => !n.geometry.userData.shared || clones.has(n.geometry)).map(n => n.geometry))
    const shared = new Set(nodes.filter(n => n.geometry.userData.shared && !clones.has(n.geometry)).map(n => n.geometry))
    const ownSpies = [...privateGeometry, ...new Set(nodes.map(n => n.material)), ...nodes.filter(n => n.isInstancedMesh)]
      .map(value => vi.spyOn(value, 'dispose'))
    const sharedSpies = [...shared].map(value => vi.spyOn(value, 'dispose'))
    const sharedMetadata = [...shared].map(value => ({ value, metadata: value.userData }))
    layer.dispose(); layer.dispose()
    for (const spy of ownSpies) expect(spy).toHaveBeenCalledOnce()
    for (const spy of sharedSpies) expect(spy).not.toHaveBeenCalled()
    for (const { value, metadata } of sharedMetadata) {
      expect(value.userData).toBe(metadata)
      expect(metadata.shared).toBe(true)
    }
    expect(reset).toHaveBeenCalledOnce(); expect(typeof reset.mock.calls[0][0]).toBe('symbol')
    expect(palette.buildStapleColorMap(geometry, { ...liveDesign, strands: [{ id: 'added' }, ...liveDesign.strands] }).get('live')).toBe(before)
    palette._resetStapleColorPins('live-palette')
  })

  it('leaves a simultaneously retained normal scene and its shared-template metadata unchanged', () => {
    const component = dnaComponent(), normalScene = new THREE.Scene()
    const normal = buildHelixObjects(decodeDnaComparisonRecords(component.nucleotides),
      { ...component.display_topology, id: 'retained-normal' }, normalScene)
    const held = normal.backboneEntries.map(entry => ({ entry, matrix: instance(entry.instMesh, entry.id).elements,
      geometry: entry.instMesh.geometry, metadata: entry.instMesh.geometry.userData }))
    const spies = [...new Set(held.map(item => item.geometry))].map(value => vi.spyOn(value, 'dispose'))
    try {
      component.display_topology.strands[0].is_reference = true
      component.nucleotides = [dnaRow({ ...dnaRecord(), is_reference: true }), dnaRow({ ...dnaRecord(1), is_reference: true })]
      const comparison = build(component)
      comparison.dispose()
      for (const { entry, matrix, geometry, metadata } of held) {
        expect(instance(entry.instMesh, entry.id).elements).toEqual(matrix)
        expect(entry.instMesh.geometry).toBe(geometry)
        expect(geometry.userData).toBe(metadata)
        expect(metadata.shared).toBe(true)
      }
      for (const spy of spies) expect(spy).not.toHaveBeenCalled()
    } finally {
      for (const node of objects(normalScene)) {
        if (!node.geometry.userData.shared) node.geometry.dispose()
        node.material.dispose(); if (node.isInstancedMesh) node.dispose()
      }
      normalScene.clear(); palette._resetStapleColorPins('retained-normal')
    }
  })
})
