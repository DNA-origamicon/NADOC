import { expect, it } from 'vitest'
import * as THREE from 'three'
import { createPiercingMarkers } from './piercing_markers.js'

it('renders distinct cyan diamonds, follows live positions, clears and disposes', () => {
  const scene = new THREE.Scene(), layer = createPiercingMarkers(scene)
  const pos = new THREE.Vector3(1, 2, 3), matrix = new THREE.Matrix4()
  const live = new THREE.Vector3(4, 5, 6)
  layer.setEntries([{ pos }, { getPosition: () => live }])
  const mesh = scene.getObjectByName('piercingMarkers')
  expect(scene.children).toHaveLength(1)
  expect(layer.count()).toBe(2)
  expect(mesh.geometry.type).toBe('OctahedronGeometry')
  expect(mesh.material.wireframe).toBe(true)
  expect(mesh.material.color.getHex()).toBe(0x38d9ef)
  pos.set(7, 8, 9); live.set(10, 11, 12); layer.refresh()
  mesh.getMatrixAt(0, matrix)
  expect(new THREE.Vector3().setFromMatrixPosition(matrix).toArray()).toEqual([7, 8, 9])
  mesh.getMatrixAt(1, matrix)
  expect(new THREE.Vector3().setFromMatrixPosition(matrix).toArray()).toEqual([10, 11, 12])
  layer.clear(); expect(mesh.count).toBe(0)
  layer.dispose(); expect(scene.children).toHaveLength(0)
})
