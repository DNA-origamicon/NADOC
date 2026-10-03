import { it, expect } from 'vitest'
import * as THREE from 'three'
import { captureSelectionUpdate, validateSelectionUpdate } from './selection_update.js'
import { mountSharedSelection } from './shared_selection.js'
import { createClusterSelection, installSelectionTint } from '../scene/selection_tint.js'
import { prepareScene, loadPreparedScene } from './prepared_scene.js'
const revision = 'a'.repeat(64)
function fixture() {
  const scene = new THREE.Scene(), mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial(), 3)
  for (let i = 0; i < 3; i++) mesh.setMatrixAt(i, new THREE.Matrix4().makeTranslation(i * 3, 0, 0))
  installSelectionTint(mesh); scene.add(mesh)
  const cloud = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)), new THREE.PointsMaterial())
  cloud.userData.presentationSelection = 'points'; scene.add(cloud)
  const view = { selection: { target: cloud.uuid, revision: 1, label: 'Base', ping: null } }
  return { scene, mesh, cloud, view, layer: createClusterSelection(scene) }
}
it('captures bounded world coordinates, masks and corners separately from molecular data', () => {
  const f = fixture(); f.cloud.position.x = 7
  f.layer.setGroups([[{ instMesh: f.mesh, id: 1 }]])
  const first = captureSelectionUpdate(f), second = captureSelectionUpdate(f)
  expect(first.supported).toBe(true); expect(first.payload.points).toEqual([7, 0, 0])
  expect(first.payload.tints).toEqual([{ target: f.mesh.uuid, ids: [1] }])
  expect(first.payload.corners).toHaveLength(144)
  expect(second.payload.points).toBe(first.payload.points)
  expect(second.payload.tints[0].ids).toBe(first.payload.tints[0].ids)
  f.view.selection.ping = { id: 'ping', createdAt: Date.now() }
  expect(captureSelectionUpdate(f).signature).toBe(first.signature)
  f.cloud.geometry.attributes.position.setX(0, 2); f.cloud.geometry.attributes.position.needsUpdate = true
  expect(captureSelectionUpdate(f).payload.points).toEqual([9, 0, 0])
  expect(() => validateSelectionUpdate({ ...first.payload, revision, id: 'one' })).not.toThrow()
  expect(() => validateSelectionUpdate({ ...first.payload, revision, id: 'one', points: [Infinity, 0, 0] })).toThrow()
  expect(() => validateSelectionUpdate({ ...first.payload, revision, id: 'one', tints: [{ target: f.mesh.uuid, ids: [2, 1] }] })).toThrow()
  f.layer.dispose()
})
it('updates and clears a loaded selection without replacing molecular buffers or scene', async () => {
  const f = fixture(), camera = { position: [0,0,20], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' }
  f.layer.setGroups([[{ instMesh: f.mesh, id: 0 }]])
  const guest = await loadPreparedScene(prepareScene({ scene: f.scene, view: f.view, camera }))
  const guestMesh = guest.scene.getObjectByProperty('uuid', f.mesh.uuid), matrix = guestMesh.instanceMatrix
  expect(guestMesh.material.userData.selectionTint).toBe(true)
  const runtime = { scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera() }
  runtime.scene.add(guest.scene)
  const container = document.createElement('div'), shared = mountSharedSelection({ container, runtime })
  shared.update(guest)
  f.layer.setGroups([[{ instMesh: f.mesh, id: 2 }]])
  const packet = { ...captureSelectionUpdate(f).payload, revision, id: 'update-one' }
  shared.receiveSelection(packet)
  expect(guestMesh.instanceMatrix).toBe(matrix)
  expect([...guestMesh.geometry.attributes.instanceSelection.array]).toEqual([0,0,1])
  expect(container.textContent).toContain('Presenter selected: Base')
  const attr = runtime.scene.getObjectByName('Shared selection overlay').children[0].geometry.attributes.position
  shared.receiveSelection(packet); expect(attr.version).toBe(0)
  shared.receiveSelection({ ...packet, id: 'invalid', tints: [{ target: f.mesh.uuid, ids: [10] }] })
  expect([...guestMesh.geometry.attributes.instanceSelection.array]).toEqual([0,0,1])
  shared.receiveSelection({ ...packet, id: 'clear', selection: null, points: [], corners: [], tints: [] })
  expect([...guestMesh.geometry.attributes.instanceSelection.array]).toEqual([0,0,0])
  expect(container.querySelector('.shared-selection-label').hidden).toBe(true)
  shared.dispose(); expect(runtime.scene.children).toEqual([guest.scene])
  guest.dispose(); f.layer.dispose()
})
