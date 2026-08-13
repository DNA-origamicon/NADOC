import { describe, expect, it } from 'vitest'
import { bondRefForCone, coneForBondRef, crossoverRefForArc, endRefForEntry } from './selection_hit_resolver.js'

const nuc = (bp, extra = {}) => ({ helix_id: 'h1', bp_index: bp, direction: 'FORWARD', ...extra })

describe('pure selection hit resolution', () => {
  it('resolves regular and forced-ligation arc IDs by live design ownership', () => {
    const design = { crossovers: [{ id: 'x1' }], forced_ligations: [{ id: 'f1' }] }
    expect(crossoverRefForArc({ crossover_id: 'x1' }, design))
      .toEqual({ kind: 'crossover', id: 'x1', subtype: 'crossover' })
    expect(crossoverRefForArc({ crossover_id: 'f1' }, design))
      .toEqual({ kind: 'crossover', id: 'f1', subtype: 'forced_ligation' })
    expect(crossoverRefForArc({ crossover_id: 'gone' }, design)).toBeNull()
  })

  it('resolves only terminal beads as End refs', () => {
    expect(endRefForEntry({ nuc: nuc(3, { is_five_prime: true }) }))
      .toEqual({ kind: 'end', key: 'h1:3:FORWARD' })
    expect(endRefForEntry({ nuc: nuc(3) })).toBeNull()
  })

  it('resolves a visual cone to stable ordered backbone-bond identity', () => {
    expect(bondRefForCone({ fromNuc: nuc(3), toNuc: nuc(4) }, 's1')).toEqual({
      kind: 'bond', fromKey: 'h1:3:FORWARD', toKey: 'h1:4:FORWARD', strandId: 's1',
    })
  })

  it('projects a canonical bond back to matching live geometry after rebuild', () => {
    const other = { strandId: 's2', fromNuc: nuc(3), toNuc: nuc(4) }
    const match = { strandId: 's1', fromNuc: nuc(3), toNuc: nuc(4) }
    const reversed = { strandId: 's1', fromNuc: nuc(4), toNuc: nuc(3) }
    const ref = { kind: 'bond', fromKey: 'h1:3:FORWARD', toKey: 'h1:4:FORWARD', strandId: 's1' }

    expect(coneForBondRef([other, reversed, match], ref)).toBe(match)
    expect(coneForBondRef([match], { ...ref, strandId: undefined })).toBe(match)
    expect(coneForBondRef([reversed], ref)).toBeNull()
  })
})
