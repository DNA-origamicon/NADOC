import { it, expect } from 'vitest'
import * as THREE from 'three'
import { initDesignRenderer } from './design_renderer.js'

it('refreshes group bounds on display frames without changing the design or selection', () => {
  const scene = new THREE.Scene(), frames = new Set()
  const state = { currentGeometry: [], currentDesign: null, currentHelixAxes: {} }
  const renderer = initDesignRenderer(scene, { getState: () => state, subscribe: () => () => {} }, {
    addFrameCallback: fn => frames.add(fn), removeFrameCallback: fn => frames.delete(fn),
  })
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 1)
  mesh.setMatrixAt(0, new THREE.Matrix4()); scene.add(mesh)
  renderer.setClusterSelectionGroups([[{ instMesh: mesh, id: 0, tint: false }]])
  const corners = scene.getObjectByName('clusterSelectionCorners')
  const before = corners.geometry.attributes.position.getX(0)
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(5, 0, 0))
  mesh.instanceMatrix.needsUpdate = true
  for (const frame of frames) frame()
  expect(corners.geometry.attributes.position.getX(0)).toBeCloseTo(before + 5)
  expect(state.currentDesign).toBeNull()
  renderer.dispose()
  expect(frames.size).toBe(0)
  mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose()
})
