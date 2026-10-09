import { describe, expect, it } from 'vitest'
import { sameConnectionTopology, sameForcedLigationTopology } from './connection_topology.js'

const ligation = (extra = null) => ({
  id: 'fl1',
  three_prime_helix_id: 'h1', three_prime_bp: 9, three_prime_direction: 'FORWARD',
  five_prime_helix_id: 'h2', five_prime_bp: 2, five_prime_direction: 'REVERSE',
  extra_bases: extra, is_periodic_seam: false,
})

describe('rendered connection topology signatures', () => {
  it('refreshes seam bonds on circle Apply/Undo/Redo, but not unrelated bend edits', () => {
    const seam = { ...ligation(), is_periodic_seam: true }
    const open = { forced_ligations: [seam], deformations: [] }
    const bend = { type: 'bend', plane_a_bp: 0, plane_b_bp: 9,
      params: { polymer_circle_count: 1, curvature_deg_per_bp: 36 } }
    const closed = { ...open, deformations: [bend] }
    expect(sameConnectionTopology(open, closed)).toBe(false)
    expect(sameConnectionTopology(closed, open)).toBe(false)
    expect(sameConnectionTopology(closed, { ...closed, deformations: [{ ...bend,
      params: { ...bend.params, direction_deg: 45 } }] })).toBe(true)
    expect(sameConnectionTopology(open, { ...closed, deformations: [{ ...bend,
      affected_helix_ids: ['unrelated'] }] })).toBe(true)
  })
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
