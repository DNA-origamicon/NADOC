import { describe, it, expect } from 'vitest'
import { _physLen, _axisPoint } from './domain_ends.js'

const RISE = 0.334

describe('_physLen (blunt-end disk→t span)', () => {
  it('uses the topological length_bp, not the chord between deformed endpoints', () => {
    // A BENT helix: arc = length_bp*RISE, but the straight-line chord is much shorter.
    // The chord-derived count would be wrong; length_bp+1 is correct.
    const h = { length_bp: 420 }
    const chord = 114.1          // << arc (≈140 nm) for a strongly bent helix
    expect(_physLen(h, chord)).toBe(421)
    // A straight helix: chord == arc, so length_bp+1 equals the old chord estimate.
    expect(_physLen({ length_bp: 420 }, 420 * RISE)).toBe(421)
  })

  it('falls back to the chord estimate when length_bp is missing', () => {
    expect(_physLen({}, 10 * RISE)).toBe(11)
  })
})

describe('_axisPoint on a BENT helix', () => {
  // An L-shaped (90°) centre-line: 5 bp up +Z, then 5 bp along +X. Arc = 10 bp; the
  // straight chord between the endpoints is only ~7.1 bp, so a chord-derived physLen
  // would push the end-disk t past 1 and float the ring beyond the real bent tip.
  const samples = []
  for (let i = 0; i <= 5; i++) samples.push([0, 0, i * RISE])          // bp 0..5 up +Z
  for (let i = 1; i <= 5; i++) samples.push([i * RISE, 0, 5 * RISE])   // bp 6..10 along +X
  const axDef = { start: samples[0], end: samples[samples.length - 1], samples }
  const h = { length_bp: 10, bp_start: 0 }

  it('places the far-end disk AT the bent tip, not overshooting past it', () => {
    const tip = samples[samples.length - 1]                 // [1.67, 0, 1.67]
    const p = _axisPoint(h, axDef, 10)                      // far-end disk = bp_start+length_bp
    expect(p.x).toBeCloseTo(tip[0], 5)
    expect(p.z).toBeCloseTo(tip[2], 5)
    // The pre-fix (chord-derived) physLen would have overshot well along +X (x ≫ tip).
    expect(p.x).toBeLessThan(tip[0] + 0.1)
  })

  it('places a mid disk on the arc, not on the chord', () => {
    const p = _axisPoint(h, axDef, 5)   // bp 5 = the corner of the L
    expect(p.x).toBeCloseTo(0, 5)
    expect(p.z).toBeCloseTo(5 * RISE, 5)
  })
})
