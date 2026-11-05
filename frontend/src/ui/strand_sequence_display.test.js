import { describe, it, expect } from 'vitest'
import { strandSequenceDisplay, renderStrandSequence, strandLength } from './strand_sequence_display.js'

import { junctionFixture } from '../test-helpers/strand_junction_fixture.js'

describe('copyable strand sequences with crossover arcs', () => {
  it('retains base ownership before sequences are assigned', () => {
    const { strand, design } = junctionFixture()
    strand.sequence = null
    design.crossovers = []
    const display = strandSequenceDisplay(strand, design)
    expect(display.text).toBe('')
    expect(display.runs.flatMap(r => r.keys)).toContain('b:2:REVERSE')
  })

  it.each([false, true])('includes junction bases in text, length and base highlighting (forced=%s)', forced => {
    const { strand, design } = junctionFixture(forced)
    const display = strandSequenceDisplay(strand, design)
    expect(display.text).toBe('ACGATTTTTGCA')
    expect(strandLength(strand, design)).toBe(12)
    const span = document.createElement('span')
    renderStrandSequence(span, display, new Set([`__xb__:${forced ? 'fl:1' : 'xo'}:0`, 'b:2:REVERSE']))
    expect(span.textContent).toBe(display.text)
    expect(span.querySelectorAll('.sheet-seq-extra')).toHaveLength(1)
    expect(span.querySelector('.sheet-seq-extra').textContent).toBe('ATTTTT')
    expect([...span.querySelectorAll('mark')].map(m => m.textContent)).toEqual(['A', 'G'])
  })

  it('places inserts after loop/skip-aware domain sequence and checks both endpoints', () => {
    const { strand, design } = junctionFixture()
    design.helices[0].loop_skips = [{ bp_index: 0, delta: 2 }, { bp_index: 1, delta: -1 }]
    strand.sequence = 'ATCGGCA'
    expect(strandSequenceDisplay(strand, design).text).toBe('ATCGATTTTTGCA')
    expect(strandLength(strand, design)).toBe(13)
    design.crossovers[0].half_a.index = 1
    expect(strandSequenceDisplay(strand, design).text).toBe('ATCGGCA')
  })

  it('keeps terminal extension notation and separate overhang columns', () => {
    const { strand, design } = junctionFixture()
    strand.domains.unshift({ helix_id: 'a', start_bp: 3, end_bp: 4, direction: 'FORWARD', overhang_id: 'oh' })
    strand.sequence = 'TT' + strand.sequence
    design.extensions = [{ strand_id: 's', end: 'five_prime', sequence: 'CC', modification: 'cy3' }]
    expect(strandSequenceDisplay(strand, design).text).toBe('[CC/CY3]ACGATTTTTGCA')
  })

  it('includes a circular closing junction once', () => {
    const { strand, design } = junctionFixture(true)
    design.forced_ligations.push({ id: 'close', extra_bases: 'TA',
      three_prime_helix_id: 'b', three_prime_bp: 0, three_prime_direction: 'REVERSE',
      five_prime_helix_id: 'a', five_prime_bp: 0, five_prime_direction: 'FORWARD' })
    expect(strandSequenceDisplay(strand, design).text).toBe('ACGATTTTTGCATA')
    expect(strandLength(strand, design)).toBe(14)
  })

  it.each(['FORWARD', 'REVERSE'])('includes a ligation inside a merged %s domain', direction => {
    const { strand, design } = junctionFixture(true)
    const forward = direction === 'FORWARD'
    strand.domains = [{ helix_id: 'a', start_bp: forward ? 0 : 5, end_bp: forward ? 5 : 0, direction }]
    Object.assign(design.forced_ligations[0], {
      three_prime_bp: forward ? 2 : 3, three_prime_direction: direction,
      five_prime_helix_id: 'a', five_prime_bp: forward ? 3 : 2, five_prime_direction: direction,
    })
    expect(strandSequenceDisplay(strand, design).text).toBe('ACGATTTTTGCA')
    expect(strandLength(strand, design)).toBe(12)
  })
})
