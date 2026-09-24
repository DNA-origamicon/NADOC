import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { createCpdSlabBonds, slabBondEndpoints } from './cpd_slab_bonds.js'
import { installInstanceAlpha, setInstanceAlpha } from './instance_alpha.js'

const design = { photoproduct_junctions: [{ base_key_1: '__xb__:xo:0', base_key_2: '__xb__:xo:1', design_coordinates: { '__xb__:xo:0': {} } }] }
function fixture() {
  const slabs = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 2)
  const a = new THREE.Matrix4().makeScale(0.3, 0.06, 0.7)
  const b = a.clone().setPosition(0, 0, 1.2)
  slabs.setMatrixAt(0, a); slabs.setMatrixAt(1, b)
  const bars = createCpdSlabBonds(design, slabs, p => p.k)
  return { slabs, bars, a, b }
}
const matrixAt = (mesh, index) => { const m = new THREE.Matrix4(); mesh.getMatrixAt(index, m); return m }

describe('Full CPD crosslink bars', () => {
  it('draws two separated bars near slab centers and follows their rigid movement', () => {
    const { slabs, bars, a, b } = fixture()
    expect(bars.mesh.count).toBe(2)
    const original = [0, 1].map(i => matrixAt(bars.mesh, i))
    expect(new THREE.Vector3().setFromMatrixPosition(original[0]).distanceTo(new THREE.Vector3().setFromMatrixPosition(original[1]))).toBeGreaterThan(0.1)
    const move = new THREE.Matrix4().makeTranslation(2, 3, 4).multiply(new THREE.Matrix4().makeRotationZ(0.6))
    slabs.setMatrixAt(0, move.clone().multiply(a)); slabs.setMatrixAt(1, move.clone().multiply(b))
    bars.sync()
    for (let i = 0; i < 2; i++) {
      const expected = new THREE.Vector3().setFromMatrixPosition(original[i]).applyMatrix4(move)
      expect(new THREE.Vector3().setFromMatrixPosition(matrixAt(bars.mesh, i)).distanceTo(expected)).toBeLessThan(1e-6)
    }
    expect(slabBondEndpoints(a, b)[0][0].z).toBeCloseTo(0)
    expect(slabBondEndpoints(a, b)[0][1].z).toBeCloseTo(1.2)
  })
  it('honors representation visibility and hidden/faded endpoints', () => {
    const { slabs, bars } = fixture()
    bars.sync(false); expect(bars.mesh.visible).toBe(false)
    bars.sync(true); expect(bars.mesh.visible).toBe(true)
    installInstanceAlpha(slabs); setInstanceAlpha(slabs, 1, 0)
    bars.sync(); expect(bars.mesh._instanceAlpha.getX(0)).toBe(0)
    setInstanceAlpha(slabs, 1, 0.3); bars.sync()
    expect(bars.mesh._instanceAlpha.getX(1)).toBeCloseTo(0.3)
    slabs.visible = false; bars.sync(); expect(bars.mesh.visible).toBe(false)
  })
  it('does not draw unresolved or unconverted products', () => {
    const { slabs } = fixture()
    expect(createCpdSlabBonds(design, slabs, () => null)).toBeNull()
    expect(createCpdSlabBonds({}, slabs, () => 0)).toBeNull()
  })
})
