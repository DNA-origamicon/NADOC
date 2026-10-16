// @vitest-environment node
import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { createDeformationPreviewCamera, DEFORMATION_PREVIEW_LAYER } from './deformation_preview_camera.js'

describe('private deformation camera layer', () => {
  it('excludes canonical siblings and later rebuilds without changing their visibility', () => {
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
    const live = new THREE.Group(), arc = new THREE.Line(), light = new THREE.AmbientLight()
    scene.add(live, arc, light)
    const owner = createDeformationPreviewCamera({ scene, camera })
    const preview = new THREE.Group(), mesh = new THREE.Mesh(); preview.add(mesh)
    owner.include(preview); scene.add(preview)
    expect(camera.layers.test(mesh.layers)).toBe(true)
    expect(camera.layers.test(arc.layers)).toBe(false)
    expect(camera.layers.test(light.layers)).toBe(true)
    const rebuilt = new THREE.Mesh(); scene.add(rebuilt)
    expect(camera.layers.test(rebuilt.layers)).toBe(false)
    expect(live.visible).toBe(true); expect(arc.visible).toBe(true)
    owner.dispose(); owner.dispose()
    expect(camera.layers.mask).toBe(1); expect(light.layers.mask).toBe(1)
    expect(camera.layers.test(mesh.layers)).toBe(false)
  })

  it('refuses an occupied layer or nonstandard camera before changing any state', () => {
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(), other = new THREE.Group()
    other.layers.set(DEFORMATION_PREVIEW_LAYER); scene.add(other)
    expect(() => createDeformationPreviewCamera({ scene, camera })).toThrow(/layer/i)
    expect(camera.layers.mask).toBe(1)
    scene.remove(other); camera.layers.set(2)
    expect(() => createDeformationPreviewCamera({ scene, camera })).toThrow(/view/i)
    expect(camera.layers.mask).toBe(4)
  })

  it('restores only masks it still owns, preserving another view transition', () => {
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(), light = new THREE.AmbientLight()
    scene.add(light)
    const owner = createDeformationPreviewCamera({ scene, camera })
    camera.layers.set(3); light.layers.set(4)
    owner.dispose()
    expect(camera.layers.mask).toBe(8); expect(light.layers.mask).toBe(16)
  })
})
