import { expect, it } from 'vitest'
import * as THREE from 'three'
import { buildAuditFullLayer } from './molecular_placement_audit.js'
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
