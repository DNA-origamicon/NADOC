import { it, expect } from 'vitest'
import * as THREE from 'three'
import { broadcastFingerprint } from './broadcast_fingerprint.js'

it('ignores redundant interleaved uploads but detects coordinate changes', () => {
  const data = new THREE.InterleavedBuffer(new Float32Array([1, 2, 3, 4, 5, 6]), 3)
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.InterleavedBufferAttribute(data, 3, 0))
  const scene = new THREE.Scene(); scene.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial()))
  const first = broadcastFingerprint({ scene })
  data.needsUpdate = true
  expect(broadcastFingerprint({ scene })).toBe(first)
  data.array[0] = 9; data.needsUpdate = true
  expect(broadcastFingerprint({ scene })).not.toBe(first)
})

it('treats actual index changes as layout changes, even for streamed coordinates', () => {
  const scene = new THREE.Scene(), geometry = new THREE.BoxGeometry()
  scene.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial()))
  const signature = () => broadcastFingerprint({ scene }, { coordinates: false })
  const first = signature()
  geometry.index.needsUpdate = true; expect(signature()).toBe(first)
  geometry.index.array[0] = geometry.index.array[1]; geometry.index.needsUpdate = true
  expect(signature()).not.toBe(first)
})
