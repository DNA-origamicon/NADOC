import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { initMdOverlay } from './md_overlay.js'

describe('MD bead overlay', () => {
  it('rebuilds the same bead count and radius after being cleared', () => {
    const scene = new THREE.Scene()
    const overlay = initMdOverlay(scene)
    const points = [{ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }]
    overlay.update(points, 0.28, 0.95)
    const first = overlay.mesh()
    expect(first?.count).toBe(2)

    overlay.update([], 0.55, 0.95)
    expect(overlay.mesh()).toBeNull()
    overlay.update(points, 0.28, 0.95)
    expect(overlay.mesh()?.count).toBe(2)
    expect(overlay.mesh()).not.toBe(first)
  })
})
