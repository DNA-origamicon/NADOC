import { describe, it, expect, vi } from 'vitest'
import { buildVRParameterizedToolPlan, evaluateVRToolPreflight } from './vr_tool_execution_plan.js'
const draft = {
  mode: 'extrude', target_kind: 'none', target_identity: null, target_owner_tokens: [],
  length_bp: 21, direction_sign: 1, strand_filter: 'both', ligate_adjacent: true,
  footprint_state: 'unresolved', extrude_from: 'XY',
  painted_footprint: { lattice_type: 'HONEYCOMB', cells: [[0,0],[0,1]] },
}
const design = { id: 'part', lattice_type: 'HONEYCOMB', helices: [], strands: [] }
const plan = (changes = {}, document = design) => buildVRParameterizedToolPlan(
  { ...draft, ...changes }, { design: document, revision: 4 })

describe('empty-part painted extrusion resolution', () => {
  it('pins the document revision, canonical plane, cells and signed length', () => {
    const result = plan({ direction_sign: -1, extrude_from: 'XZ' })
    expect(result.accepted).toBe(true)
    expect(result.plan.commit.arguments).toEqual({
      expected_design_id: 'part', expected_revision: 4, cells: [[0,0],[0,1]],
      length_bp: -21, plane: 'XZ', translation_nm: [0,0,0], rotation_xyzw: [0,0,0,1],
    })
    result.plan.commit.arguments.cells[0][0] = 10
    expect(result.plan.preflight.arguments.cells[0][0]).toBe(0)
    expect(draft.painted_footprint.cells[0][0]).toBe(0)
  })
  it.each(['helices','strands','protein_assets','nanoparticles','overhangs'])(
    'does not silently overlap existing %s', field => {
      expect(plan({}, { ...design, [field]: [{}] }).reason).toBe('source_frame_required')
    })
  it('rejects missing paint, wrong lattice, zero length and unsupported filtering', () => {
    expect(plan({ painted_footprint: { lattice_type: 'HONEYCOMB', cells: [] } }).reason).toBe('paint_cells_required')
    expect(plan({}, { ...design, lattice_type: 'SQUARE' }).reason).toBe('lattice_mismatch')
    expect(plan({ length_bp: 0 }).reason).toBe('length_required')
    expect(plan({ strand_filter: 'scaffold' }).reason).toBe('strand_filter_unsupported')
    expect(plan({ extrude_from: undefined }).reason).toBe('source_plane_required')
  })
  it('uses only the read-only backend validator and never calls commit', async () => {
    const api = { currentRevisionWatermark: () => 4,
      validateFrameExtrusion: vi.fn(async () => ({ status: 'ok' })), addFrameExtrusion: vi.fn() }
    const result = await evaluateVRToolPreflight(7, draft, { design, api })
    expect(result.feedback).toMatchObject({ status: 'ok', target_kind: 'none', tool_config_sequence: 7 })
    expect(api.validateFrameExtrusion).toHaveBeenCalledWith(result.plan.commit.arguments)
    expect(api.addFrameExtrusion).not.toHaveBeenCalled()
  })
})


describe('existing source plane resolution', () => {
  const existing = {
    ...design, helices: [{ id:'h', grid_pos:[3,3], lattice_frame_id:'frame' }],
    lattice_frames:[{ id:'frame', plane:'XY', placement_cluster_id:'placed' }],
    cluster_transforms:[{ id:'placed', translation:[12,4,8], rotation:[0,0.6,0,0.8] }],
  }
  it('pins the unique source frame without applying its rigid transform twice', () => {
    const result = plan({}, existing)
    expect(result.accepted).toBe(true)
    expect(result.plan.commit.arguments).toMatchObject({ source_frame_id:'frame',
      translation_nm:[0,0,0], rotation_xyzw:[0,0,0,1] })
    expect(result.plan.preflight.arguments).toEqual(result.plan.commit.arguments)
  })
  it('requires an unambiguous frame and rejects occupied cells and missing placement', () => {
    expect(plan({ extrude_from:'XZ' }, existing).reason).toBe('source_plane_mismatch')
    expect(plan({}, { ...existing, lattice_frames:[...existing.lattice_frames,
      { id:'other', plane:'XY', placement_cluster_id:'placed' }] }).reason).toBe('source_frame_ambiguous')
    expect(plan({ painted_footprint:{ lattice_type:'HONEYCOMB', cells:[[3,3]] } }, existing).reason).toBe('painted_cell_occupied')
    expect(plan({}, { ...existing, cluster_transforms:[] }).reason).toBe('source_placement_required')
  })
  it('selects by the explicit plane when other planes exist', () => {
    const result = plan({}, { ...existing, lattice_frames:[...existing.lattice_frames,
      { id:'other', plane:'YZ', placement_cluster_id:'placed' }] })
    expect(result.plan.commit.arguments.source_frame_id).toBe('frame')
  })
})

it('creates an independent freeform frame using canonical cells and a separate rigid pose', () => {
  const placement = { translation_nm:[12,-4,8],rotation_xyzw:[0,0.6,0,0.8] }
  expect(plan({freeform_placement:placement}).reason).toBe('initial_default_plane_required')
  const result = plan({freeform_placement:placement}, {...design,helices:[{id:'h'}]})
  expect(result.plan.commit.arguments).toMatchObject({...placement,plane:'XY',cells:[[0,0],[0,1]],expected_revision:4})
  expect(result.plan.commit.arguments).not.toHaveProperty('source_frame_id')
  result.plan.commit.arguments.translation_nm[0]=99
  expect(result.plan.preflight.arguments.translation_nm[0]).toBe(12)
  expect(placement.translation_nm[0]).toBe(12)
  expect(plan({freeform_placement:{...placement,rotation_xyzw:[0,0,0,0]}}).reason).toBe('invalid_draft')
})
