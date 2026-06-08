/**
 * Pure-helper tests for scene/force_crossover_tool.js — the 3D forced-ligation
 * tool's end-polarity / pairing / arc math. Real module + real THREE (no mocks),
 * mirroring cluster_gizmo.test.js. Oracles come from the spec, not the code.
 */
import { describe, it, expect } from 'vitest'
import { endRole, isValidPair, ligationArgs, crossoverArcPoints } from './force_crossover_tool.js'

const three = (sid) => ({ strand_id: sid, is_three_prime: true })
const five  = (sid) => ({ strand_id: sid, is_five_prime: true })

describe('endRole', () => {
  it('reads 3p / 5p from the nucleotide flags', () => {
    expect(endRole({ is_three_prime: true })).toBe('3p')
    expect(endRole({ is_five_prime: true })).toBe('5p')
  })
  it('null for a mid-strand bead or missing nuc', () => {
    expect(endRole({})).toBe(null)
    expect(endRole(null)).toBe(null)
  })
  it('null for an ambiguous single-bead strand (both ends)', () => {
    expect(endRole({ is_three_prime: true, is_five_prime: true })).toBe(null)
  })
})

describe('isValidPair', () => {
  it('opposite polarity on different strands → valid', () => {
    expect(isValidPair(three('A'), five('B'))).toBe(true)
    expect(isValidPair(five('A'), three('B'))).toBe(true)
  })
  it('same polarity → invalid', () => {
    expect(isValidPair(three('A'), three('B'))).toBe(false)
    expect(isValidPair(five('A'), five('B'))).toBe(false)
  })
  it('same strand → invalid (no self-circularization)', () => {
    expect(isValidPair(three('A'), five('A'))).toBe(false)
  })
  it('a non-end bead → invalid', () => {
    expect(isValidPair(three('A'), { strand_id: 'B' })).toBe(false)
  })
})

describe('ligationArgs', () => {
  it('maps 3p→three_prime, 5p→five_prime regardless of click order', () => {
    const a = ligationArgs(three('A'), five('B'))
    expect(a).toEqual({ three_prime_strand_id: 'A', five_prime_strand_id: 'B' })
    // Clicked the 5′ first, the 3′ second → same backend args.
    const b = ligationArgs(five('B'), three('A'))
    expect(b).toEqual({ three_prime_strand_id: 'A', five_prime_strand_id: 'B' })
  })
})

describe('crossoverArcPoints', () => {
  const nucA = { backbone_position: [0, 0, 0], axis_tangent: [0, 0, 1], base_normal: [0, 1, 0] }
  const nucB = { backbone_position: [2, 0, 0], axis_tangent: [0, 0, 1], base_normal: [0, 1, 0] }

  it('returns segs+1 samples, anchored at the two endpoints', () => {
    const pts = crossoverArcPoints(nucA, nucB, 16)
    expect(pts).toHaveLength(17)
    expect(pts[0].toArray()).toEqual([0, 0, 0])
    expect(pts[16].toArray().map(v => +v.toFixed(6))).toEqual([2, 0, 0])
  })

  it('bows off the chord (not a straight line)', () => {
    const pts = crossoverArcPoints(nucA, nucB, 16)
    // Midpoint sample is pulled perpendicular to the chord (bow = chord × axis).
    expect(Math.abs(pts[8].y)).toBeGreaterThan(0.1)
  })
})
