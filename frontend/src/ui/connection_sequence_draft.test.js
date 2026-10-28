import { describe, expect, it, vi } from 'vitest'
import { connectionSequenceDraft } from './connection_sequence_draft.js'

function source(a, b, lengthA = 4, lengthB = 4) {
  return { overhangs: [{ id: 'a', sequence: a }, { id: 'b', sequence: b }], strands: [
    { domains: [{ overhang_id: 'a', start_bp: 0, end_bp: lengthA - 1 }] },
    { domains: [{ overhang_id: 'b', start_bp: 0, end_bp: lengthB - 1 }] },
  ] }
}
describe('connection sequence draft', () => {
  it.each([
    ['AAAA', null, 'AAAA', 'TTTT'], [null, 'CCCC', 'GGGG', 'CCCC'],
    ['ACGT', 'ACGT', 'ACGT', 'ACGT'], ['AAAA', 'CCCC', 'AAAA', 'TTTT'],
  ])('prepares the existing complement policy without mutating either endpoint', async (a, b, aa, bb) => {
    const design = source(a, b), before = structuredClone(design), generate = vi.fn()
    expect(await connectionSequenceDraft(design, 'a', 'b', generate)).toEqual({ overhang_a_seq: aa, overhang_b_seq: bb })
    expect(design).toEqual(before)
    expect(generate).not.toHaveBeenCalled()
  })
  it('uses a screened draft when both sequences are missing', async () => {
    const design = source(null, null), generate = vi.fn(async () => 'AAAC')
    expect(await connectionSequenceDraft(design, 'a', 'b', generate)).toEqual({ overhang_a_seq: 'AAAC', overhang_b_seq: 'GTTT' })
    expect(generate).toHaveBeenCalledExactlyOnceWith('a')
    expect(design.overhangs.every(o => o.sequence == null)).toBe(true)
  })
  it('keeps the shorter overhang length and preserves the longer toehold', async () => {
    expect(await connectionSequenceDraft(source('AAAACCCC', null, 8, 4), 'a', 'b', vi.fn()))
      .toEqual({ overhang_a_seq: 'AAAACCCC', overhang_b_seq: 'GGGG' })
  })
  it('leaves the part unchanged when screening fails', async () => {
    const design = source(null, null), before = structuredClone(design)
    await expect(connectionSequenceDraft(design, 'a', 'b', async () => { throw new Error('screen failed') })).rejects.toThrow('screen failed')
    expect(design).toEqual(before)
  })
})
