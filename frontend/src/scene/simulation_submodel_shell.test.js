import { it, expect } from 'vitest'
import * as THREE from 'three'
import { createSubmodelShell } from './simulation_submodel_shell.js'

it('draws the rounded Euclidean offset, follows rotation and obeys visibility', () => {
  const scene = new THREE.Scene(), shell = createSubmodelShell(scene)
  const box = { min_corner: [-1,-2,-3], max_corner: [1,2,3], rotation: [0,0,Math.SQRT1_2,Math.SQRT1_2], shell_nm: 1 }
  shell.update(box, true)
  expect(shell.visible()).toBe(true)
  const root = scene.children[0], mesh = root.children[0]
  const positions = mesh.geometry.attributes.position
  for (let i=0; i<positions.count; i++) {
    const p = new THREE.Vector3().fromBufferAttribute(positions,i)
    const distance = Math.hypot(Math.max(Math.abs(p.x)-1,0),Math.max(Math.abs(p.y)-2,0),Math.max(Math.abs(p.z)-3,0))
    expect(distance).toBeCloseTo(1,5)
  }
  expect(root.quaternion.z).toBeCloseTo(Math.SQRT1_2)
  shell.update(box,false); expect(shell.visible()).toBe(false)
  shell.update({...box,shell_nm:0},true); expect(shell.visible()).toBe(false)
  expect(root.children).toHaveLength(0)
  shell.dispose(); expect(scene.children).toHaveLength(0)
})
