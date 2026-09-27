import { it, expect } from 'vitest'
import * as THREE from 'three'
import { registerPreparedAssemblyMaterial, bakePreparedAssemblyInstances } from './prepared_assembly_instances.js'
import { prepareScene, loadPreparedScene } from '../viewer/prepared_scene.js'
import { broadcastFingerprint } from '../viewer/broadcast_fingerprint.js'
import { preparedImpostorSpec } from './impostor_material.js'

const texture = values => ({ value: new THREE.DataTexture(new Float32Array(values), 4, values.length / 16, THREE.RGBAFormat, THREE.FloatType) })
const matrix = x => new THREE.Matrix4().makeTranslation(x, 0, 0).toArray()
function fixture({ radius, positions = false, offset = 0 } = {}) {
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial(), 1)
  mesh.count = 4
  mesh.material.onBeforeCompile = () => {}
  const spec = { xform: texture([...matrix(10), ...matrix(30), ...matrix(50)]),
    visibility: texture([1,...Array(15).fill(0), 0,...Array(15).fill(0), 1,...Array(15).fill(0)]),
    baseCount: 2, offset: { value: offset }, radius,
    color: texture([1,0,0,1, 0,1,0,1, ...Array(8).fill(0)]),
    ...(positions ? { positions: texture([2,0,0,1, 4,0,0,1, ...Array(8).fill(0)]) } : { local: texture([...matrix(2), ...matrix(4)]) }) }
  registerPreparedAssemblyMaterial(mesh.material, spec)
  const scene = new THREE.Scene(); scene.add(mesh)
  return { mesh, spec, scene }
}
it('bakes texture placement × local matrices, colors, visibility and LOD offsets without mutating the editor', async () => {
  const { mesh, scene } = fixture({ offset: 1 })
  const original = mesh.instanceMatrix.array.slice()
  const result = await loadPreparedScene(prepareScene({ scene, camera: { position: [0,0,100], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } }))
  const frozen = result.scene.children[0]
  expect(frozen.count).toBe(2)
  expect([...frozen.instanceMatrix.array]).toEqual([...matrix(52), ...matrix(54)])
  expect([...frozen.instanceColor.array]).toEqual([1,0,0, 0,1,0])
  expect(mesh.count).toBe(4); expect(mesh.instanceMatrix.array).toEqual(original)
  result.dispose()
})
it('restores recognized atom sphere impostors with translated centers and their radius', () => {
  const { mesh, spec } = fixture({ radius: .17, positions: true })
  spec.xform.value.image.data[0] = 2
  const frozen = bakePreparedAssemblyInstances(mesh)
  expect(preparedImpostorSpec(frozen.material)?.radius).toBe(.17)
  expect([...frozen.instanceMatrix.array]).toEqual([...matrix(14), ...matrix(18)])
})
it('observes texture content and LOD ranges even when ordinary instance buffers are unchanged', () => {
  const { scene, spec } = fixture()
  const source = { scene, view: {} }, before = broadcastFingerprint(source)
  spec.xform.value.needsUpdate = true
  expect(broadcastFingerprint(source)).toBe(before)
  spec.xform.value.image.data[12] = 20; spec.xform.value.needsUpdate = true
  const moved = broadcastFingerprint(source); expect(moved).not.toBe(before)
  spec.offset.value = 1
  expect(broadcastFingerprint(source)).not.toBe(moved)
})
it('does not authorize a subsequently replaced custom shader', () => {
  const { mesh, scene } = fixture()
  mesh.material.onBeforeCompile = () => {}
  expect(bakePreparedAssemblyInstances(mesh)).toBe(mesh)
  expect(() => prepareScene({ scene })).toThrow('Custom shader')
})
