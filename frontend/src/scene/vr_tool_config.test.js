import { describe, expect, it } from 'vitest'

import {
  initialVRToolConfigState,
  normalizeVRToolConfig,
  reduceVRToolConfig,
  vrToolConfigMissing,
} from './vr_tool_config.js'

const target = {
  target_identity: 'nuc:s1:0:h1:3:FORWARD:0',
  target_kind: 'end',
  target_owner_tokens: ['end-token'],
}

describe('native VR tool configuration drafts', () => {
  it('keeps extrusion footprint unresolved instead of inferring geometry', () => {
    const draft = normalizeVRToolConfig({
      mode: 'extrude', ...target,
      length_bp: 42,
      direction_sign: 1,
      strand_filter: 'both',
      ligate_adjacent: true,
      footprint_state: 'unresolved',
    })
    expect(draft).not.toBeNull()
    expect(vrToolConfigMissing(draft)).toEqual(['footprint'])
  })

  it('requires two ordered deformation planes without inventing anchors', () => {
    const draft = normalizeVRToolConfig({
      mode: 'twist', ...target,
      plane_a_bp: null,
      plane_b_bp: null,
      amount_mode: 'total_degrees',
      amount: 90,
    })
    expect(vrToolConfigMissing(draft)).toEqual(['plane_a', 'plane_b'])
    expect(vrToolConfigMissing({ ...draft, plane_a_bp: 12, plane_b_bp: 12 }))
      .toEqual(['ordered_planes'])
    expect(vrToolConfigMissing({ ...draft, plane_a_bp: 12, plane_b_bp: 24 }))
      .toEqual([])
  })

  it('accepts desktop bend ranges and rejects non-finite or unbounded values', () => {
    const bend = {
      mode: 'bend', ...target,
      plane_a_bp: -4,
      plane_b_bp: 15,
      angle_deg: 360,
      direction_deg: 0,
    }
    expect(normalizeVRToolConfig(bend)).toEqual(bend)
    expect(normalizeVRToolConfig({ ...bend, angle_deg: NaN })).toBeNull()
    expect(normalizeVRToolConfig({ ...bend, direction_deg: 361 })).toBeNull()
    expect(normalizeVRToolConfig({ ...bend, plane_b_bp: 2 ** 31 })).toBeNull()
  })

  it('binds drafts to a complete canonical target snapshot', () => {
    const draft = {
      mode: 'extrude', ...target,
      length_bp: 1,
      direction_sign: -1,
      strand_filter: 'staples',
      ligate_adjacent: false,
      footprint_state: 'unresolved',
    }
    expect(normalizeVRToolConfig({ ...draft, target_owner_tokens: [] })).toBeNull()
    expect(normalizeVRToolConfig({
      ...draft,
      target_identity: null,
      target_kind: 'none',
      target_owner_tokens: [],
    })).not.toBeNull()
  })

  it('reduces only strictly increasing, valid draft sequences', () => {
    const draft = {
      mode: 'bend', ...target,
      plane_a_bp: null,
      plane_b_bp: null,
      angle_deg: 0,
      direction_deg: 0,
    }
    const accepted = reduceVRToolConfig(initialVRToolConfigState, {
      sequence: 4, draft,
    })
    expect(accepted.accepted).toBe(true)
    expect(accepted.reason).toBe('incomplete')
    expect(reduceVRToolConfig(accepted.state, { sequence: 4, draft }).state)
      .toBe(accepted.state)
    expect(reduceVRToolConfig(accepted.state, {
      sequence: 5, draft: { ...draft, angle_deg: Infinity },
    }).state).toBe(accepted.state)
    const cleared = reduceVRToolConfig(accepted.state, { sequence: 6, draft: null })
    expect(cleared).toEqual({
      state: { sequence: 6, draft: null }, accepted: true, reason: 'cleared',
    })
  })
})
