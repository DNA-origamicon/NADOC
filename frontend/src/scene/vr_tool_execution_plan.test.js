import { describe, expect, it } from 'vitest'

import {
  buildVRParameterizedToolPlan,
  resolveVRDeformationScope,
} from './vr_tool_execution_plan.js'

const endRef = { kind: 'end', key: 'h1:9:FORWARD' }
const geometry = [{
  helix_id: 'h1', bp_index: 9, direction: 'FORWARD', copy_k: 0,
  strand_id: 's1', domain_index: 0,
}]
const design = {
  cluster_transforms: [
    { id: 'whole', is_default: true, helix_ids: ['h1', 'h2'] },
    { id: 'local', helix_ids: ['h1'] },
  ],
}
const target = (selectedRef, overrides = {}) => ({
  identity: 'nuc:end', selectionKind: selectedRef.kind,
  ownerTokens: ['owner:end'], selectedRef, ...overrides,
})
const endDraft = overrides => ({
  mode: 'extrude', target_identity: 'nuc:end', target_kind: 'end',
  target_owner_tokens: ['owner:end'], length_bp: 7, direction_sign: 1,
  strand_filter: 'staples', ligate_adjacent: false,
  footprint_state: 'unresolved', ...overrides,
})
const endContext = overrides => ({
  kind: 'continuation_end', helixId: 'h1', continuationBp: 10,
  openSide: 1, plane: 'XY', offsetNm: 3.4, connections: [], deformed: false,
  footprint: {
    kind: 'single_end_cell', latticeType: 'HONEYCOMB', cells: [[2, 3]],
  },
  ...overrides,
})

describe('native VR parameterized tool execution plans', () => {
  it('maps an exact free End to the desktop continuation operation without executing it', () => {
    const result = buildVRParameterizedToolPlan(endDraft(), {
      toolTarget: target(endRef, { toolContext: endContext() }), design, geometry,
    })
    expect(result).toEqual({
      accepted: true,
      reason: 'ready_read_only',
      plan: {
        kind: 'extrude_continuation', targetIdentity: 'nuc:end',
        commit: {
          apiMethod: 'addBundleContinuation',
          arguments: {
            cells: [[2, 3]], lengthBp: 7, plane: 'XY', offsetNm: 3.4,
            strandFilter: 'staples', ligateAdjacent: false,
          },
        },
        lifecycle: {
          previewAuthority: 'native_read_only_geometry',
          preflight: 'desktop_continuation_validation_required',
          cancel: 'discard_descriptor', undo: 'desktop_feature_log',
        },
      },
    })
    expect(endContext().footprint.cells).toEqual([[2, 3]])
  })

  it('preserves face-relative direction and refuses occupied or deformed Ends', () => {
    const reversed = buildVRParameterizedToolPlan(endDraft({ direction_sign: -1 }), {
      toolTarget: target(endRef, { toolContext: endContext({ openSide: -1 }) }),
      design, geometry,
    })
    expect(reversed.plan.commit.arguments.lengthBp).toBe(7)
    expect(buildVRParameterizedToolPlan(endDraft(), {
      toolTarget: target(endRef, { toolContext: endContext({
        connections: [{ type: 'crossover', id: 'x1' }],
      }) }), design, geometry,
    }).reason).toBe('occupied_target')
    expect(buildVRParameterizedToolPlan(endDraft(), {
      toolTarget: target(endRef, { toolContext: endContext({ deformed: true }) }),
      design, geometry,
    }).reason).toBe('deformed_frame_required')
  })

  it('resolves End deformation to the most-specific containing Cluster', () => {
    expect(resolveVRDeformationScope(endRef, { design, geometry })).toEqual({
      resolved: true, reason: 'resolved', clusterIds: ['local'],
    })
    expect(resolveVRDeformationScope(endRef, {
      design: { cluster_transforms: [] }, geometry,
    })).toEqual({ resolved: true, reason: 'resolved', clusterIds: [] })
  })

  it('describes Twist preflight, transient preview cleanup, commit, and undo', () => {
    const draft = {
      mode: 'twist', target_identity: 'nuc:end', target_kind: 'end',
      target_owner_tokens: ['owner:end'], plane_a_bp: 5, plane_b_bp: 20,
      amount_mode: 'degrees_per_nm', amount: 1.5,
    }
    const result = buildVRParameterizedToolPlan(draft, {
      toolTarget: target(endRef), design, geometry,
    })
    expect(result.accepted).toBe(true)
    expect(result.plan.preflight).toEqual({
      apiMethod: 'validateDeformation',
      arguments: {
        type: 'twist', planeA: 5, planeB: 20,
        params: { degrees_per_nm: 1.5 }, helixIds: [], clusterIds: ['local'],
      },
    })
    expect(result.plan.preview.transient).toBe(true)
    expect(result.plan.preview.arguments).toEqual([
      'twist', 5, 20, { degrees_per_nm: 1.5 }, [], true, ['local'],
    ])
    expect(result.plan.commit.arguments).toEqual([
      'twist', 5, 20, { degrees_per_nm: 1.5 }, [], false, ['local'],
    ])
    expect(result.plan.commit.requiresPreviewDeleteFirst).toBe(true)
    expect(result.plan.lifecycle).toEqual({
      cancel: 'delete_transient_preview', undo: 'desktop_feature_log',
    })
  })

  it('fails closed on stale targets, invalid plane order, and unresolved scope', () => {
    const bend = {
      mode: 'bend', target_identity: 'nuc:end', target_kind: 'end',
      target_owner_tokens: ['owner:end'], plane_a_bp: 20, plane_b_bp: 5,
      angle_deg: 30, direction_deg: 45,
    }
    expect(buildVRParameterizedToolPlan(bend, {
      toolTarget: target(endRef), design, geometry,
    }).reason).toBe('ordered_planes_required')
    expect(buildVRParameterizedToolPlan({ ...bend, plane_a_bp: 5, plane_b_bp: 20 }, {
      toolTarget: target(endRef, { ownerTokens: ['changed'] }), design, geometry,
    }).reason).toBe('stale_target')
    expect(resolveVRDeformationScope(endRef, {
      design: { cluster_transforms: [{ id: 'other', helix_ids: ['h2'] }] },
      geometry,
    }).reason).toBe('target_scope_unresolved')
  })
})
