import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'

function specimen(direction, end, length) {
  const five = end === 'five_prime'
  const domain = { helix_id: 'h', start_bp: -5, end_bp: -1, direction }
  if (direction === 'REVERSE') [domain.start_bp, domain.end_bp] = [domain.end_bp, domain.start_bp]
  const anchor = five ? domain.start_bp : domain.end_bp
  const design = {
    helices: [{ id: 'h', label: '0', bp_start: -5, length_bp: 5,
      axis_start: [0, 0, -5 * .334], axis_end: [0, 0, -.334] }],
    strands: [{ id: 'staple', strand_type: 'staple', domains: [domain] }],
    extensions: [{ id: 'tail', strand_id: 'staple', end, sequence: 'A'.repeat(length) }],
    crossovers: [], forced_ligations: [],
  }
  const common = { direction, strand_id: 'staple', strand_type: 'staple',
    base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1] }
  const geometry = Array.from({ length: 5 }, (_, i) => ({
    ...common, helix_id: 'h', bp_index: i - 5, domain_index: 0,
    placement_source: 'native-full-o5-v1',
    backbone_position: [1, 0, (i - 5) * .334], base_position: [.5, 0, (i - 5) * .334],
    slab_position: [.67, 0, (i - 5) * .334], slab_quaternion: [0, Math.SQRT1_2, Math.SQRT1_2, 0],
  }))
  geometry.push(...Array.from({ length }, (_, i) => ({
    ...common, helix_id: '__ext_tail', extension_id: 'tail', bp_index: i,
    domain_index: five ? -1 : 1, placement_source: 'native-full-extension-v1',
    is_modification: false, slab_position: null, slab_quaternion: null,
    backbone_position: [1 + (i + 1) * .68, 0, anchor * .334],
    base_position: [.7 + (i + 1) * .68, 0, anchor * .334],
  })))
  return { design, geometry, anchor }
}

describe('Full representation extension attachment', () => {
  it.each(['FORWARD', 'REVERSE'].flatMap(direction =>
    ['five_prime', 'three_prime'].flatMap(end => [1, 16].map(length => [direction, end, length]))))(
    '%s %s %i-base tail connects its nearest bead to the host', (direction, end, length) => {
      const { design, geometry, anchor } = specimen(direction, end, length)
      const original = structuredClone(geometry)
      const ctrl = buildHelixObjects(geometry, design, new THREE.Scene())
      try {
        const connections = ctrl.getCrossHelixConnections()
        expect(connections).toHaveLength(1)
        const connection = connections[0]
        const [tail, host] = end === 'five_prime'
          ? [connection.fromNuc, connection.toNuc] : [connection.toNuc, connection.fromNuc]
        expect(tail).toMatchObject({ extension_id: 'tail', bp_index: 0 })
        expect(host).toMatchObject({ helix_id: 'h', bp_index: anchor })
        const internal = ctrl.coneEntries.filter(c => c.fromNuc.extension_id && c.toNuc.extension_id)
        expect(internal).toHaveLength(length - 1)
        for (const bond of internal) {
          expect(bond.toNuc.bp_index - bond.fromNuc.bp_index).toBe(end === 'five_prime' ? -1 : 1)
        }
        expect(geometry).toEqual(original)
      } finally {
        ctrl.root.traverse(object => {
          if (!object.geometry?.userData?.shared) object.geometry?.dispose()
          for (const material of [object.material].flat().filter(Boolean)) material.dispose()
        })
        ctrl.root.removeFromParent()
      }
    },
  )
})
