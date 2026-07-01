import { describe, it, expect } from 'vitest'
import { skipMapFromHelices, sequenceColumns } from './sequence_layout.js'

const fwd = (helix_id, start_bp, end_bp) => ({ helix_id, start_bp, end_bp, direction: 'FORWARD' })
const rev = (helix_id, start_bp, end_bp) => ({ helix_id, start_bp, end_bp, direction: 'REVERSE' })

describe('skipMapFromHelices', () => {
  it('keys nonzero deltas by helix+bp, drops zeros/empties', () => {
    const m = skipMapFromHelices([
      { id: 'h0', loop_skips: [{ bp_index: 3, delta: -1 }, { bp_index: 7, delta: 1 }] },
      { id: 'h1', loop_skips: [] },
      { id: 'h2' },
    ])
    // separator-agnostic: exactly the two nonzero deltas survive, keyed on h0's bps.
    expect(m.size).toBe(2)
    expect([...m.values()].sort()).toEqual([-1, 1])
    expect([...m.keys()].every(k => k.startsWith('h0'))).toBe(true)
    const byBp = new Map([...m].map(([k, v]) => [k.replace(/^h0\D+/, ''), v]))
    expect(byBp.get('3')).toBe(-1)
    expect(byBp.get('7')).toBe(1)
  })
})

describe('sequenceColumns', () => {
  it('with no skips, seqIndex equals the geometric column offset', () => {
    const strand = { domains: [fwd('h0', 0, 4)] }
    const cols = [...sequenceColumns(strand, new Map())]
    expect(cols.map(c => [c.bp, c.seqIndex])).toEqual([[0, 0], [1, 1], [2, 2], [3, 3], [4, 4]])
  })

  it('omits a skipped column and keeps the compressed index contiguous after it', () => {
    // skip at bp 2: the stored sequence is "b0 b1 b3 b4" (4 chars for 5 columns)
    const strand = { domains: [fwd('h0', 0, 4)] }
    const skipMap = skipMapFromHelices([{ id: 'h0', loop_skips: [{ bp_index: 2, delta: -1 }] }])
    const cols = [...sequenceColumns(strand, skipMap)]
    // column bp=2 is gone; bp=3 draws sequence[2], bp=4 draws sequence[3] (shifted vs the old bug)
    expect(cols.map(c => [c.bp, c.seqIndex])).toEqual([[0, 0], [1, 1], [3, 2], [4, 3]])
  })

  it('advances the index by 2 at a loop column so following columns stay aligned', () => {
    const strand = { domains: [fwd('h0', 0, 3)] }
    const skipMap = skipMapFromHelices([{ id: 'h0', loop_skips: [{ bp_index: 1, delta: 1 }] }])
    const cols = [...sequenceColumns(strand, skipMap)]
    // bp=1 is a loop (2 nt): it occupies seqIndex 1, and bp=2 jumps to seqIndex 3
    expect(cols.map(c => [c.bp, c.seqIndex, c.delta])).toEqual(
      [[0, 0, 0], [1, 1, 1], [2, 3, 0], [3, 4, 0]])
    // nBases exposes both loop nucleotides (seq[1], seq[2]) so the renderer draws both
    expect(cols.map(c => c.nBases)).toEqual([1, 2, 1, 1])
  })

  it('walks a REVERSE domain 5’->3’ (descending bp) with correct compressed indices', () => {
    const strand = { domains: [rev('h0', 4, 0)] }
    const skipMap = skipMapFromHelices([{ id: 'h0', loop_skips: [{ bp_index: 3, delta: -1 }] }])
    const cols = [...sequenceColumns(strand, skipMap)]
    // 5'->3' is bp 4,3,2,1,0; skip at bp 3 removed -> 4 present columns, contiguous indices
    expect(cols.map(c => [c.bp, c.seqIndex])).toEqual([[4, 0], [2, 1], [1, 2], [0, 3]])
  })

  it('carries the compressed index across multiple domains of one strand', () => {
    const strand = { domains: [fwd('h0', 0, 2), fwd('h1', 0, 2)] }
    const skipMap = skipMapFromHelices([{ id: 'h0', loop_skips: [{ bp_index: 1, delta: -1 }] }])
    const cols = [...sequenceColumns(strand, skipMap)]
    // h0: bp0->idx0, bp1 skipped, bp2->idx1 ; h1 continues: bp0->idx2, bp1->idx3, bp2->idx4
    expect(cols.map(c => [c.helixId, c.bp, c.seqIndex])).toEqual([
      ['h0', 0, 0], ['h0', 2, 1], ['h1', 0, 2], ['h1', 1, 3], ['h1', 2, 4],
    ])
    expect(cols.map(c => c.domCol)).toEqual([0, 1, 0, 1, 2]) // domCol resets per domain
  })
})
