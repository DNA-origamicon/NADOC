import { it, expect } from 'vitest'
import * as THREE from 'three'
import { createSelectionHaloMaterial, updateSelectionHaloPositions, selectionHaloShader } from './selection_halo.js'
import { prepareScene, loadPreparedScene, validateScene } from '../viewer/prepared_scene.js'
import { decodeContainer } from '../viewer/package_container.js'
import { captureSelectionUpdate } from '../viewer/selection_update.js'

it('reuses geometry and buffer across selection changes and uploads only changed positions', () => {
  const geometry = new THREE.BufferGeometry(), p = x => new THREE.Vector3(x, 1, 2)
  updateSelectionHaloPositions(geometry, [p(1), p(2)])
  const attr = geometry.attributes.position, version = attr.version
  updateSelectionHaloPositions(geometry, [p(1), p(2)])
  expect(attr.version).toBe(version)
  updateSelectionHaloPositions(geometry, [p(3)])
  expect(geometry.attributes.position).toBe(attr)
  expect(geometry.drawRange.count).toBe(1)
  expect(attr.array[0]).toBe(3)
  updateSelectionHaloPositions(geometry, [])
  expect(geometry.attributes.position).toBe(attr)
  expect(geometry.drawRange.count).toBe(0)
})

it('exports only active points rather than unused buffer capacity', () => {
  const scene = new THREE.Scene(), geometry = new THREE.BufferGeometry()
  const cloud = new THREE.Points(geometry, createSelectionHaloMaterial())
  cloud.userData.presentationSelection = 'points'; scene.add(cloud)
  const view = { selection: { target: cloud.uuid, revision: 1, label: 'Strand', ping: null } }
  updateSelectionHaloPositions(geometry, [new THREE.Vector3(1, 2, 3), new THREE.Vector3(4, 5, 6)])
  expect(captureSelectionUpdate({ scene, view }).payload.points).toEqual([1,2,3,4,5,6])
  updateSelectionHaloPositions(geometry, [new THREE.Vector3(1, 2, 3)])
  expect(captureSelectionUpdate({ scene, view }).payload.points).toEqual([1,2,3])
})

it('round-trips the trusted halo with depth testing and rejects invalid material types', async () => {
  const scene = new THREE.Scene(), geometry = new THREE.BufferGeometry()
  updateSelectionHaloPositions(geometry, [new THREE.Vector3(0, 0, 0)])
  const cloud = new THREE.Points(geometry, createSelectionHaloMaterial()); scene.add(cloud)
  const bytes = prepareScene({ scene, camera: { position: [0,0,10], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } })
  const loaded = await loadPreparedScene(bytes)
  const restored = loaded.scene.getObjectByProperty('uuid', cloud.uuid)
  expect(restored.material.onBeforeCompile).toBe(selectionHaloShader)
  expect(restored.material.depthTest).toBe(true)
  expect(restored.material.depthWrite).toBe(false)
  expect(restored.geometry.drawRange.count).toBe(1)
  const invalid = decodeContainer(bytes); invalid.materials[0].type = 'MeshBasicMaterial'
  expect(() => validateScene(invalid)).toThrow('Invalid selection halo')
  loaded.dispose()
})
