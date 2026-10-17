// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createTransformHistoryPreview, buildTransformPreviewLayer } from './transform_history_preview.js'
import { transformComponent, transformPacket } from '../test-helpers/transform_preview.js'
import { store } from '../state/store.js'

const owners = []
afterEach(() => { for (const owner of owners.splice(0)) owner.dispose(); vi.restoreAllMocks() })
function setup() {
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(), live = new THREE.Group(), light = new THREE.AmbientLight()
  scene.add(live, light)
  const preview = createTransformHistoryPreview({ scene, camera }); owners.push(preview)
  return { scene, camera, live, light, preview }
}
describe('private complete transform renderer', () => {
  it('uses native slab matrices and leaves canonical store, root and camera pose untouched', () => {
    const { scene, camera, live, light, preview } = setup(), packet = transformPacket(), original = JSON.stringify(packet)
    const position = camera.position.clone()
    vi.spyOn(store, 'getState').mockImplementation(() => { throw new Error('live store access') })
    vi.spyOn(store, 'setState').mockImplementation(() => { throw new Error('live store mutation') })
    preview.open(packet)
    expect(live.visible).toBe(true); expect(camera.layers.test(live.layers)).toBe(false)
    expect(camera.position.equals(position)).toBe(true)
    const geometry = preview.candidateGeometry()
    expect(geometry.backboneEntries).toHaveLength(2)
    const slab = geometry.slabEntries[0], matrix = new THREE.Matrix4(), center = new THREE.Vector3()
    slab.instMesh.getMatrixAt(slab.id, matrix); center.setFromMatrixPosition(matrix)
    expect(center.toArray()).toEqual(expect.arrayContaining(packet.candidate.nucleotides[0].slab_position.map(v => expect.closeTo(v, 6))))
    expect(JSON.stringify(packet)).toBe(original)
    preview.dispose(); expect(scene.children).toEqual([live, light]); expect(camera.layers.mask).toBe(1)
  })
  it('preserves last accepted candidate on malformed update and disposes partially built Open', () => {
    const { scene, live, light, preview } = setup(), bad = transformPacket(); bad.candidate.nucleotides.pop()
    expect(() => preview.open(bad)).toThrow(); expect(scene.children).toEqual([live, light])
    preview.open(transformPacket()); const previous = preview.candidateGeometry()
    expect(() => preview.replaceCandidate(bad.candidate)).toThrow()
    expect(preview.candidateGeometry()).toBe(previous)
    preview.replaceCandidate(null); expect(preview.candidateGeometry()).toBe(null)
    preview.show('before'); preview.replaceCandidate(transformComponent()); preview.show('candidate')
  })
  it('never restores a camera layer taken by a newer owner', () => {
    const { camera, preview } = setup(); preview.open(transformPacket())
    camera.layers.set(7); preview.dispose(); expect(camera.layers.mask).toBe(1 << 7)
  })
  it('releases private resources once and leaves shared geometry usable', () => {
    const scene = new THREE.Scene(), layer = buildTransformPreviewLayer(transformComponent(), scene); owners.push(layer)
    const shared = new Set(), materials = new Set()
    layer.root.traverse(node => { if (node.geometry?.userData?.shared) shared.add(node.geometry); if (node.material) materials.add(node.material) })
    const sharedSpies = [...shared].map(value => vi.spyOn(value, 'dispose'))
    const disposed = [...materials].map(value => vi.spyOn(value, 'dispose'))
    layer.dispose(); layer.dispose()
    for (const spy of sharedSpies) expect(spy).not.toHaveBeenCalled()
    for (const spy of disposed) expect(spy).toHaveBeenCalledOnce()
    expect(scene.children).toEqual([])
  })
})
