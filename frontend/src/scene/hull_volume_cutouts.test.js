import { it, expect } from 'vitest'
import * as THREE from 'three'
import { hullCutoutSpec, pointInHullCutout, applyHullCutouts, hullCutoutShader } from './hull_volume_cutouts.js'
import { pointInVolume } from './view_volumes.js'
import { prepareScene, loadPreparedScene } from '../viewer/prepared_scene.js'
const camera = { position: [0,0,10], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' }
it.each(['box', 'hexagonal'])('matches %s volume membership with rotation', shape => {
  const volume = { shape, min_corner: [-3,-2,-1], max_corner: [3,2,1], rotation: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0), .7).toArray() }
  const spec = hullCutoutSpec([volume])
  for (const point of [[0,0,0], [1,1,1], [4,0,0], [0,2,0], [-1.2,.3,-.5]]) {
    expect(pointInHullCutout(new THREE.Vector3(...point), spec)).toBe(pointInVolume(point, volume))
  }
  expect(hullCutoutSpec([{ ...volume, enabled: false }])).toEqual([])
})
it('updates uniforms without shader recompilation and round trips through sharing', async () => {
  const material = new THREE.MeshPhongMaterial(), scene = new THREE.Scene()
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(6,6,6), material))
  const volume = { min_corner: [-1,-1,-1], max_corner: [1,1,1] }
  applyHullCutouts(material, hullCutoutSpec([volume]))
  const shader = { uniforms: {}, vertexShader: '#include <project_vertex>', fragmentShader: '#include <clipping_planes_fragment>' }
  material.onBeforeCompile(shader)
  expect(shader.fragmentShader).toContain('discard')
  const version = material.version
  applyHullCutouts(material, hullCutoutSpec([{ ...volume, max_corner: [3,3,3] }]))
  expect(material.version).toBe(version)
  expect(shader.uniforms.hullHalf.value[0].toArray()).toEqual([2,2,2])
  expect(() => material.clone()).not.toThrow()
  const guest = await loadPreparedScene(prepareScene({ scene, camera }))
  expect(guest.data.version).toBe(6)
  expect(guest.scene.children[0].material.onBeforeCompile).toBe(hullCutoutShader)
  expect(guest.scene.children[0].material.userData.hullCutouts).toEqual(material.userData.hullCutouts)
  guest.dispose()
  applyHullCutouts(material, [])
  expect(material.version).toBeGreaterThan(version)
})
