import { describe, it, expect } from 'vitest'
import { assemblyConnectorArcEndpoints } from './assembly_connector_arcs.js'

// nuc bead helper: a world-space linker nucleotide as returned by
// GET /assembly/linker-geometry.
const nuc = (strand_id, helix_id, bp_index, pos) => ({
  strand_id, helix_id, bp_index, backbone_position: pos,
})

const HA = 'iA::hA'   // namespaced complement helix, side A
const HB = 'iB::hB'   // namespaced complement helix, side B

describe('assemblyConnectorArcEndpoints', () => {
  it('ds linker: one arc per side strand at its complement↔bridge junction', () => {
    const br = '__lnk__c'
    const strands = [
      // side A, comp-first: [comp_a, bridge]
      { id: '__lnk__c__a', color: '#abc',
        domains: [{ helix_id: HA, start_bp: 5, end_bp: 2 }, { helix_id: br, start_bp: 0, end_bp: 3 }] },
      // side B, bridge-first: [bridge, comp_b]
      { id: '__lnk__c__b', color: '#abc',
        domains: [{ helix_id: br, start_bp: 3, end_bp: 0 }, { helix_id: HB, start_bp: 2, end_bp: 5 }] },
    ]
    const nucs = [
      nuc('__lnk__c__a', HA, 2, [0, 0, 0]), nuc('__lnk__c__a', br, 0, [1, 0, 0]),
      nuc('__lnk__c__b', br, 0, [1, 0, 0]), nuc('__lnk__c__b', HB, 2, [2, 0, 0]),
    ]
    const arcs = assemblyConnectorArcEndpoints(strands, nucs)
    expect(arcs).toHaveLength(2)
    expect(arcs.every(a => a.connId === 'c')).toBe(true)
    expect(arcs[0]).toMatchObject({ a: [0, 0, 0], b: [1, 0, 0], colorCss: '#abc' })
  })

  it('length>0 ss linker: two arcs (comp_a↔bridge and bridge↔comp_b)', () => {
    const br = '__lnk__c2'
    const strands = [{ id: '__lnk__c2__s', color: '#fff',
      domains: [
        { helix_id: HA, start_bp: 5, end_bp: 2 },
        { helix_id: br, start_bp: 0, end_bp: 3 },
        { helix_id: HB, start_bp: 2, end_bp: 5 },
      ] }]
    const nucs = [
      nuc('__lnk__c2__s', HA, 2, [0, 0, 0]),
      nuc('__lnk__c2__s', br, 0, [1, 0, 0]),
      nuc('__lnk__c2__s', br, 3, [2, 0, 0]),
      nuc('__lnk__c2__s', HB, 2, [3, 0, 0]),
    ]
    const arcs = assemblyConnectorArcEndpoints(strands, nucs)
    expect(arcs).toHaveLength(2)
    expect(arcs.map(a => a.connId)).toEqual(['c2', 'c2'])
    expect(arcs[0]).toMatchObject({ a: [0, 0, 0], b: [1, 0, 0] })
    expect(arcs[1]).toMatchObject({ a: [2, 0, 0], b: [3, 0, 0] })
  })

  it('length-0 indirect ss linker: one direct complement↔complement arc', () => {
    // domains [comp_a, comp_b] with NO bridge.
    const strands = [{ id: '__lnk__c3__s', color: '#0f0',
      domains: [
        { helix_id: HA, start_bp: 5, end_bp: 2 },
        { helix_id: HB, start_bp: 2, end_bp: 5 },
      ] }]
    const nucs = [
      nuc('__lnk__c3__s', HA, 2, [0, 0, 0]),
      nuc('__lnk__c3__s', HB, 2, [5, 0, 0]),
    ]
    const arcs = assemblyConnectorArcEndpoints(strands, nucs)
    expect(arcs).toHaveLength(1)
    expect(arcs[0]).toMatchObject({ connId: 'c3', a: [0, 0, 0], b: [5, 0, 0], colorCss: '#0f0' })
  })

  it('ignores non-linker strands', () => {
    const strands = [{ id: 'scaffold-1', domains: [{ helix_id: HA, start_bp: 0, end_bp: 3 }, { helix_id: HB, start_bp: 0, end_bp: 3 }] }]
    const nucs = [nuc('scaffold-1', HA, 3, [0, 0, 0]), nuc('scaffold-1', HB, 0, [1, 0, 0])]
    expect(assemblyConnectorArcEndpoints(strands, nucs)).toHaveLength(0)
  })

  it('skips same-helix continuations (no backbone jump)', () => {
    const strands = [{ id: '__lnk__c4__s',
      domains: [{ helix_id: HA, start_bp: 0, end_bp: 3 }, { helix_id: HA, start_bp: 4, end_bp: 7 }] }]
    const nucs = [nuc('__lnk__c4__s', HA, 3, [0, 0, 0]), nuc('__lnk__c4__s', HA, 4, [1, 0, 0])]
    expect(assemblyConnectorArcEndpoints(strands, nucs)).toHaveLength(0)
  })

  it('skips a jump whose endpoint beads are missing from the geometry', () => {
    const strands = [{ id: '__lnk__c5__s',
      domains: [{ helix_id: HA, start_bp: 5, end_bp: 2 }, { helix_id: HB, start_bp: 2, end_bp: 5 }] }]
    expect(assemblyConnectorArcEndpoints(strands, [])).toHaveLength(0)
  })

  it('drops a degenerate (coincident) jump', () => {
    const strands = [{ id: '__lnk__c6__s',
      domains: [{ helix_id: HA, start_bp: 5, end_bp: 2 }, { helix_id: HB, start_bp: 2, end_bp: 5 }] }]
    const nucs = [nuc('__lnk__c6__s', HA, 2, [1, 1, 1]), nuc('__lnk__c6__s', HB, 2, [1, 1, 1])]
    expect(assemblyConnectorArcEndpoints(strands, nucs)).toHaveLength(0)
  })
})
