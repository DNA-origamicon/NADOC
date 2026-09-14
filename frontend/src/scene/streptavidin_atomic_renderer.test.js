import { expect, it } from 'vitest'
import * as THREE from 'three'
import { createStreptavidinAtomicRenderer } from './streptavidin_atomic_renderer.js'

it('renders all imported atoms/bonds with shared buffers and independent rigid poses', () => {
  const parent = new THREE.Group()
  const coating = { protein: { atoms: [
    { name: 'CA', element: 'C', chain_id: 'A', res_name: 'GLY', res_seq: 1, x: 0, y: 0, z: 0 },
    { name: 'N', element: 'N', chain_id: 'A', res_name: 'GLY', res_seq: 1, x: .15, y: 0, z: 0 },
  ], bonds: [[0,1]] }, poses: [0,3].map(x => ({ values: new THREE.Matrix4().makeTranslation(x,0,0).transpose().toArray() })) }
  const renderer = createStreptavidinAtomicRenderer(parent, coating)
  renderer.setMode('ballstick')
  const groups = renderer.root.children
  expect(renderer.atomCount).toBe(4)
  const sphere = groups[0].children.find(c => c.name === 'atomSpheres')
  const copy = groups[1].children.find(c => c.name === 'atomSpheres')
  expect(sphere.instanceMatrix).toBe(copy.instanceMatrix)
  expect(sphere.geometry).toBe(copy.geometry)
  expect(groups[0].children.find(c => c.name === 'atomBonds').count).toBe(1)
  renderer.applyTransforms([new THREE.Matrix4(), new THREE.Matrix4().makeTranslation(0,5,0)])
  const before = groups[1].matrix.clone()
  expect(new THREE.Vector3().setFromMatrixPosition(before).toArray()).toEqual([3,5,0])
  renderer.setMode('stick')
  expect(groups[0].children.map(c => c.name)).toEqual(['atomBonds'])
  expect(groups[1].matrix.equals(before)).toBe(true)
  renderer.setMode('vdw')
  expect(groups[0].children.some(c => c.name === 'atomBonds')).toBe(false)
  expect(groups[0].children.reduce((n,c) => n+c.count, 0)).toBe(2)
  renderer.setMode('full'); expect(renderer.root.visible).toBe(false)
  renderer.setMode('vdw'); expect(renderer.root.visible).toBe(true)
  renderer.dispose(); expect(parent.children).toHaveLength(0)
})
