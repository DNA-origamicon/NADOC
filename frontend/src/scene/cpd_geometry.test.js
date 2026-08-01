// cpd_geometry.test.js
//
// The load-bearing test here is the CROSS-LANGUAGE CONTRACT: this module and
// backend/core/cpd_metrics.py both compute the weld reaction coordinates, and both assert
// against tests/fixtures/cpd_reference_cases.json. The viewer must compute from the
// coordinates it is already rendering (the MD display affine is handed over, not
// re-derived), which is why a second implementation exists at all — so it has to be
// pinned to the first, or the number on screen silently diverges from the analysis.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import {
  K1, K2, D0, N0, REACTIVE_D_NM,
  angularSeparationDeg, kimmdyRate, dihedralDeg, bondMidpoint,
  weldGeometry, readSerial, readWeldGeometry, weldColor, formatWeldReadout,
} from './cpd_geometry.js'

const here = dirname(fileURLToPath(import.meta.url))
const REF = JSON.parse(
  readFileSync(resolve(here, '../../../tests/fixtures/cpd_reference_cases.json'), 'utf8'))

describe('cross-language contract with backend/core/cpd_metrics.py', () => {
  it('constants match the shared fixture', () => {
    expect(K1).toBe(REF.constants.K1)
    expect(K2).toBe(REF.constants.K2)
    expect(D0).toBe(REF.constants.D0)
    expect(N0).toBe(REF.constants.N0)
  })

  for (const c of REF.cases) {
    it(`reproduces reference case: ${c.name}`, () => {
      const g = weldGeometry(c.c5_a, c.c6_a, c.c5_b, c.c6_b)
      expect(g.dNm).toBeCloseTo(c.d_nm, 9)
      expect(g.etaDeg).toBeCloseTo(c.eta_deg, 6)
      expect(g.k).toBeCloseTo(c.k, 9)
      expect(g.reactive).toBe(c.reactive)
    })
  }
})

describe('geometry', () => {
  it('rate is 1.0 at the product geometry', () => {
    expect(kimmdyRate(D0, N0)).toBeCloseTo(1.0, 12)
  })

  it('rate falls off with distance and with twist', () => {
    expect(kimmdyRate(0.34, 0)).toBeGreaterThan(kimmdyRate(0.6, 0))
    expect(kimmdyRate(0.34, 0)).toBeGreaterThan(kimmdyRate(0.34, 90))
  })

  it('angular separation takes the short way round', () => {
    expect(angularSeparationDeg(-175)).toBeCloseTo(168.256348, 5)
    expect(angularSeparationDeg(N0)).toBeCloseTo(0, 12)
    // the naive abs() the upstream model uses would give 191.7 here
    expect(Math.abs(-175 - N0)).toBeGreaterThan(angularSeparationDeg(-175))
  })

  it('angular separation never exceeds 180', () => {
    for (let e = -180; e <= 180; e += 0.5) {
      expect(angularSeparationDeg(e)).toBeLessThanOrEqual(180 + 1e-9)
    }
  })

  it('dihedral of a planar cis arrangement is zero', () => {
    expect(dihedralDeg([0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 1, 0])).toBeCloseTo(0, 9)
  })

  it('dihedral sign flips with the mirror image', () => {
    const a = dihedralDeg([0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 0.5, 0.5])
    const b = dihedralDeg([0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 0.5, -0.5])
    expect(a).toBeCloseTo(-b, 9)
    expect(Math.abs(a)).toBeGreaterThan(1e-6)
  })

  it('dihedral of degenerate input does not return NaN', () => {
    expect(dihedralDeg([0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0])).toBe(0)
  })

  it('bond midpoint is the average of C5 and C6', () => {
    expect(bondMidpoint([0, 0, 0], [0.14, 0, 0])).toEqual([0.07, 0, 0])
  })

  it('d_mid is the midpoint distance, NOT the C5-C5 distance', () => {
    // flipped partner bond: midpoints stay 0.34 apart while C5-C5 does not
    const g = weldGeometry([0, 0, 0], [0.139, 0, 0], [0.139, 0, 0.34], [0, 0, 0.34])
    expect(g.dNm).toBeCloseTo(0.34, 9)
    const c5c5 = Math.hypot(0.139, 0, 0.34)
    expect(c5c5).toBeGreaterThan(0.36)
  })
})

