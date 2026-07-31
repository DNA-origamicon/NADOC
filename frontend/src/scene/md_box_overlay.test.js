import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { boxEdgePositions, BOX_EDGES, initMdBoxOverlay } from './md_box_overlay.js'

/** The unit cube's 8 corners in the backend's corner order: bit a of the index
 *  selects the + half-length on axis a. */
const UNIT = Float32Array.from([
  0, 0, 0,  1, 0, 0,  0, 1, 0,  1, 1, 0,
  0, 0, 1,  1, 0, 1,  0, 1, 1,  1, 1, 1,
])

describe('BOX_EDGES', () => {
  it('is the 12 cuboid edges', () => {
    expect(BOX_EDGES).toHaveLength(12)
    expect(new Set(BOX_EDGES.map((e) => e.join(','))).size).toBe(12)
  })

  // Two corners share an edge exactly when their indices differ in ONE bit — that
  // is what makes the corner ordering a contract between backend and frontend
  // rather than a convention. A face diagonal differs in two bits.
  it('joins only corners differing in exactly one bit', () => {
    for (const [a, b] of BOX_EDGES) {
      const diff = a ^ b
      expect(diff & (diff - 1)).toBe(0)   // a power of two → one bit set
      expect(diff).not.toBe(0)
    }
  })

  it('touches every corner three times', () => {
    const deg = new Array(8).fill(0)
    for (const [a, b] of BOX_EDGES) { deg[a]++; deg[b]++ }
    expect(deg).toEqual(new Array(8).fill(3))
  })
})

describe('boxEdgePositions', () => {
  it('expands 8 corners into 24 line vertices', () => {
    const out = boxEdgePositions(UNIT)
    expect(out).toBeInstanceOf(Float32Array)
    expect(out.length).toBe(72)
  })

  it('produces unit-length edges for the unit cube', () => {
    const out = boxEdgePositions(UNIT)
    for (let e = 0; e < 12; e++) {
      const o = e * 6
      const dx = out[o + 3] - out[o]
      const dy = out[o + 4] - out[o + 1]
      const dz = out[o + 5] - out[o + 2]
      expect(Math.hypot(dx, dy, dz)).toBeCloseTo(1, 6)
    }
  })

  // Four edges along each axis, so a cuboid reads as a cuboid rather than a
  // tangle of diagonals.
  it('lays four edges along each axis', () => {
    const out = boxEdgePositions(UNIT)
    const perAxis = [0, 0, 0]
    for (let e = 0; e < 12; e++) {
      const o = e * 6
      const d = [out[o + 3] - out[o], out[o + 4] - out[o + 1], out[o + 5] - out[o + 2]]
      perAxis[d.findIndex((v) => Math.abs(v) > 0.5)]++
    }
    expect(perAxis).toEqual([4, 4, 4])
  })

  it('handles a rotated (non-axis-aligned) cell', () => {
    // The served cell IS rotated — frames are Kabsch-aligned to the design pose.
    const q = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(1, 1, 0).normalize(), 0.7)
    const rot = new Float32Array(24)
    const v = new THREE.Vector3()
    for (let i = 0; i < 8; i++) {
      v.set(UNIT[i * 3], UNIT[i * 3 + 1], UNIT[i * 3 + 2]).applyQuaternion(q)
      rot[i * 3] = v.x; rot[i * 3 + 1] = v.y; rot[i * 3 + 2] = v.z
    }
    const out = boxEdgePositions(rot)
    for (let e = 0; e < 12; e++) {
      const o = e * 6
      expect(Math.hypot(out[o + 3] - out[o], out[o + 4] - out[o + 1],
        out[o + 5] - out[o + 2])).toBeCloseTo(1, 5)
    }
  })

  it('writes into a caller-supplied buffer instead of allocating', () => {
    const buf = new Float32Array(72)
    expect(boxEdgePositions(UNIT, buf)).toBe(buf)
    expect(buf[3]).toBeCloseTo(1, 6)
  })

  it('rejects a short or missing payload', () => {
    expect(boxEdgePositions(null)).toBeNull()
    expect(boxEdgePositions(new Float32Array(23))).toBeNull()
  })
})

describe('initMdBoxOverlay', () => {
  it('adds one hidden LineSegments at init', () => {
    const scene = new THREE.Scene()
    initMdBoxOverlay(scene)
    const l = scene.children.find((o) => o.name === 'mdPeriodicBox')
    expect(l).toBeInstanceOf(THREE.LineSegments)
    expect(l.visible).toBe(false)
    expect(l.frustumCulled).toBe(false)   // the cell encloses the camera target
  })

  it('shows the cell and writes the edge buffer', () => {
    const scene = new THREE.Scene()
    const box = initMdBoxOverlay(scene)
    expect(box.setCorners(UNIT)).toBe(true)
    expect(box.isVisible()).toBe(true)
    const l = scene.children.find((o) => o.name === 'mdPeriodicBox')
    expect(l.geometry.attributes.position.array[3]).toBeCloseTo(1, 6)
  })

  // Under NPT the cell rescales every frame, so setCorners is a per-frame call —
  // it must reuse the geometry, not build a new one.
  it('reuses one geometry across frames', () => {
    const scene = new THREE.Scene()
    const box = initMdBoxOverlay(scene)
    const l = scene.children.find((o) => o.name === 'mdPeriodicBox')
    box.setCorners(UNIT)
    const geo = l.geometry
    const arr = l.geometry.attributes.position.array
    const grown = UNIT.map((v) => v * 2)
    box.setCorners(grown)
    expect(l.geometry).toBe(geo)
    expect(l.geometry.attributes.position.array).toBe(arr)
    expect(arr[3]).toBeCloseTo(2, 6)
  })

  it('hides rather than throwing on a bad payload', () => {
    const scene = new THREE.Scene()
    const box = initMdBoxOverlay(scene)
    box.setCorners(UNIT)
    expect(box.setCorners(new Float32Array(4))).toBe(false)
    expect(box.isVisible()).toBe(false)
  })

  it('hide() and dispose()', () => {
    const scene = new THREE.Scene()
    const box = initMdBoxOverlay(scene)
    box.setCorners(UNIT)
    box.hide()
    expect(box.isVisible()).toBe(false)
    box.dispose()
    expect(scene.children.find((o) => o.name === 'mdPeriodicBox')).toBeUndefined()
  })
})
