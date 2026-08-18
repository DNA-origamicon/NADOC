import { describe, expect, it } from 'vitest'

import { resolveVREndToolContext } from './vr_tool_context.js'

const design = ({ transformed = false, deformed = false } = {}) => ({
  helices: [{ id: 'h1', bp_start: 0, length_bp: 20 }],
  deformations: deformed ? [{ id: 'bend-1' }] : [],
  cluster_transforms: transformed ? [{
    helix_ids: ['h1'], rotation: [0, 0, 0, 1], translation: [1, 0, 0],
  }] : [],
})
const nucleotide = (overrides = {}) => ({
  helix_id: 'h1', bp_index: 9, direction: 'FORWARD', copy_k: 0,
  strand_id: 's1', domain_index: 0,
  is_five_prime: false, is_three_prime: true,
  ...overrides,
})
const face = (overrides = {}) => ({
  helixId: 'h1', bp: 9, diskBp: 10, openSide: 1,
  plane: 'XY', offsetNm: 3.34, overhangId: null,
  owners: [{
    strandId: 's1', domainIndex: 0, direction: 'FORWARD',
    strandType: 'scaffold', overhangId: null,
  }],
  ...overrides,
})

describe('VR End tool context', () => {
  it('resolves the exact desktop continuation face and canonical source bp', () => {
    expect(resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' },
      { geometry: [nucleotide()], design: design(), domainEnds: [face()] },
    )).toEqual({
      accepted: true,
      reason: 'resolved',
      context: {
        kind: 'continuation_end', helixId: 'h1', bp: 9, diskBp: 10,
        continuationBp: 10, openSide: 1, plane: 'XY', offsetNm: 3.34,
        strandId: 's1', domainIndex: 0, direction: 'FORWARD',
        endRole: 'three_prime', overhangId: null, connections: [], deformed: false,
      },
    })
  })

  it('uses bp itself for the near face and preserves overhang/deformation context', () => {
    const result = resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' },
      {
        geometry: [nucleotide({ is_five_prime: true, is_three_prime: false })],
        design: design({ transformed: true }),
        domainEnds: [face({
          diskBp: 8, openSide: -1, overhangId: 'oh1',
          owners: [{
            strandId: 's1', domainIndex: 0, direction: 'FORWARD',
            strandType: 'staple', overhangId: 'oh1',
          }],
        })],
      },
    )
    expect(result.context).toMatchObject({
      continuationBp: 9, openSide: -1, overhangId: 'oh1',
      endRole: 'five_prime', deformed: true,
    })
  })

  it.each([
    ['extension tip', { kind: 'end', key: '__ext_mod:2:FORWARD' },
      [nucleotide({ helix_id: '__ext_mod', bp_index: 2 })], [face()],
      'synthetic_end_not_supported'],
    ['loop copy', { kind: 'end', key: 'h1:9:FORWARD:2' },
      [nucleotide({ copy_k: 2 })], [face()], 'loop_copy_not_supported'],
    ['stale end', { kind: 'end', key: 'h1:9:FORWARD' },
      [], [face()], 'stale_live_end'],
    ['nonterminal base', { kind: 'end', key: 'h1:9:FORWARD' },
      [nucleotide({ is_three_prime: false })], [face()], 'not_terminal'],
    ['owner mismatch', { kind: 'end', key: 'h1:9:FORWARD' },
      [nucleotide()], [face({ owners: [{
        strandId: 'other', domainIndex: 0, direction: 'FORWARD',
      }] })], 'no_continuation_face'],
  ])('refuses %s without widening to a nearby face', (
    _label, ref, geometry, domainEnds, reason,
  ) => {
    expect(resolveVREndToolContext(ref, {
      geometry, design: design(), domainEnds,
    })).toEqual({ accepted: false, reason, context: null })
  })

  it('fails closed on duplicate or malformed physical faces', () => {
    const inputs = {
      geometry: [nucleotide()], design: design(), domainEnds: [face(), face()],
    }
    expect(resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' }, inputs,
    ).reason).toBe('ambiguous_continuation_face')
    expect(resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' },
      { ...inputs, domainEnds: [face({ offsetNm: NaN })] },
    ).reason).toBe('invalid_continuation_face')
  })

  it('reports forced ligations and crossovers without deciding tool policy', () => {
    const connectedDesign = {
      ...design(),
      crossovers: [{
        id: 'xo1',
        half_a: { helix_id: 'h1', index: 9, strand: 'FORWARD' },
        half_b: { helix_id: 'h2', index: 9, strand: 'REVERSE' },
      }],
      forced_ligations: [{
        id: 'fl1',
        three_prime_helix_id: 'h1', three_prime_bp: 9,
        three_prime_direction: 'FORWARD',
        five_prime_helix_id: 'h3', five_prime_bp: 2,
        five_prime_direction: 'REVERSE',
      }],
    }
    const result = resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' },
      { geometry: [nucleotide()], design: connectedDesign, domainEnds: [face()] },
    )
    expect(result.context.connections).toEqual([
      { type: 'crossover', id: 'xo1' },
      { type: 'forced_ligation', id: 'fl1' },
    ])
  })
})
