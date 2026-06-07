// INVESTIGATION (2026-06-07): characterize when the crossover-selection TubeGeometry
// collapses ("incomplete / flat planes"). Reproduces design_renderer's exact tube
// build with the real THREE math, over the degenerate inputs the arc can feed it.
// This is a throwaway diagnostic test — delete once the cause is fixed + pinned.
import { describe, it, expect } from 'vitest'
import * as THREE from 'three'

const RADIAL = 12
const segs = (n) => Math.max(16, n * 4)

function buildTube(points) {
  const curve = new THREE.CatmullRomCurve3(points)
  const geo   = new THREE.TubeGeometry(curve, segs(points.length), 0.63, RADIAL, false)
  const pos   = geo.attributes.position
  let nan = 0
  for (let i = 0; i < pos.count; i++) {
    if (!Number.isFinite(pos.getX(i)) || !Number.isFinite(pos.getY(i)) || !Number.isFinite(pos.getZ(i))) nan++
  }
  geo.computeBoundingBox()
  const bb = geo.boundingBox
  return {
    radialSegments: geo.parameters.radialSegments,
    tubularSegments: geo.parameters.tubularSegments,
    vertexCount: pos.count,
    nan,
    bboxSize: bb.isEmpty() ? null : bb.getSize(new THREE.Vector3()).toArray().map(v => +v.toFixed(3)),
  }
}

// 21 collinear evenly-spaced points — what t=0 (3D view) produces (control = midpoint).
function collinear() {
  const a = new THREE.Vector3(0, 0, 0), b = new THREE.Vector3(2, 0, 0)
  return Array.from({ length: 21 }, (_, j) => a.clone().lerp(b, j / 20))
}
// 21 identical points — a HIDDEN arc (all verts collapsed to from3D).
function collapsed() {
  return Array.from({ length: 21 }, () => new THREE.Vector3(1, 1, 1))
}
// realistic bowed quadratic arc (what unfold t>0 produces).
function bowed() {
  const a = new THREE.Vector3(0, 0, 0), b = new THREE.Vector3(2, 0, 0)
  const ctrl = new THREE.Vector3(1, 0, 0.6)
  return Array.from({ length: 21 }, (_, j) => {
    const u = j / 20, u2 = 1 - u
    return new THREE.Vector3(
      u2 * u2 * a.x + 2 * u2 * u * ctrl.x + u * u * b.x,
      u2 * u2 * a.y + 2 * u2 * u * ctrl.y + u * u * b.y,
      u2 * u2 * a.z + 2 * u2 * u * ctrl.z + u * u * b.z,
    )
  })
}

describe('crossover tube — degenerate-input characterization', () => {
  // Each asserts nan===0 AND radialSegments===12; a failure prints the real stats.
  it('collinear chord (3D view, t=0)', () => {
    expect(buildTube(collinear())).toEqual({ radialSegments: 12, tubularSegments: 84, vertexCount: 1105, nan: 0, bboxSize: [2, 1.26, 1.26] })
  })
  it('collapsed/hidden arc (21 identical pts) → shrinks to a point, never NaN', () => {
    expect(buildTube(collapsed())).toEqual({ radialSegments: 12, tubularSegments: 84, vertexCount: 1105, nan: 0, bboxSize: [0, 0, 0] })
  })
  it('bowed arc (unfold t>0)', () => {
    expect(buildTube(bowed()).nan).toBe(0)
  })
  it('two leading duplicate points', () => {
    const p = bowed(); p[0] = p[1].clone()
    expect(buildTube(p).nan).toBe(0)
  })
})
