import { describe, it, expect } from 'vitest'
import { relaxToConvergence, _internals } from './flexible_relax_solver.js'

// Shared parity fixtures + goldens. backend/core/flexible_relax.py is pinned to
// the SAME numbers in tests/test_flexible_relax.py (JS↔Python parity) — change
// here ⇒ change there.
const PIVOT = [0, 0, 0]

// Asymmetric two-tether case → engages the rotation pass (net torque ≠ 0).
const ARMED_ROT = [
  { pM0: [5, 3, 0], pF: [0, 3, 0], contour: 2.0 },
  { pM0: [5, -1, 0], pF: [0, -1, 0], contour: 2.0 },
]
const GOLDEN_ROT = {
  pos: [-3.012416081, -0.03970986, 0],
  quat: [0, 0, 0.006411506, 0.999979446],
}

// Single-tether case → translate-only (a lone tether has no rotation basis).
const ARMED_TRANS = [{ pM0: [5, 0, 0], pF: [0, 0, 0], contour: 3.0 }]

describe('flexible_relax_solver', () => {
  it('converges an asymmetric two-tether hinge to the parity golden (rotation engaged)', () => {
    const state = { pos: [0, 0, 0], quat: [0, 0, 0, 1], pivot: [...PIVOT] }
    const r = relaxToConvergence(state, ARMED_ROT, { translateOnly: false })
    expect(r.moved).toBe(true)
    expect(r.residual).toBeLessThan(0.05) // within the overstretch tolerance
    r.pos.forEach((v, i) => expect(v).toBeCloseTo(GOLDEN_ROT.pos[i], 6))
    r.quat.forEach((v, i) => expect(v).toBeCloseTo(GOLDEN_ROT.quat[i], 6))
    // The rotation pass actually fired (not a pure translation).
    expect(Math.abs(r.quat[2])).toBeGreaterThan(1e-3)
  })

  it('translate-only slides a single overstretched tether to its contour (no rotation)', () => {
    const state = { pos: [0, 0, 0], quat: [0, 0, 0, 1], pivot: [...PIVOT] }
    const r = relaxToConvergence(state, ARMED_TRANS, { translateOnly: true })
    expect(r.moved).toBe(true)
    expect(r.pos[0]).toBeCloseTo(-2.0, 3) // 5 → 3 via a −2 slide along x
    expect(r.quat).toEqual([0, 0, 0, 1]) // no rotation
    // The moved anchor now sits exactly on the contour sphere.
    const chord = Math.hypot(r.pos[0] + 5, r.pos[1], r.pos[2])
    expect(chord).toBeCloseTo(3.0, 3)
  })

  it('is a no-op when nothing is overstretched', () => {
    const state = { pos: [0, 0, 0], quat: [0, 0, 0, 1], pivot: [...PIVOT] }
    const armed = [{ pM0: [1, 0, 0], pF: [0, 0, 0], contour: 3.0 }] // chord 1 ≤ 3
    const r = relaxToConvergence(state, armed, { translateOnly: false })
    expect(r.moved).toBe(false)
    expect(state.pos).toEqual([0, 0, 0])
  })

  it('movable-link chain: the link body swings to follow a displaced near-anchor while staying anchored to the fixed far-anchor', () => {
    // Models the duplex LINK during a drag: its near bond tracks the dragged part A (pF moved
    // away), its far bond stays on the fixed partner B. The link should move so the near bead
    // approaches A, without abandoning B.
    const { applyQuat } = _internals
    const near = { pM0: [1, 0, 0], pF: [3, 0, 0], contour: 1.0 }   // A pulled away → over by 1
    const far = { pM0: [-1, 0, 0], pF: [-1, 0, 0], contour: 1.0 }  // B fixed → already satisfied
    const state = { pos: [0, 0, 0], quat: [0, 0, 0, 1], pivot: [0, 0, 0] }
    const r = relaxToConvergence(state, [near, far], {})
    expect(r.moved).toBe(true)
    // Bead world pos under the solved pose (rotate about the start pos [0,0,0], then translate).
    const bead = (pM0) => {
      const rot = applyQuat(r.quat, pM0)
      return [rot[0] + r.pos[0], rot[1] + r.pos[1], rot[2] + r.pos[2]]
    }
    const d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
    expect(d(bead(near.pM0), near.pF)).toBeLessThan(2.0)  // near bead followed A (started 2 away)
    expect(d(bead(far.pM0), far.pF)).toBeLessThan(1.5)    // far bead stayed anchored near B
  })
})
