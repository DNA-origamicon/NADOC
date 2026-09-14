import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { addStreptavidinCoating } from './streptavidin_renderer.js'

describe('nanoparticle-local protein rendering', () => {
  it('instances PDB chain traces and follows parent translation and rotation', () => {
    const mesh = new THREE.Mesh()
    const atoms = ['A','B','C','D'].flatMap((chain_id, n) => [0,1,2].map(i => ({ name: 'CA', chain_id, x:i*.38, y:n, z:0 })))
    const pose = new THREE.Matrix4().makeTranslation(3,0,0)
    addStreptavidinCoating(mesh, { protein: { atoms }, poses: [{ values: pose.clone().transpose().toArray() }] })
    const group = mesh.children[0]
    expect(group.userData.tetramerCount).toBe(1)
    expect(group.children).toHaveLength(4)
    const instance = group.children[0], local = new THREE.Matrix4()
    instance.getMatrixAt(0, local)
    mesh.position.set(10,0,0); mesh.rotation.z = Math.PI/2
    mesh.updateMatrixWorld(true)
    const position = new THREE.Vector3().setFromMatrixPosition(local).applyMatrix4(instance.matrixWorld)
    expect(position.x).toBeCloseTo(10)
    expect(position.y).toBeCloseTo(3)
    group.traverse(obj => { obj.geometry?.dispose(); obj.material?.dispose() })
  })
})
