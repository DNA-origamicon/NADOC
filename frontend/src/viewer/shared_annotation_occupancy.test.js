import { it, expect } from 'vitest'
import * as THREE from 'three'
import { createSharedAnnotationOccupancy } from './shared_annotation_occupancy.js'
it('uses moving world-space atom instances, ignores hidden meshes, and bounds work', () => {
  const scene = new THREE.Scene(), mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1), new THREE.MeshBasicMaterial(), 10000)
  for (let i = 0; i < mesh.count; i++) mesh.setMatrixAt(i, new THREE.Matrix4().makeTranslation(i, 0, 0))
  mesh.position.y = 5; scene.add(mesh); scene.updateMatrixWorld(true)
  const capture = createSharedAnnotationOccupancy(scene), first = capture()
  expect(first.length).toBeLessThanOrEqual(4096); expect(first[0]).toMatchObject({ x: 0, y: 5, z: 0 })
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(10, 2, 0))
  expect(capture()[0]).toMatchObject({ x: 10, y: 7, z: 0 })
  mesh.visible = false; expect(capture()).toEqual([])
  mesh.geometry.dispose(); mesh.material.dispose()
})
