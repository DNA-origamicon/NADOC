import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { prepareScene, loadPreparedScene, validateScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { installInstanceAlpha, instanceAlphaOnBeforeCompile } from '../scene/instance_alpha.js'
const camera = { position: [10, 4, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'multiscale' }
function fixture() {
  const scene = new THREE.Scene(), geo = new THREE.BoxGeometry(), mat = new THREE.MeshPhongMaterial({ color: 0x345678 })
  const mesh = new THREE.InstancedMesh(geo, mat, 2)
  mesh.name = 'bases'; mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(8, 2, -9)); mesh.setColorAt(1, new THREE.Color('red'))
  mesh.frustumCulled = false
  scene.add(mesh, new THREE.Mesh(geo, mat), new THREE.DirectionalLight(0xffffff, 1.1))
  return { scene, mesh }
}
describe('prepared scene', () => {
  it('round-trips Full geometry, instance transforms/colors, lights and shared resources', async () => {
    const { scene, mesh } = fixture()
    mesh.material.color.setRGB(.1234567, .3456789, .5678912)
    const bytes = prepareScene({ scene, camera })
    const result = await loadPreparedScene(bytes), restored = result.scene.children[0]
    expect(restored.geometry.attributes.position.array).toEqual(mesh.geometry.attributes.position.array)
    expect(restored.instanceMatrix.array).toEqual(mesh.instanceMatrix.array)
    expect(restored.instanceColor.array).toEqual(mesh.instanceColor.array)
    expect(restored.material.color.toArray()).toEqual(mesh.material.color.toArray())
    expect(restored.geometry).toBe(result.scene.children[1].geometry)
    expect(restored.frustumCulled).toBe(false)
    expect(result.scene.children[2].target.isObject3D).toBe(true)
    const dispose = vi.spyOn(restored.geometry, 'dispose')
    result.dispose(); expect(dispose).toHaveBeenCalledTimes(1)
    expect(result.scene.children).toHaveLength(0)
  })
  it('preserves instance alpha, omits invisible nodes and does not mutate the source', async () => {
    const { scene, mesh } = fixture(); installInstanceAlpha(mesh)
    mesh.geometry.attributes.instanceAlpha.setX(1, 0)
    scene.children[1].visible = false
    const result = await loadPreparedScene(prepareScene({ scene, camera }))
    expect(result.scene.children).toHaveLength(2)
    expect(result.scene.children[0].material.onBeforeCompile).toBe(instanceAlphaOnBeforeCompile)
    expect(result.scene.children[0].geometry.attributes.instanceAlpha.array[1]).toBe(0)
    expect(scene.children).toHaveLength(3)
    expect(scene.children[1].visible).toBe(false)
    result.dispose()
  })
  it('fails clearly for unsupported shader transforms and rejects remote images before loading', () => {
    const { scene, mesh } = fixture()
    mesh.material.onBeforeCompile = () => {}
    expect(() => prepareScene({ scene, camera })).toThrow('Custom shader')
    mesh.material.onBeforeCompile = THREE.Material.prototype.onBeforeCompile
    const data = decodeContainer(prepareScene({ scene, camera }))
    data.images.push({ uuid: 'image', url: 'https://example.test/private.png' })
    expect(() => validateScene(data)).toThrow('embedded PNG')
  })
  it('rejects invalid resources before allocating GPU objects', () => {
    const { scene } = fixture()
    const original = prepareScene({ scene, camera })
    for (const mutate of [d => { d.root.children[0].count = 1e10 }, d => { d.geometries[0].index.array[0] = 65535 }, d => { d.materials[0].type = 'ShaderMaterial' }, d => { d.camera.position[0] = Infinity }, d => { d.version = 999 }]) {
      const data = decodeContainer(original.slice(0)); mutate(data)
      expect(() => validateScene(data)).toThrow()
    }
  })
})

it('preserves strided attribute values and normalization', async () => {
  const scene = new THREE.Scene(), geometry = new THREE.BufferGeometry()
  const buffer = new THREE.InterleavedBuffer(new Float32Array([1, 2, 3, 8, 4, 5, 6, 9, 7, 8, 9, 10]), 4)
  geometry.setAttribute('position', new THREE.InterleavedBufferAttribute(buffer, 3, 0))
  scene.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial()))
  const result = await loadPreparedScene(prepareScene({ scene, camera }))
  expect([...result.scene.children[0].geometry.attributes.position.array]).toEqual([1,2,3,4,5,6,7,8,9])
  result.dispose()
})
