import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { computeSurfaceNormals } from './surface_normals.js'

function compare(geometry) {
  const old = geometry.clone()
  const previousVersion = geometry.attributes.normal?.version ?? 0
  old.computeVertexNormals(); computeSurfaceNormals(geometry)
  expect(new Uint8Array(geometry.attributes.normal.array.buffer)).toEqual(new Uint8Array(old.attributes.normal.array.buffer))
  expect(geometry.attributes.normal.version).toBe(previousVersion + 1)
}

describe('surface normal buffer writes', () => {
  it('matches Three bytes for changing meshes, repeated/degenerate faces and isolated vertices', () => {
    let seed = 7789
    const random = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32)
    for (const Type of [Uint16Array, Uint32Array]) {
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(Float32Array.from({length:303}, () => (random() - .5) * 100), 3))
      geometry.setIndex(new THREE.BufferAttribute(Type.from([0,0,0,1,2,1,...Array.from({length:600}, () => Math.floor(random()*100))]), 1))
      compare(geometry)
      geometry.attributes.position.array[9] += .37
      // Preserve identity of an installed normal buffer through subsequent updates.
      const installed = geometry.attributes.normal
      compare(geometry)
      expect(geometry.attributes.normal).toBe(installed)
    }
  })
  it('matches Three for empty and collinear surfaces', () => {
    for (const points of [[],[0,0,0,1,1,1,2,2,2]]) {
      const geometry=new THREE.BufferGeometry()
      geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(points),3))
      geometry.setIndex(points.length ? [0,1,2] : [])
      compare(geometry)
    }
  })
  it('falls back for nonindexed and Float64 positions', () => {
    for (const Type of [Float32Array,Float64Array]) {
      const geometry=new THREE.BufferGeometry()
      geometry.setAttribute('position',new THREE.BufferAttribute(new Type([0,0,0,1,2,3,3,2,1]),3))
      if (Type===Float64Array) geometry.setIndex([0,1,2])
      compare(geometry)
    }
  })
})
