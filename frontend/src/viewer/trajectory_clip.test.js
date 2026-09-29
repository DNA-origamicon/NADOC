import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { prepareScene, loadPreparedScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { sceneChannels, encodeFrame, decodeFrame, createClipApplier, clipFrameAt, validateClip } from './trajectory_clip.js'

const camera = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
function fixture() {
  const scene = new THREE.Scene(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
  scene.add(mesh)
  return { scene, mesh, pack: () => prepareScene({ scene, camera }) }
}
describe('independent trajectory patches', () => {
  it('smooths sparse positions and rotations without collapsing geometry, then restores exact frames', async () => {
    const f = fixture(), buffer = f.pack(), base = sceneChannels(decodeContainer(buffer)), current = await loadPreparedScene(buffer)
    const empty = encodeFrame(base, base), apply = createClipApplier(current)
    f.mesh.position.x = 8; f.mesh.rotation.z = Math.PI
    f.mesh.geometry.attributes.position.setY(0, 6)
    const end = encodeFrame(base, sceneChannels(decodeContainer(f.pack())))
    apply.interpolate(empty, end, .5)
    const matrix = current.scene.children[0].matrix, position = new THREE.Vector3(), rotation = new THREE.Quaternion(), scale = new THREE.Vector3()
    matrix.decompose(position, rotation, scale)
    expect(position.x).toBe(4)
    for (const value of scale) expect(value).toBeCloseTo(1)
    expect(new THREE.Vector3(1, 0, 0).applyQuaternion(rotation).y).toBeCloseTo(1)
    expect(current.scene.children[0].geometry.attributes.position.getY(0)).toBeCloseTo(3.25)
    apply.interpolate(empty, end, .75)
    expect(matrix.elements[12]).toBe(6)
    apply.apply(empty)
    expect(matrix.elements).toEqual(new THREE.Matrix4().elements)
    expect(current.scene.children[0].geometry.attributes.position.getY(0)).toBe(.5)
    current.dispose()
  })
  it('keeps hidden instances discrete and never writes NaN matrices', async () => {
    const f = fixture(), buffer = f.pack(), base = sceneChannels(decodeContainer(buffer)), current = await loadPreparedScene(buffer)
    const empty = encodeFrame(base, base), apply = createClipApplier(current)
    f.mesh.scale.setScalar(0); f.mesh.position.x = 8
    const end = encodeFrame(base, sceneChannels(decodeContainer(f.pack())))
    apply.interpolate(empty, end, .5)
    expect(current.scene.children[0].matrix.elements).toEqual(new THREE.Matrix4().elements)
    apply.interpolate(empty, end, 1)
    expect(current.scene.children[0].matrix.elements.every(Number.isFinite)).toBe(true)
    expect(current.scene.children[0].matrix.elements[0]).toBe(0)
    current.dispose()
  })
  it('restores unchanged baseline values after out-of-order seeks without recreating geometry', async () => {
    const f = fixture(), buffer = f.pack(), base = sceneChannels(decodeContainer(buffer)), current = await loadPreparedScene(buffer)
    const geometry = current.scene.children[0].geometry, apply = createClipApplier(current)
    f.mesh.position.x = 12
    const a = encodeFrame(base, sceneChannels(decodeContainer(f.pack())))
    f.mesh.position.x = 0; f.mesh.position.y = 7; f.mesh.geometry.attributes.position.setX(0, 9)
    const b = encodeFrame(base, sceneChannels(decodeContainer(f.pack())))
    apply.apply(b); expect(geometry.attributes.position.getX(0)).toBe(9)
    apply.apply(a)
    expect(current.scene.children[0].matrix.elements.slice(12, 15)).toEqual([12, 0, 0])
    expect(geometry.attributes.position.getX(0)).toBe(.5)
    expect(current.scene.children[0].geometry).toBe(geometry)
    current.dispose()
  })
  it('fails closed on changed topology/material rather than mixing scene identities', () => {
    const f = fixture(), base = sceneChannels(decodeContainer(f.pack()))
    f.mesh.material.color.setHex(0xff0000)
    expect(() => encodeFrame(base, sceneChannels(decodeContainer(f.pack())))).toThrow('scene structure changed')
  })
  it('rejects invalid indices, NaNs and truncated frame payloads', () => {
    const f = fixture(), base = sceneChannels(decodeContainer(f.pack()))
    f.mesh.position.x = 2
    const b = encodeFrame(base, sceneChannels(decodeContainer(f.pack())))
    expect(() => decodeFrame(b.slice(0, b.byteLength - 1), base.values.length)).toThrow()
    new Uint32Array(b, 8, 1)[0] = base.values.length
    expect(() => decodeFrame(b, base.values.length)).toThrow('Invalid trajectory coordinates')
  })
  it('uses elapsed meeting time and clamps at clip boundaries', () => {
    expect(clipFrameAt({ frame: 2, at: 1000, playing: true, fps: 8 }, 2000, 20)).toBe(10)
    expect(clipFrameAt({ frame: 2, at: 1000, playing: false, fps: 8 }, 9000, 20)).toBe(2)
    expect(clipFrameAt({ frame: 2, at: 1000, playing: true, fps: 8 }, 9000, 20)).toBe(19)
  })
  it('rejects ambiguous source ordering and excessive clip lengths', () => {
    expect(() => validateClip({ version: 1, encoding: 'absolute-render-patch-gzip', fps: 8, sourceFrames: [1, 0], frames: [{}, {}] })).toThrow()
  })
})
