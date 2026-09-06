import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { sectionStencilGeometry } from './section_geometry.js'

describe('section stencil solid geometry', () => {
  it('accepts closed solids with split UV and normal seams', () => {
    for (const geometry of [new THREE.SphereGeometry(), new THREE.BoxGeometry(), new THREE.CylinderGeometry()]) {
      expect(sectionStencilGeometry(geometry)).toBe(geometry)
      expect(sectionStencilGeometry(geometry.toNonIndexed())).not.toBeNull()
    }
  })
  it('rejects open sheets and arbitrary missing faces', () => {
    expect(sectionStencilGeometry(new THREE.PlaneGeometry())).toBeNull()
    const partial = new THREE.BoxGeometry()
    partial.setDrawRange(6, partial.index.count - 6)
    expect(sectionStencilGeometry(partial)).toBeNull()
    const box = new THREE.BoxGeometry()
    box.setIndex(Array.from(box.index.array).slice(6))
    expect(sectionStencilGeometry(box)).toBeNull()
  })
  it('closes open tube and cylinder ends only in the stencil copy', () => {
    const path = new THREE.CatmullRomCurve3([new THREE.Vector3(-1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(1, 0, 0)])
    for (const source of [new THREE.TubeGeometry(path, 12, 0.2, 8), new THREE.CylinderGeometry(1, 1, 2, 8, 1, true)]) {
      const originalCount = source.index.count
      const closed = sectionStencilGeometry(source)
      expect(closed).not.toBeNull()
      expect(closed).not.toBe(source)
      expect(closed.index.count).toBeGreaterThan(originalCount)
      expect(closed.getAttribute('position')).toBe(source.getAttribute('position'))
      expect(source.index.count).toBe(originalCount)
      expect(sectionStencilGeometry(closed)).toBe(closed)
    }
  })
})
