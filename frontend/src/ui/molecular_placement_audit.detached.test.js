import { expect, it } from 'vitest'
import * as THREE from 'three'
import { auditMetricRows, buildAuditFullLayer } from './molecular_placement_audit.js'
import { transformComponent } from '../test-helpers/transform_preview.js'

it('Full audit uses distinct candidate poses and exact detector residue selection', () => {
  const original = transformComponent(), candidate = structuredClone(original)
  for (const n of candidate.nucleotides) {
    for (const key of ['backbone_position', 'base_position', 'slab_position']) n[key][0] += 4
    n.helical_site.axis_point[0] += 4
  }
  const data = component => ({ nucleotides: component.nucleotides, helix_axes: component.helix_axes,
    atoms: component.nucleotides.map(n => ({ helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction })) })
  const bundle = { schema: 'nadoc.member-motion-ordering-audit.v1', strand_colors: [],
    nucleotides: original.nucleotides, helix_axes: original.helix_axes,
    current: data(original), candidate: data(candidate) }
  const before = JSON.stringify(bundle), layers = []
  try {
    for (const side of ['current', 'candidate']) {
      const layer = buildAuditFullLayer(new THREE.Scene(), bundle, original.display_topology, { side })
      layers.push(layer)
      const beads = layer.root.getObjectByName('baseSlabs'), matrix = new THREE.Matrix4()
      expect(beads.count).toBe(2)
      beads.getMatrixAt(0, matrix)
      expect(new THREE.Vector3().setFromMatrixPosition(matrix).x)
        .toBeCloseTo(bundle[side].nucleotides[0].slab_position[0], 6)
    }
    const selected = buildAuditFullLayer(new THREE.Scene(), bundle, original.display_topology,
      { side: 'candidate', serials: [1] })
    layers.push(selected)
    expect(selected.root.getObjectByName('baseSlabs').count).toBe(1)
    const matrix = new THREE.Matrix4()
    selected.root.getObjectByName('baseSlabs').getMatrixAt(0, matrix)
    expect(new THREE.Vector3().setFromMatrixPosition(matrix).z)
      .toBeCloseTo(candidate.nucleotides[1].slab_position[2], 6)
    expect(selected.root.getObjectByName('axisLine')).toBeUndefined()
    expect(JSON.stringify(bundle)).toBe(before)
  } finally { for (const layer of layers) layer.dispose() }
})

it('tail audit selects canonical material rather than the atom anchor and reports Full-only motion', () => {
  const original = transformComponent()
  const tail = original.nucleotides[1]
  const bundle = { schema: 'nadoc.member-motion-tail-audit.v1', strand_colors: [],
    candidate: { nucleotides: original.nucleotides, helix_axes: original.helix_axes,
      atoms: [{ ...original.nucleotides[0],
        material_key: `${tail.helix_id}:${tail.bp_index}:${tail.direction}` }] },
    current: { atoms: [] } }
  const layer = buildAuditFullLayer(new THREE.Scene(), bundle, original.display_topology,
    { side: 'candidate', serials: [0] })
  try {
    const matrix = new THREE.Matrix4(), slabs = layer.root.getObjectByName('baseSlabs')
    expect(slabs.count).toBe(1)
    slabs.getMatrixAt(0, matrix)
    expect(new THREE.Vector3().setFromMatrixPosition(matrix).z).toBeCloseTo(tail.slab_position[2], 6)
  } finally { layer.dispose() }
  const diagnostics = { piercing: { n_pierced: 0 }, n_clashes: 0,
    bonds: { max_length_nm: 0.2, n_overstretched: 0 } }
  const rows = auditMetricRows({ ...bundle, provider: { label: 'Tail' },
    current: { diagnostics }, candidate: { diagnostics },
    displacement: { n_displaced: 0, max_nm: 0 },
    full_displacement: { n_displaced: 2, max_nm: 3.2 } })
  expect(rows).toContainEqual(['Displaced Full residues', 2, ''])
  expect(rows).toContainEqual(['Max Full displacement', '3.200 nm', ''])
})
