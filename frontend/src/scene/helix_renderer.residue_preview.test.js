import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'
import { dnaRecord } from '../test-helpers/part_dna_comparison.js'

it('updates only moved residue connectors, preserving rigid poses, colors and cancellation', () => {
  const records = Array.from({ length: 100 }, (_, i) => ({ ...dnaRecord(i), is_three_prime: i === 99 }))
  const scene = new THREE.Scene()
  const ctrl = buildHelixObjects(records, { helices: [], strands: [{ id: 's', strand_type: 'scaffold', domains: [] }] }, scene)
  const connectors = scene.getObjectByName('slabBackboneConnectors')
  const original = connectors.instanceMatrix.array.slice()
  const infos = [7, 8].map(bp_index => ctrl.residueTransformInfo({ helix_id: 'h', bp_index, direction: 'FORWARD' }))
  const write = vi.spyOn(connectors, 'setMatrixAt')
  const delta = new THREE.Matrix4().makeRotationZ(.7).setPosition(3, 4, 5)
  try {
    for (const info of infos) ctrl.applyResidueTransformMatrix(info, delta)
    expect(write).toHaveBeenCalledTimes(2)
    expect(write.mock.calls.map(call => call[0])).toEqual([7, 8])
    for (let i = 0; i < records.length; i++) {
      const expected = new THREE.Matrix4().fromArray(original, i * 16)
      if (i === 7 || i === 8) expected.premultiply(delta)
      const actual = new THREE.Matrix4(); connectors.getMatrixAt(i, actual)
      if (i !== 7 && i !== 8) expect(actual.elements).toEqual(expected.elements)
      // Cylinder roll is re-derived from its axis; the physical attachment
      // endpoints, rather than arbitrary roll around that axis, must agree.
      for (const y of [-.5, .5]) {
        const a = new THREE.Vector3(0, y, 0).applyMatrix4(actual)
        const b = new THREE.Vector3(0, y, 0).applyMatrix4(expected)
        expect(a.distanceTo(b)).toBeLessThan(1e-5)
      }
    }
    const slab = infos[0].slab, color = new THREE.Color(0xff00ff), actualColor = new THREE.Color()
    slab.instMesh.setColorAt(slab.id, color)
    for (const info of infos) ctrl.applyResidueTransformMatrix(info, new THREE.Matrix4())
    expect(write).toHaveBeenCalledTimes(4)
    expect(connectors.instanceMatrix.array).toEqual(original)
    connectors.getColorAt(slab.connectorId, actualColor)
    expect(actualColor.getHex()).toBe(color.getHex())
  } finally {
    write.mockRestore()
    scene.traverse(node => {
      if (node.geometry && !node.geometry.userData?.shared) node.geometry.dispose()
      for (const material of Array.isArray(node.material) ? node.material : node.material ? [node.material] : []) material.dispose()
      if (node.isInstancedMesh) node.dispose()
    })
  }
})
