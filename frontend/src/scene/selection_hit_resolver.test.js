import { describe, expect, it } from 'vitest'
import {
  bondRefForCone, coneForBondRef, crossoverRefForArc, endRefForEntry, vrPrimitiveOwner,
  vrOwnerTokens,
} from './selection_hit_resolver.js'

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

  it('resolves native nucleotide identities by live candidate, including colon IDs', () => {
    const nucleotide = {
      strand_id: 'strand:a', domain_index: 2, helix_id: 'helix:b', bp_index: 7,
      direction: 'REVERSE', copy_k: 1,
    }
    const owner = vrPrimitiveOwner(
      'nuc:strand:a:2:helix:b:7:REVERSE:1:slab',
      { geometry: [nucleotide] },
    )
    expect(owner).toEqual({
      kind: 'nucleotide', nucleotide,
      ref: { kind: 'base', key: 'helix:b:7:REVERSE:1' },
    })
    expect(vrPrimitiveOwner(
      'atom:12:base:helix:b:7:REVERSE:1:C', { geometry: [nucleotide] },
    )).toEqual({
      kind: 'atom', nucleotide,
      ref: { kind: 'base', key: 'helix:b:7:REVERSE:1' },
    })
  })

  it('resolves coarse and atomistic backbone bonds without index ownership', () => {
    const first = {
      strand_id: 'strand:a', domain_index: 0, helix_id: 'helix:b', bp_index: 3,
      direction: 'FORWARD',
    }
    const second = { ...first, bp_index: 4 }
    expect(vrPrimitiveOwner(
      'backbone:nuc:strand:a:0:helix:b:3:FORWARD:0~nuc:strand:a:0:helix:b:4:FORWARD:0',
      { geometry: [first, second] },
    )).toEqual({
      kind: 'backbone_bond', fromNucleotide: first, toNucleotide: second,
      ref: {
        kind: 'bond', fromKey: 'helix:b:3:FORWARD', toKey: 'helix:b:4:FORWARD',
        strandId: 'strand:a',
      },
    })
    expect(vrPrimitiveOwner(
      'atom-bond:bases:helix:b:3:FORWARD~helix:b:4:FORWARD:atoms:10-20',
      { geometry: [first, second] },
    )?.kind).toBe('atom_bond')
    expect(vrPrimitiveOwner(
      'atom-bond:bases:helix:b:3:FORWARD~helix:b:3:FORWARD:atoms:10-11',
      { geometry: [first, second] },
    )).toEqual({
      kind: 'atom_bond_base', nucleotide: first,
      ref: { kind: 'base', key: 'helix:b:3:FORWARD' },
    })
  })

  it('resolves crossover, forced-ligation, warning, and domain primitives', () => {
    const design = {
      crossovers: [{ id: 'xo:a' }],
      forced_ligations: [{ id: 'fl:b' }],
      strands: [{ id: 'strand:c', domains: [{ helix_id: 'helix:d' }] }],
    }
    expect(vrPrimitiveOwner('crossover:xo:a:direct', { design })?.ref).toEqual(
      { kind: 'crossover', id: 'xo:a', subtype: 'crossover' },
    )
    expect(vrPrimitiveOwner('warning:xo:a:outline:0', { design })?.ref).toEqual(
      { kind: 'crossover', id: 'xo:a', subtype: 'crossover' },
    )
    expect(vrPrimitiveOwner('ligation:fl:b:direct', { design })?.ref).toEqual(
      { kind: 'crossover', id: 'fl:b', subtype: 'forced_ligation' },
    )
    expect(vrPrimitiveOwner(
      'segment:helix:d:strand:c:0:3:9:axis', { design },
    )?.ref).toEqual({ kind: 'domain', strandId: 'strand:c', domainIndex: 0 })
  })

  it('resolves flexible and ss-linker base owners without parsing connection IDs', () => {
    const design = {
      strands: [{ id: 'strand:a', domains: [{ helix_id: 'helix:b' }] }],
      flexible_connections: [{
        id: 'flex:c',
        segment_bead_keys: [{
          strand_id: 'strand:a', domain_index: 0, bp_index: 8, direction: 'REVERSE',
        }],
      }],
      overhang_connections: [{ id: 'link:d' }],
    }
    expect(vrPrimitiveOwner('flex:flex:c:slab:0', { design })).toEqual({
      kind: 'flexible_base', connectionId: 'flex:c',
      ref: { kind: 'base', key: 'helix:b:8:REVERSE' },
    })
    expect(vrPrimitiveOwner('linker:link:d:ss:bead:3', { design })).toEqual({
      kind: 'linker_base', connectionId: 'link:d',
      ref: { kind: 'base', key: '__lnk__link:d:3:FORWARD' },
    })
    expect(vrPrimitiveOwner('flex:flex:c:backbone:12:near:0', { design })).toEqual({
      kind: 'flexible_base', connectionId: 'flex:c',
      ref: { kind: 'base', key: 'helix:b:8:REVERSE' },
    })
    expect(vrPrimitiveOwner('linker:link:d:ss:backbone:9:near:3', { design })).toEqual({
      kind: 'linker_base', connectionId: 'link:d',
      ref: { kind: 'base', key: '__lnk__link:d:3:FORWARD' },
    })
    expect(vrPrimitiveOwner('linker:link:d:ds:a:connector:2', { design })).toEqual({
      kind: 'linker_connection', connectionId: 'link:d', ref: null,
    })
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

  it('orders exact and coarse owner aliases without delimiter ambiguity', () => {
    const nucleotide = {
      strand_id: 'strand:a b', domain_index: 2, helix_id: 'h:1', bp_index: 7,
      direction: 'FORWARD',
    }
    const tokens = vrOwnerTokens({
      selected: true,
      selectedRef: { kind: 'base', key: 'h:1:7:FORWARD' },
      owner: { ref: { kind: 'base', key: 'h:1:7:FORWARD' } },
      nucleotide,
      key: 'h:1:7:FORWARD',
    })
    expect(tokens.map(decodeURIComponent)).toEqual([
      '["base","h:1:7:FORWARD"]',
      '["domain","strand:a b",2]',
      '["strand","strand:a b"]',
    ])
    expect(tokens.every(token => !/\s/.test(token))).toBe(true)
    expect(vrOwnerTokens({ selected: false, selectedRef: { kind: 'strand', id: 's' } }))
      .toEqual([])
  })
})
