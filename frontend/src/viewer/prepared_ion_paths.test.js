import { it, expect } from 'vitest'
import * as THREE from 'three'
import { initMdIonPaths } from '../scene/md_ion_paths.js'
import { prepareScene, loadPreparedScene, validateScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { liveSceneSignature } from './live_frame_capture.js'
const camera = { position: [0, 10, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
const data = { paths: [{ species: 'NA', ion_serial: 1, positions: [0, -1, 0, 0, 1, 0, 1, 2, 0] }, { species: 'CL', ion_serial: 2, positions: [1, -1, 0, 1, 1, 0] }], pore: { radius_nm: 4, normal: [0, 1, 0] } }
it('round-trips actual nanopore paths, thickness, color, percentage, and vector arrows without arbitrary shader code', async () => {
  const scene = new THREE.Scene(), overlay = initMdIonPaths(scene); overlay.setData(data); overlay.setWidth(7)
  const before = liveSceneSignature({ scene })
  overlay.setWidth(4); expect(liveSceneSignature({ scene })).not.toBe(before)
  const packet = prepareScene({ scene, camera }), decoded = decodeContainer(packet)
  expect(decoded.version).toBe(3); expect(decoded.materials.every(m => !m.vertexShader && !m.uniforms)).toBe(true)
  const view = await loadPreparedScene(packet), lines = []
  view.scene.traverse(o => { if (o.isLineSegments2) lines.push(o) }); lines.sort((a, b) => b.name.localeCompare(a.name))
  expect(lines).toHaveLength(2); expect(lines[0].material.linewidth).toBe(4)
  expect([...lines[0].geometry.attributes.instanceStart.array]).toEqual([0, -1, 0, 0, 1, 0])
  expect(lines[0].geometry.instanceCount).toBe(2)
  expect(lines[0].material.vertexColors).toBe(true)
  const original = scene.getObjectByName('ionPaths-NA')
  expect([...lines[0].geometry.attributes.instanceColorStart.array]).toEqual(Array.from({ length: original.geometry.attributes.instanceColorStart.count * 3 }, (_, i) => original.geometry.attributes.instanceColorStart.getComponent(Math.floor(i / 3), i % 3)))
  view.dispose()
  overlay.setPercentage(50); expect(liveSceneSignature({ scene })).not.toBe(before)
  overlay.setMode('vector-field'); const vectors = await loadPreparedScene(prepareScene({ scene, camera }))
  const arrows = vectors.scene.getObjectByName('ionVectorHeads-NA'), source = scene.getObjectByName('ionVectorHeads-NA')
  expect(arrows.count).toBe(source.count); expect([...arrows.instanceMatrix.array]).toEqual([...source.instanceMatrix.array])
  expect([...arrows.instanceColor.array]).toEqual([...source.instanceColor.array])
  expect(vectors.scene.getObjectByName('ionPaths-NA')).toBeUndefined()
  vectors.dispose(); overlay.clear()
  decoded.materials.find(m => m.wideLine).uniforms = { injected: 1 }
  expect(() => validateScene(decoded)).toThrow('Unsupported package material')
})
