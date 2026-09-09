import { describe, expect, it } from 'vitest'
import { selectedEndLigationArgs, selectedEndsIncludeNuc } from './force_ligation.js'

const selected = (nuc, copy = 0) => ({ entry: { _copy: copy }, nuc })

describe('selected-end forced ligation', () => {
  it('requires exactly one unambiguous 5′ and one 3′ end on different strands', () => {
    const five = selected({ helix_id: 'h', bp_index: 1, direction: 1, strand_id: 'five', is_five_prime: true })
    const three = selected({ helix_id: 'h', bp_index: 8, direction: 1, strand_id: 'three', is_three_prime: true })
    expect(selectedEndLigationArgs([five, three])).toEqual({
      three_prime_strand_id: 'three', five_prime_strand_id: 'five',
    })
    expect(selectedEndLigationArgs([five])).toBeNull()
    expect(selectedEndLigationArgs([five, { ...three, nuc: { ...three.nuc, is_three_prime: false, is_five_prime: true } }])).toBeNull()
  })

  it('recognizes a raycast nucleotide by its canonical helix/bp/direction identity', () => {
    const nuc = { helix_id: 'h2', bp_index: 12, direction: -1, strand_id: 's', is_three_prime: true }
    expect(selectedEndsIncludeNuc([selected(nuc)], { ...nuc })).toBe(true)
    expect(selectedEndsIncludeNuc([selected(nuc)], { ...nuc, bp_index: 13 })).toBe(false)
  })
})