describe('readSerial', () => {
  const pos = new Float32Array([0, 0, 0, 1, 2, 3, 4, 5, 6])

  it('reads xyz at serial*3', () => {
    expect(readSerial(pos, 1)).toEqual([1, 2, 3])
    expect(readSerial(pos, 2)).toEqual([4, 5, 6])
  })

  it('returns null out of range rather than reading past the end', () => {
    expect(readSerial(pos, 3)).toBeNull()
    expect(readSerial(pos, -1)).toBeNull()
    expect(readSerial(pos, 1.5)).toBeNull()
    expect(readSerial(null, 0)).toBeNull()
  })

  it('returns null for non-finite coordinates', () => {
    expect(readSerial(new Float32Array([NaN, 0, 0]), 0)).toBeNull()
  })
})

describe('readWeldGeometry', () => {
  // two parallel C5=C6 bonds 0.34 nm apart, serials 0..3
  const positions = new Float32Array([
    0, 0, 0, // serial 0 — C5 a
    0.139, 0, 0, // serial 1 — C6 a
    0, 0, 0.34, // serial 2 — C5 b
    0.139, 0, 0.34, // serial 3 — C6 b
  ])
  const pair = {
    id: 'x:0~y:0', label: 'x[k=0]~y[k=0]',
    c5_a: 0, c6_a: 1, c5_b: 2, c6_b: 3, serials_resolved: true,
  }

  it('computes geometry from the rendered frame', () => {
    const g = readWeldGeometry(pair, positions)
    // Rendered positions are Float32Array (~7 significant digits), so 6 dp is the real
    // precision floor here -- and it is ~4 orders below the 0.01 Angstrom we display.
    expect(g.dNm).toBeCloseTo(0.34, 6)
    expect(g.etaDeg).toBeCloseTo(0, 6)
    expect(g.id).toBe('x:0~y:0')
    expect(g.label).toBe('x[k=0]~y[k=0]')
  })

  it('returns null for an unresolved pair', () => {
    expect(readWeldGeometry({ ...pair, serials_resolved: false }, positions)).toBeNull()
  })

  it('returns null when an atom is missing from this frame', () => {
    expect(readWeldGeometry({ ...pair, c6_b: 99 }, positions)).toBeNull()
  })

  it('returns null for a null pair', () => {
    expect(readWeldGeometry(null, positions)).toBeNull()
  })
})

describe('weldColor', () => {
  it('is red at k=0 and green at k=1', () => {
    expect(weldColor(0)).toBe(0xd92626)
    const green = weldColor(1)
    expect((green >> 8) & 0xff).toBeGreaterThan((green >> 16) & 0xff) // G > R
  })

  it('clamps out-of-range k instead of producing an invalid colour', () => {
    expect(weldColor(-5)).toBe(weldColor(0))
    expect(weldColor(5)).toBe(weldColor(1))
  })

  it('always returns a valid 24-bit colour', () => {
    for (let k = 0; k <= 1; k += 0.05) {
      const c = weldColor(k)
      expect(Number.isInteger(c)).toBe(true)
      expect(c).toBeGreaterThanOrEqual(0)
      expect(c).toBeLessThanOrEqual(0xffffff)
    }
  })
})

describe('formatWeldReadout', () => {
  it('reports Angstrom, degrees and k', () => {
    const s = formatWeldReadout(weldGeometry([0, 0, 0], [0.139, 0, 0], [0, 0, 0.34], [0.139, 0, 0.34]))
    expect(s).toContain('3.40 Å')
    expect(s).toContain('η +0°')
    expect(s).toContain('k 0.418')
  })

  it('flags the reactive corner', () => {
    const near = weldGeometry([0, 0, 0], [0.139, 0, 0], [0, 0, 0.30], [0.139, 0, 0.30])
    expect(near.dNm).toBeLessThan(REACTIVE_D_NM)
    expect(formatWeldReadout(near)).toContain('reactive')
  })

  it('degrades to a dash with no geometry', () => {
    expect(formatWeldReadout(null)).toBe('weld: —')
  })
})
