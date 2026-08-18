import { describe, expect, it } from 'vitest'

import { resolveVREndToolContext, vrToolFeedbackPayload } from './vr_tool_context.js'

const design = ({ transformed = false, deformed = false, gridPos = [2, 3] } = {}) => ({
  lattice_type: 'HONEYCOMB',
  helices: [
    {
      id: 'h1', bp_start: 0, length_bp: 20, grid_pos: gridPos,
      axis_start: { x: -1, y: 0, z: 0 }, axis_end: { x: -1, y: 0, z: 10 },
    },
    {
      id: 'h2', bp_start: 0, length_bp: 20, grid_pos: [3, 3],
      axis_start: { x: 1, y: 0, z: 0 }, axis_end: { x: 1, y: 0, z: 10 },
    },
  ],
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
  ringPos3d: [1, 2, 3], faceNormal3d: [0, 0, 1],
  endPos3d: [1, 2, 2.666],
  owners: [{
    strandId: 's1', domainIndex: 0, direction: 'FORWARD',
    strandType: 'scaffold', overhangId: null,
  }],
  ...overrides,
})

describe('VR End tool context', () => {
  it('resolves the exact desktop continuation face and canonical source bp', () => {
    const result = resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' },
      { geometry: [nucleotide()], design: design(), domainEnds: [face()] },
    )
    const delta = 5 / 2.25 - 1
    expect(result).toEqual({
      accepted: true,
      reason: 'resolved',
      context: {
        kind: 'continuation_end', helixId: 'h1', bp: 9, diskBp: 10,
        continuationBp: 10, openSide: 1, plane: 'XY', offsetNm: 3.34,
        facePosition: [1, 2, 3], faceNormal: [0, 0, 1],
        continuationPosition: [1, 2, 3],
        expandedFacePosition: [1 - delta, 2, 3],
        expandedFaceNormal: [0, 0, 1],
        expandedContinuationPosition: [1 - delta, 2, 3],
        strandId: 's1', domainIndex: 0, direction: 'FORWARD',
        endRole: 'three_prime', overhangId: null, connections: [], deformed: false,
        footprint: {
          kind: 'single_end_cell', latticeType: 'HONEYCOMB', cells: [[2, 3]],
        },
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
      continuationPosition: [1, 2, 2.666],
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

  it('uses the canonical lattice cell and refuses to invent one', () => {
    const resolved = resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' },
      { geometry: [nucleotide()], design: design({ gridPos: [-2, 7] }), domainEnds: [face()] },
    )
    expect(resolved.context.footprint.cells).toEqual([[-2, 7]])

    const legacy = design({ gridPos: null })
    legacy.helices[0].id = 'h_XY_-4_6_2'
    const legacyFace = face({ helixId: legacy.helices[0].id })
    const legacyNucleotide = nucleotide({ helix_id: legacy.helices[0].id })
    expect(resolveVREndToolContext(
      { kind: 'end', key: `${legacy.helices[0].id}:9:FORWARD` },
      { geometry: [legacyNucleotide], design: legacy, domainEnds: [legacyFace] },
    ).context.footprint.cells).toEqual([[-4, 6]])

    const ungridded = design({ gridPos: null })
    expect(resolveVREndToolContext(
      { kind: 'end', key: 'h1:9:FORWARD' },
      { geometry: [nucleotide()], design: ungridded, domainEnds: [face()] },
    ).context.footprint).toBeNull()
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

  it('publishes a bounded exact locator without widening unresolved targets', () => {
    const draft = { target_kind: 'end', target_identity: 'nuc:end' }
    expect(vrToolFeedbackPayload(7, draft, {
      toolContext: {
        facePosition: [1, 2, 3], faceNormal: [0, 0, 2],
        continuationPosition: [1, 2, 2.666],
        expandedFacePosition: [4, 5, 6], expandedFaceNormal: [0, 2, 0],
        expandedContinuationPosition: [4, 5, 5.666],
        connections: [{ type: 'crossover', id: 'xo1' }], deformed: true,
        footprint: { kind: 'single_end_cell', latticeType: 'HONEYCOMB', cells: [[2, 3]] },
      },
      toolContextReason: 'resolved',
    })).toEqual({
      tool_config_sequence: 7,
      target_identity: 'nuc:end',
      target_kind: 'end',
      resolved: true,
      reason: 'resolved',
      face_position: [1, 2, 3],
      face_normal: [0, 0, 2],
      preview_origin: [1, 2, 2.666],
      expanded_face_position: [4, 5, 6],
      expanded_face_normal: [0, 2, 0],
      expanded_preview_origin: [4, 5, 5.666],
      occupied: true,
      deformed: true,
      footprint_resolved: true,
    })
    expect(vrToolFeedbackPayload(8, draft, {
      toolContext: null, toolContextReason: 'no_continuation_face',
    })).toMatchObject({
      tool_config_sequence: 8, resolved: false,
      reason: 'no_continuation_face', face_position: null, face_normal: null,
      preview_origin: null, occupied: false, deformed: false,
      expanded_face_position: null, expanded_face_normal: null,
      expanded_preview_origin: null,
      footprint_resolved: false,
    })
    expect(vrToolFeedbackPayload(9, draft, {
      toolContext: null, toolContextReason: 'geometry_context_required',
    })).toBeNull()
    expect(vrToolFeedbackPayload(10, draft, {
      toolContext: { facePosition: [1, 2, 3], faceNormal: [0, 0, 0] },
    })).toBeNull()
    expect(vrToolFeedbackPayload(11, draft, {
      toolContext: {
        facePosition: [1, 2, 3], faceNormal: [0, 0, 1], connections: [],
        expandedFacePosition: [4, 5, 6], expandedFaceNormal: [0, 0, 1],
        expandedContinuationPosition: [4, 5, 5.666],
        footprint: { kind: 'single_end_cell', latticeType: 'HONEYCOMB', cells: [[]] },
      },
    }).footprint_resolved).toBe(false)
  })
})
