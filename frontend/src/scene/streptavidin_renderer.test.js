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

import { addBiotinMarkers, applyCoatingTransforms } from './streptavidin_renderer.js'
import pockets from '../../../backend/data/proteins/biotin_pockets.json'

it('places one bound marker per occupied pocket and follows each tetramer independently', () => {
  const mesh = new THREE.Mesh()
  mesh.position.set(10, 2, 0); mesh.rotation.z = .7
  const pose = new THREE.Matrix4().makeTranslation(3, 0, 0)
  const particle = { id: 'p', coating: { poses: [0,1].map(() => ({ values: pose.clone().transpose().toArray() })) },
    biotin_dna: [0,1].map(i => ({ strand_id: `s${i}`, chain: 'B', tetramer_index: i })) }
  addBiotinMarkers(mesh, particle, 'full')
  const group = mesh.getObjectByName('biotin-pockets')
  expect(group.visible).toBe(true)
  expect(group.children).toHaveLength(2)
  const rest = group.children.map(c => c.getWorldPosition(new THREE.Vector3()))
  const expected = new THREE.Vector3(...pockets.pockets.B.center).applyMatrix4(pose).applyMatrix4(mesh.matrixWorld)
  expect(rest[0].distanceTo(expected)).toBeLessThan(1e-8)
  const translation = new THREE.Matrix4().makeTranslation(0, 5, 0).transpose().toArray()
  applyCoatingTransforms(mesh, particle, { 'p:strep:1': translation })
  expect(group.children[0].getWorldPosition(new THREE.Vector3()).distanceTo(rest[0])).toBeLessThan(1e-8)
  expect(group.children[1].getWorldPosition(new THREE.Vector3()).distanceTo(rest[1].clone().add(new THREE.Vector3(0,5,0)))).toBeLessThan(1e-8)
  applyCoatingTransforms(mesh, particle)
  expect(group.children[1].getWorldPosition(new THREE.Vector3()).distanceTo(rest[1])).toBeLessThan(1e-8)
  const atomic = new THREE.Mesh(); addBiotinMarkers(atomic, particle, 'vdw')
  expect(atomic.getObjectByName('biotin-pockets').visible).toBe(false)
})
