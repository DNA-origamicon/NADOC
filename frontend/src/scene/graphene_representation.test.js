import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { grapheneNeighbors, grapheneTriangles, graphenePreviewSites, initGrapheneRepresentation } from './graphene_representation.js'

const ring = new Float32Array(Array.from({ length: 6 }, (_, i) =>
  [0.142 * Math.cos(i * Math.PI / 3), 0.142 * Math.sin(i * Math.PI / 3), 0]).flat())

describe('graphene display geometry', () => {
  it('connects nearest carbons, without second-neighbor, interlayer or across-pore bonds', () => {
    const xyz = new Float32Array([...ring, ...Array.from(ring, (v, i) => i % 3 === 2 ? v + 0.335 : v), 3, 0, 0])
    const neighbors = grapheneNeighbors(xyz)
    expect(neighbors.slice(0, 12).map(row => row.length)).toEqual(Array(12).fill(2))
    expect(neighbors[12]).toEqual([])
    expect(grapheneTriangles(neighbors)).toHaveLength(24)
    const broken = grapheneNeighbors(ring.slice(0, 15))
    expect(grapheneTriangles(broken)).toEqual([])
  })
  it('keeps preview sites outside the pore and layers on the outward side', () => {
    const xyz = graphenePreviewSites(1, 0.5, 2, 0.335)
    expect(xyz.length).toBeGreaterThan(0)
    const levels = new Set()
    for (let i = 0; i < xyz.length; i += 3) {
      expect(Math.hypot(xyz[i], xyz[i + 1])).toBeGreaterThanOrEqual(0.5 - 1e-7)
      expect(Math.abs(xyz[i])).toBeLessThanOrEqual(1)
      levels.add(xyz[i + 2].toFixed(3))
    }
    expect([...levels]).toEqual(['0.000', '-0.335'])
  })
  it('switches a paused frame immediately, keeps it hidden across frames, and disposes meshes', () => {
    const scene = new THREE.Scene(), view = initGrapheneRepresentation(scene)
    view.setFrame(ring)
    expect(view.mesh().count).toBe(6)
    view.setDisplay({ visible: false, representation: 'stick' })
    expect(view.mesh().count).toBe(6)
    expect(view.mesh().visible).toBe(false)
    view.setFrame(ring.map(v => v + 1))
    expect(view.mesh().visible).toBe(false)
    view.setDisplay({ visible: true, representation: 'plane' })
    expect(view.mesh().geometry.index.count).toBe(12)
    expect(view.mesh().geometry.attributes.position.array[0]).toBeCloseTo(ring[0] + 1)
    expect(view.mesh().visible).toBe(true)
    expect(scene.children).toHaveLength(1)
    view.clear(); expect(view.mesh().visible).toBe(false)
    view.setDisplay({ visible: true, representation: 'ball' })
    expect(scene.children).toHaveLength(0)
    view.dispose()
  })
})
