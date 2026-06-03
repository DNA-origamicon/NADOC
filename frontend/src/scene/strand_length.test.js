import { describe, it, expect } from 'vitest'
import { strandLengthNt, strandLengthNtFromDesign, strandDomainNt } from './strand_length.js'

const dom = (helix_id, start_bp, end_bp) => ({ helix_id, start_bp, end_bp })
// helixById is a plain object keyed by id; loop_skips: [{bp_index, delta}]
const helixById = (...helices) => Object.fromEntries(helices.map(h => [h.id, h]))

describe('strandDomainNt (no loop/skip)', () => {
  it('sums domain spans inclusively', () => {
    expect(strandDomainNt({ domains: [dom('h1', 0, 9), dom('h1', 0, 4)] })).toBe(15) // 10 + 5
  })
  it('handles reversed domains (abs span)', () => {
    expect(strandDomainNt({ domains: [dom('h1', 9, 0)] })).toBe(10)
  })
  it('returns 0 for no domains', () => {
    expect(strandDomainNt({})).toBe(0)
    expect(strandDomainNt({ domains: [] })).toBe(0)
  })
  it('ignores loop_skips even if helices have them (it is span-only)', () => {
    // strandDomainNt takes no helix info, so deltas can't apply.
    expect(strandDomainNt({ domains: [dom('h1', 0, 9)] })).toBe(10)
  })
})

describe('strandLengthNt (loop/skip-aware)', () => {
  it('equals the span sum when there are no loop_skips', () => {
    const hb = helixById({ id: 'h1' })
    expect(strandLengthNt({ domains: [dom('h1', 0, 9)] }, hb)).toBe(10)
  })
  it('adds positive loop deltas inside the domain range', () => {
    const hb = helixById({ id: 'h1', loop_skips: [{ bp_index: 5, delta: 2 }] })
    expect(strandLengthNt({ domains: [dom('h1', 0, 9)] }, hb)).toBe(12) // 10 + 2
  })
  it('subtracts skip deltas and ignores those outside the range', () => {
    const hb = helixById({ id: 'h1', loop_skips: [{ bp_index: 3, delta: -1 }, { bp_index: 50, delta: -9 }] })
    expect(strandLengthNt({ domains: [dom('h1', 0, 9)] }, hb)).toBe(9) // 10 - 1, the bp 50 skip is out of [0,9]
  })
  it('handles reversed domains for the lo/hi window', () => {
    const hb = helixById({ id: 'h1', loop_skips: [{ bp_index: 5, delta: 2 }] })
    expect(strandLengthNt({ domains: [dom('h1', 9, 0)] }, hb)).toBe(12)
  })
  it('returns 0 for no domains', () => {
    expect(strandLengthNt({}, {})).toBe(0)
  })
})

describe('strandLengthNtFromDesign === strandLengthNt with built lookup', () => {
  it('matches the helixById form for the same data', () => {
    const helices = [{ id: 'h1', loop_skips: [{ bp_index: 5, delta: 2 }] }, { id: 'h2' }]
    const strand = { domains: [dom('h1', 0, 9), dom('h2', 0, 4)] }
    const viaDesign = strandLengthNtFromDesign(strand, { helices })
    const viaLookup = strandLengthNt(strand, helixById(...helices))
    expect(viaDesign).toBe(viaLookup)
    expect(viaDesign).toBe(17) // (10 + 2) + 5
  })
  it('tolerates a missing/empty design', () => {
    expect(strandLengthNtFromDesign({ domains: [dom('h1', 0, 9)] }, undefined)).toBe(10)
  })
})
