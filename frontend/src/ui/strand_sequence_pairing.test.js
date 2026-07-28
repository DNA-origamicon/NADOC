import { describe, it, expect } from 'vitest'
import {
  normalizeSequence, invalidBases, mismatchFlags, mismatchCount,
  validateStrandSequence, spliceOverhangSegments, decorateSequence,
  preserveReadOnlySpans,
} from './strand_sequence_pairing.js'

// A staple over an 8-bp scaffold (AAAACCCC, FORWARD) running REVERSE 7→0, so the
// partner read in staple order is the scaffold reversed: CCCCAAAA. Its correct
// complement — what the backend derives — is GGGGTTTT.
const PARTNER = 'CCCCAAAA'
const DERIVED = 'GGGGTTTT'

describe('normalizeSequence', () => {
  it('uppercases and strips every kind of whitespace', () => {
    expect(normalizeSequence('  ac gt\n\tac\r\ngt ')).toBe('ACGTACGT')
  })
  it('handles null/undefined', () => {
    expect(normalizeSequence(null)).toBe('')
    expect(normalizeSequence(undefined)).toBe('')
  })
})

describe('invalidBases', () => {
  it('returns nothing for a valid sequence', () => {
    expect(invalidBases('ACGTN')).toEqual([])
  })
  it('de-duplicates and sorts the offenders', () => {
    expect(invalidBases('ACGXTXZ')).toEqual(['X', 'Z'])
  })
  it('ignores whitespace and case', () => {
    expect(invalidBases(' acgt \n')).toEqual([])
  })
})

describe('mismatchFlags', () => {
  it('flags nothing when the sequence is the exact complement', () => {
    expect(mismatchFlags(DERIVED, PARTNER)).toEqual(new Array(8).fill(false))
  })
  it('flags exactly the positions that break Watson-Crick pairing', () => {
    //                       G G G G T T T T   (derived)
    // swap position 0 and 5:A G G G T A T T
    expect(mismatchFlags('AGGGTATT', PARTNER))
      .toEqual([true, false, false, false, false, true, false, false])
  })
  it('treats N on the typed side as a wildcard', () => {
    expect(mismatchFlags('NGGGTTTT', PARTNER)[0]).toBe(false)
  })
  it('treats N on the partner side as a wildcard', () => {
    expect(mismatchFlags('AGGGTTTT', 'NCCCAAAA')[0]).toBe(false)
  })
  it("treats '-' (no partner) as never a mismatch", () => {
    expect(mismatchFlags('AAAA', '----')).toEqual([false, false, false, false])
  })
  it('does not flag positions past the end of the partner string', () => {
    expect(mismatchFlags('GGGGTTTTAAAA', PARTNER).slice(8)).toEqual([false, false, false, false])
  })
  it('returns one flag per typed character, not per partner character', () => {
    expect(mismatchFlags('GGG', PARTNER)).toHaveLength(3)
  })
  it('is case-insensitive on both sides', () => {
    expect(mismatchFlags('ggggtttt', 'ccccaaaa')).toEqual(new Array(8).fill(false))
  })
})

describe('mismatchCount', () => {
  it('counts the flagged positions', () => {
    expect(mismatchCount('AGGGTATT', PARTNER)).toBe(2)
    expect(mismatchCount(DERIVED, PARTNER)).toBe(0)
  })
})

describe('validateStrandSequence', () => {
  it('accepts an exact-length valid sequence', () => {
    expect(validateStrandSequence(DERIVED, 8)).toEqual({ ok: true, error: null })
  })
  it('accepts a fully mismatched sequence — any bases are allowed', () => {
    expect(validateStrandSequence('AAAAAAAA', 8).ok).toBe(true)
  })
  it('accepts N bases', () => {
    expect(validateStrandSequence('NNNNNNNN', 8).ok).toBe(true)
  })
  it('rejects invalid characters and names them', () => {
    const r = validateStrandSequence('ACGTACGX', 8)
    expect(r.ok).toBe(false)
    expect(r.error).toContain('X')
  })
  it('rejects a short sequence and reports both lengths', () => {
    const r = validateStrandSequence('ACGT', 8)
    expect(r.ok).toBe(false)
    expect(r.error).toContain('8')
    expect(r.error).toContain('4')
  })
  it('rejects a long sequence', () => {
    expect(validateStrandSequence('ACGTACGTA', 8).ok).toBe(false)
  })
  it('normalizes before measuring, so whitespace does not fail the length check', () => {
    expect(validateStrandSequence('GGGG TTTT', 8).ok).toBe(true)
  })
})

