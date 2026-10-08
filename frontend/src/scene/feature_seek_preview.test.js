import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { createFeatureSeekPreview } from './feature_seek_preview.js'

it('shows sampled paths without editing the source meshes and restores visibility', () => {
  const scene = new THREE.Scene()
  const original = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
  const hidden = original.clone(); hidden.visible = false
  scene.add(original, hidden)
  const before = original.matrix.clone()
  const clear = createFeatureSeekPreview(scene)({ helix_axes: [{ samples: [[0,0,0], [1,2,3], [3,4,5]] }] })
  const preview = scene.getObjectByName('feature-seek-preview')
  expect(preview.children[0].count).toBe(2)
  expect(original.visible).toBe(false)
  expect(original.matrix.equals(before)).toBe(true)
  const dispose = vi.spyOn(preview.children[0].geometry, 'dispose')
  clear(); clear()
  expect(original.visible).toBe(true)
  expect(hidden.visible).toBe(false)
  expect(dispose).toHaveBeenCalledOnce()
  expect(scene.getObjectByName('feature-seek-preview')).toBeUndefined()
})
