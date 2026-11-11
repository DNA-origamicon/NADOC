import { describe, expect, it } from 'vitest'
import { pairedCrossoverBows } from './paired_crossover_bows.js'

// Topology-only records: no molecular geometry or serialized structures.
function pair() {
  return {
    strands: [
      { domains: [
        { helix_id: 'a', start_bp: 0, end_bp: 6, direction: 'FORWARD' },
        { helix_id: 'b', start_bp: 6, end_bp: 0, direction: 'REVERSE' },
      ] },
      { domains: [
        { helix_id: 'b', start_bp: 13, end_bp: 7, direction: 'REVERSE' },
        { helix_id: 'a', start_bp: 7, end_bp: 13, direction: 'FORWARD' },
      ] },
    ],
    forced_ligations: [
      { id: 'low', three_prime_helix_id: 'a', three_prime_bp: 6, three_prime_direction: 'FORWARD',
        five_prime_helix_id: 'b', five_prime_bp: 6, five_prime_direction: 'REVERSE' },
      { id: 'high', three_prime_helix_id: 'b', three_prime_bp: 7, three_prime_direction: 'REVERSE',
        five_prime_helix_id: 'a', five_prime_bp: 7, five_prime_direction: 'FORWARD' },
    ],
  }
}

describe('paired crossover schematic bows', () => {
  it('assigns lower left and upper right independently of record order', () => {
    const design = pair(), before = JSON.stringify(design)
    expect([...pairedCrossoverBows(design)]).toEqual([['low', -1], ['high', 1]])
    expect(JSON.stringify(design)).toBe(before)
    design.strands.reverse(); design.forced_ligations.reverse()
    expect(pairedCrossoverBows(design).get('low')).toBe(-1)
    expect(pairedCrossoverBows(design).get('high')).toBe(1)
  })
  it('recognizes a standard partner regardless of stored A/B order', () => {
    const design = pair()
    design.forced_ligations.pop()
    design.crossovers = [{ id: 'high', half_a: { helix_id: 'a', index: 7, strand: 'FORWARD' },
      half_b: { helix_id: 'b', index: 7, strand: 'REVERSE' } }]
    expect(pairedCrossoverBows(design).get('low')).toBe(-1)
  })
  it('leaves an unpaired junction unclassified', () => {
    const design = pair(); design.strands.pop()
    expect(pairedCrossoverBows(design).size).toBe(0)
  })
  it('requires the same BP ordering on both helices', () => {
    const design = pair()
    design.strands[1].domains[1].start_bp = 5
    design.forced_ligations[1].five_prime_bp = 5
    expect(pairedCrossoverBows(design).size).toBe(0)
  })
  it('does not classify periodic seam connections as local pairs', () => {
    const design = pair(); design.forced_ligations[0].is_periodic_seam = true
    expect(pairedCrossoverBows(design).size).toBe(0)
  })
  it('leaves multiply matched pairs unclassified', () => {
    const design = pair()
    design.strands.push(structuredClone(design.strands[1]))
    expect(pairedCrossoverBows(design).size).toBe(0)
  })
})
