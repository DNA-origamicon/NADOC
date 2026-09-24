import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { prepareScene, loadPreparedScene, validateScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { renderSharedOverlay } from './shared_overlay.js'
const camera = { position: [10, 0, 0], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
function snapshot() {
  const scene = new THREE.Scene()
  for (const x of [-2, 2]) {
    const layer = new THREE.Scene(); layer.position.x = x
    layer.add(new THREE.AmbientLight(0xffffff, .4))
    layer.add(new THREE.Mesh(new THREE.CylinderGeometry(), new THREE.MeshPhongMaterial({ transparent: true, opacity: .35 })))
    scene.add(layer)
  }
  return prepareScene({ scene, camera, view: { overlay: scene.children.map(layer => layer.uuid) } })
}
it('round trips isolated overlay lighting, opacity, and separation', async () => {
  const loaded = await loadPreparedScene(snapshot())
  expect(loaded.data.version).toBe(5)
  expect(loaded.scene.children.map(layer => layer.matrix.elements[12])).toEqual([-2, 2])
  expect(loaded.scene.children[1].children[1].material.opacity).toBe(.35)
  const cam = new THREE.PerspectiveCamera(); cam.position.set(10, 0, 0); cam.lookAt(0, 0, 0)
  const draws = [], renderer = { autoClear: true, clearDepth: vi.fn(), render: (scene) => draws.push([scene.uuid, renderer.autoClear]) }
  renderSharedOverlay(renderer, loaded.scene.children, cam)
  expect(draws).toEqual(loaded.data.view.overlay.map((id, i) => [id, i === 0]))
  expect(renderer.clearDepth).toHaveBeenCalledOnce()
  expect(renderer.autoClear).toBe(true)
  cam.position.x = -10; cam.lookAt(0, 0, 0); draws.length = 0
  renderSharedOverlay(renderer, loaded.scene.children, cam)
  expect(draws.map(draw => draw[0])).toEqual([...loaded.data.view.overlay].reverse())
  loaded.dispose()
})
it('rejects malformed overlay references and incompatible versions before loading', () => {
  for (const change of [d => { d.view.overlay = [] }, d => { d.view.overlay[0] = 'missing' }, d => { d.version = 4 }, d => { d.root.children[0].type = 'Group' }]) {
    const data = decodeContainer(snapshot()); change(data)
    expect(() => validateScene(data)).toThrow('Invalid shared overlay')
  }
})
it('restores renderer state on a failed draw', () => {
  const renderer = { autoClear: false, render: () => { throw new Error('draw') } }
  expect(() => renderSharedOverlay(renderer, [new THREE.Scene()], new THREE.PerspectiveCamera())).toThrow('draw')
  expect(renderer.autoClear).toBe(false)
})
