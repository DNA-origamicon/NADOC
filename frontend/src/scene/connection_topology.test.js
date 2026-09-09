import { describe, expect, it } from 'vitest'
import { sameConnectionTopology, sameForcedLigationTopology } from './connection_topology.js'

const ligation = (extra = null) => ({
  id: 'fl1',
  three_prime_helix_id: 'h1', three_prime_bp: 9, three_prime_direction: 'FORWARD',
  five_prime_helix_id: 'h2', five_prime_bp: 2, five_prime_direction: 'REVERSE',
  extra_bases: extra, is_periodic_seam: false,
})

describe('rendered connection topology signatures', () => {
  it('detects a newly created forced ligation even when ordinary crossovers are unchanged', () => {
    const before = { crossovers: [], forced_ligations: [] }
    const after = { crossovers: [], forced_ligations: [ligation()] }
    expect(sameForcedLigationTopology(before, after)).toBe(false)
    expect(sameConnectionTopology(before, after)).toBe(false)
  })

  it('detects forced-ligation endpoint and inserted-base changes', () => {
    expect(sameForcedLigationTopology(
      { forced_ligations: [ligation()] },
      { forced_ligations: [{ ...ligation(), five_prime_bp: 3 }] },
    )).toBe(false)
    expect(sameForcedLigationTopology(
      { forced_ligations: [ligation()] },
      { forced_ligations: [ligation('TT')] },
    )).toBe(false)
  })
})
