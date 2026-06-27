import { describe, it, expect } from 'vitest'
import { relaxToConvergence } from './flexible_relax_solver.js'

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
})
