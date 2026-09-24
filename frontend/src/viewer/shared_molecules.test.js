import { expect, it } from 'vitest'
import * as THREE from 'three'
import { initSurfaceStrandsOverlay } from '../scene/surface_strands_overlay.js'
import { initProteinTraceRenderer } from '../scene/protein_trace_renderer.js'
import { createStreptavidinAtomicRenderer } from '../scene/streptavidin_atomic_renderer.js'
import { makeImpostorPhongMaterial, preparedImpostorSpec, enableImpostorInstanceAlpha } from '../scene/impostor_material.js'
import { prepareScene, loadPreparedScene, validateScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { createLiveFrameCapture } from './live_frame_capture.js'
import { createClipApplier } from './trajectory_clip.js'
const camera = { position: [0, 0, 30], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
const atom = (x, seq) => ({ name: 'CA', element: 'C', chain_id: 'A', seq_num: seq, res_seq: seq, res_name: 'GLY', helix_id: '__protein__p1', strand_id: '__protein__p1', x, y: 0, z: 0 })

it('shares simulated PEG beads, bonds and coverage patch, and detects new frames for republication', async () => {
  const scene = new THREE.Scene()
  const overlay = initSurfaceStrandsOverlay({ scene, camera: new THREE.PerspectiveCamera(), canvas: document.createElement('canvas') })
  overlay.setColor('#00ffff')
  overlay.update({ material: 'PEG', shape: 'square', sizeNm: 10, densityPerUm2: 10000, segments: 2, beadDiameterNm: .5 }, true)
  overlay.setResults([[[1, 2, 3], [1, 3, 3], [2, 4, 3]]])
  const bytes = prepareScene({ scene, camera }), guest = await loadPreparedScene(bytes)
  const hostPeg = scene.getObjectByName('peg-surface-beads'), guestPeg = guest.scene.getObjectByName('peg-surface-beads')
  expect(guestPeg.children[0].count).toBe(3)
  expect(guestPeg.children[0].instanceMatrix.array).toEqual(hostPeg.children[0].instanceMatrix.array)
  expect(guestPeg.children[1].geometry.attributes.position.array).toEqual(hostPeg.children[1].geometry.attributes.position.array)
  expect(guestPeg.parent.children.some(o => o.material?.opacity === .12)).toBe(true)
  const capture = createLiveFrameCapture(decodeContainer(bytes), { scene })
  overlay.applyPegFrame([0, 1, 2].map(i => ({ helix_id: 'cap0', cm_position: [i, 5, 3] })))
  expect(capture.frame({ scene })).toBeNull()
  const next = await loadPreparedScene(prepareScene({ scene, camera }))
  expect(next.scene.getObjectByName('peg-surface-beads').children[0].instanceMatrix.array[13]).toBe(5)
  next.dispose(); guest.dispose(); overlay.dispose()
})

it.each(['trace', 'ovoid', 'box'])('shares protein %s geometry and moving oxDNA poses', async mode => {
  const scene = new THREE.Scene(), protein = initProteinTraceRenderer(scene)
  protein.setMode(mode); protein.update({ atoms: [atom(0, 1), atom(.38, 2), atom(.76, 3)] })
  const bytes = prepareScene({ scene, camera }), guest = await loadPreparedScene(bytes)
  const capture = createLiveFrameCapture(decodeContainer(bytes), { scene })
  protein.applyOxdnaTransforms({ p1: new THREE.Matrix4().makeTranslation(3, 4, 5).transpose().toArray() })
  const frame = capture.frame({ scene }); expect(frame).not.toBeNull()
  createClipApplier(guest).apply(frame)
  scene.traverseVisible(o => {
    if (!o.isMesh) return
    const restored = guest.scene.getObjectByProperty('uuid', o.uuid)
    expect(restored.matrix.elements).toEqual(o.matrix.elements)
    expect(restored.geometry.attributes.position.array).toEqual(o.geometry.attributes.position.array)
  })
  guest.dispose(); protein.dispose()
})

it.each(['vdw', 'ballstick', 'stick'])('shares gold nanoparticles with atomic protein coatings in %s mode and live poses', async mode => {
  const scene = new THREE.Scene()
  const gold = new THREE.Mesh(new THREE.SphereGeometry(5), new THREE.MeshPhysicalMaterial({ color: 0xd4af37, metalness: 1, roughness: .18 }))
  scene.add(gold)
  const coating = createStreptavidinAtomicRenderer(gold, { protein: { atoms: [atom(0, 1), atom(.15, 2)], bonds: [[0, 1]] }, poses: [{ values: new THREE.Matrix4().makeTranslation(0, 5, 0).transpose().toArray() }] })
  coating.setMode(mode)
  const bytes = prepareScene({ scene, camera }), guest = await loadPreparedScene(bytes)
  expect(guest.scene.children[0].material.metalness).toBe(1)
  const capture = createLiveFrameCapture(decodeContainer(bytes), { scene })
  gold.position.set(2, 3, 4); coating.applyTransforms([new THREE.Matrix4().makeTranslation(1, 0, 0)])
  createClipApplier(guest).apply(capture.frame({ scene }))
  expect(guest.scene.children[0].matrix.elements.slice(12, 15)).toEqual([2, 3, 4])
  scene.traverseVisible(o => {
    if (!o.isInstancedMesh) return
    const restored = guest.scene.getObjectByProperty('uuid', o.uuid)
    expect(restored.instanceMatrix.array).toEqual(o.instanceMatrix.array)
    expect(preparedImpostorSpec(restored.material)).toEqual(preparedImpostorSpec(o.material))
  })
  guest.dispose(); coating.dispose(); gold.geometry.dispose(); gold.material.dispose()
})

it('restores trusted sphere shaders with alpha and rejects malformed or replaced shaders', async () => {
  const scene = new THREE.Scene(), material = makeImpostorPhongMaterial({ radius: .7 })
  enableImpostorInstanceAlpha(material)
  scene.add(new THREE.InstancedMesh(new THREE.PlaneGeometry(2, 2), material, 1))
  const bytes = prepareScene({ scene, camera }), guest = await loadPreparedScene(bytes)
  const shader = { uniforms: {}, vertexShader: '#include <common>\n#include <project_vertex>', fragmentShader: '#include <common>\n#include <clipping_planes_fragment>\n#include <normal_fragment_begin>' }
  guest.scene.children[0].material.onBeforeCompile(shader)
  expect(shader.uniforms.u_impostorRadius.value).toBe(.7)
  expect(shader.fragmentShader).toContain('gl_FragDepth')
  expect(shader.vertexShader).toContain('instanceAlpha')
  for (const radius of [-1, 0, Infinity, '1']) {
    const data = decodeContainer(bytes); data.materials[0].impostor.radius = radius
    expect(() => validateScene(data)).toThrow('Invalid sphere impostor')
  }
  material.onBeforeCompile = () => {}
  expect(() => prepareScene({ scene, camera })).toThrow('Custom shader')
  guest.dispose()
})