// 8 duplex nt then an 8-nt overhang tip.
const SEGMENTS = [
  { start: 0, length: 8, kind: 'duplex',   overhang_id: null,   editable: true },
  { start: 8, length: 8, kind: 'overhang', overhang_id: 'oh_a', editable: true },
]

describe('spliceOverhangSegments', () => {
  it('slices the overhang span out of the full strand sequence', () => {
    expect(spliceOverhangSegments('GGGGTTTTCCCCAAAA', SEGMENTS))
      .toEqual([{ overhang_id: 'oh_a', sequence: 'CCCCAAAA' }])
  })
  it('skips a read-only (sub-domain override) overhang', () => {
    const locked = [SEGMENTS[0], { ...SEGMENTS[1], editable: false }]
    expect(spliceOverhangSegments('GGGGTTTTCCCCAAAA', locked)).toEqual([])
  })
  it('returns nothing when the strand has no overhang domain', () => {
    expect(spliceOverhangSegments('GGGGTTTT', [SEGMENTS[0]])).toEqual([])
  })
  it('tolerates a missing segments list', () => {
    expect(spliceOverhangSegments('ACGT', undefined)).toEqual([])
  })
})

describe('decorateSequence', () => {
  it('run-length-merges by segment kind', () => {
    expect(decorateSequence('GGGGTTTTCCCCAAAA', SEGMENTS)).toEqual([
      { text: 'GGGGTTTT', kind: 'duplex',   mismatch: false },
      { text: 'CCCCAAAA', kind: 'overhang', mismatch: false },
    ])
  })
  it('splits a run where a mismatch starts', () => {
    const flags = [false, false, true, false, false, false, false, false]
    expect(decorateSequence('GGGGTTTT', [SEGMENTS[0]], flags)).toEqual([
      { text: 'GG', kind: 'duplex', mismatch: false },
      { text: 'G',  kind: 'duplex', mismatch: true  },
      { text: 'GTTTT', kind: 'duplex', mismatch: false },
    ])
  })
  it('defaults every position to duplex when there are no segments', () => {
    expect(decorateSequence('ACGT', [])).toEqual([
      { text: 'ACGT', kind: 'duplex', mismatch: false },
    ])
  })
})

describe('preserveReadOnlySpans', () => {
  const locked = [SEGMENTS[0], { ...SEGMENTS[1], editable: false }]
  it('restores the locked span from the current sequence', () => {
    expect(preserveReadOnlySpans('AAAAAAAAXXXXXXXX'.replace(/X/g, 'T'),
                                 'GGGGTTTTCCCCAAAA', locked))
      .toBe('AAAAAAAACCCCAAAA')
  })
  it('leaves everything alone when nothing is locked', () => {
    expect(preserveReadOnlySpans('AAAAAAAATTTTTTTT', 'GGGGTTTTCCCCAAAA', SEGMENTS))
      .toBe('AAAAAAAATTTTTTTT')
  })
  it('bails out safely when the lengths differ', () => {
    expect(preserveReadOnlySpans('ACGT', 'GGGGTTTTCCCCAAAA', locked)).toBe('ACGT')
  })
  it('bails out safely when there is no current sequence', () => {
    expect(preserveReadOnlySpans('AAAAAAAATTTTTTTT', null, locked)).toBe('AAAAAAAATTTTTTTT')
  })
})
