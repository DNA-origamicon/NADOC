import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { ordinaryBackboneContinuations } from './backbone_continuations.js'
import { buildHelixObjects, CONE_RADIUS } from './helix_renderer.js'

function continuation(sweepDirection = 1) {
  const atStart = sweepDirection === -1
  const sourceBp = atStart ? 0 : 62, sweptBp = sourceBp + sweepDirection
  const helices = [
    { id: 'source', grid_pos: [1, 1], direction: 'FORWARD', lattice_frame_id: null,
      bp_start: 0, length_bp: 63, axis_start: [0, 0, 0], axis_end: [0, 0, 62 * .334] },
    { id: 'swept', grid_pos: [1, 1], direction: 'FORWARD', lattice_frame_id: 'sweep-frame',
      bp_start: atStart ? -10 : 63, length_bp: 10,
      axis_start: [0, 0, (atStart ? -10 : 63) * .334], axis_end: [0, 0, (atStart ? -1 : 72) * .334] },
  ]
  const strands = ['FORWARD', 'REVERSE'].map(direction => {
    const domains = [
      { id: `source-${direction}`, helix_id: 'source', direction, start_bp: sourceBp, end_bp: sourceBp },
      { id: `swept-${direction}`, helix_id: 'swept', direction, start_bp: sweptBp, end_bp: sweptBp },
    ]
    if ((direction === 'REVERSE') !== atStart) domains.reverse()
    return { id: direction, strand_type: direction === 'FORWARD' ? 'scaffold' : 'staple', domains }
  })
  return { helices, strands, crossovers: [], forced_ligations: [],
    deformations: [{ type: 'sweep', affected_helix_ids: ['swept'],
      plane_a_bp: atStart ? -10 : 63, plane_b_bp: atStart ? -1 : 72,
      params: { start_step: 1, direction: sweepDirection } }] }
}

function geometry(design) {
  return design.strands.flatMap(strand => strand.domains.map((d, i) => ({
    helix_id: d.helix_id, bp_index: d.start_bp, direction: d.direction,
    strand_id: strand.id, strand_type: strand.strand_type, domain_index: i,
    backbone_position: [1, 0, d.start_bp * .334], base_position: [.5, 0, d.start_bp * .334],
    placement_source: 'native-full-o5-v1', slab_position: [.67, 0, d.start_bp * .334],
    slab_quaternion: [0, Math.SQRT1_2, Math.SQRT1_2, 0],
    base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1],
  })))
}

function coneRadius(cone) {
  const m = new THREE.Matrix4()
  cone.instMesh.getMatrixAt(cone.id, m)
  return new THREE.Vector3().setFromMatrixScale(m).x
}

describe('ordinary sweep backbone continuation rendering', () => {
  it.each([1, -1])('draws both duplex bonds as cones when sweeping direction %i', direction => {
    const design = continuation(direction)
    const ctrl = buildHelixObjects(geometry(design), design, new THREE.Scene())
    expect(ctrl.coneEntries).toHaveLength(2)
    expect(ctrl.getCrossHelixConnections()).toEqual([])
    for (const cone of ctrl.coneEntries) {
      expect(cone.isCrossHelix).toBe(false)
      expect(coneRadius(cone)).toBeCloseTo(CONE_RADIUS)
    }
    // Presentation transitions must retain the classified bond type instead
    // of reclassifying all distinct helix IDs as crossovers.
    ctrl.applyUnfoldOffsets(new Map(), 0)
    for (const cone of ctrl.coneEntries) expect(coneRadius(cone)).toBeCloseTo(CONE_RADIUS)
  })

  it('keeps an explicitly forced ligation selectable as an arc', () => {
    const design = continuation()
    design.forced_ligations.push({ id: 'forced',
      three_prime_helix_id: 'source', three_prime_bp: 62, three_prime_direction: 'FORWARD',
      five_prime_helix_id: 'swept', five_prime_bp: 63, five_prime_direction: 'FORWARD',
    })
    const ctrl = buildHelixObjects(geometry(design), design, new THREE.Scene())
    expect(ctrl.getCrossHelixConnections()).toHaveLength(1)
    const forced = ctrl.coneEntries.find(c => c.strandId === 'FORWARD')
    expect(forced.isCrossHelix).toBe(true)
    expect(coneRadius(forced)).toBe(0)
  })

  it.each([
    ['unrelated frames sharing a grid cell', d => { d.deformations = [] }],
    ['a new, unattached sweep', d => { d.deformations[0].params.start_step = 0 }],
    ['an ordinary lateral crossover', d => { d.helices[1].grid_pos = [1, 2] }],
    ['opposite helix polarity', d => { d.helices[1].direction = 'REVERSE' }],
    ['a same-frame junction', d => { d.helices[1].lattice_frame_id = null }],
    ['a gap in the backbone', d => { d.strands[0].domains[1].start_bp = 64; d.strands.splice(1) }],
    ['separate nicked strands', d => { d.strands = d.strands.flatMap(s => s.domains.map(dom => ({ domains: [dom] }))) }],
  ])('does not promote %s into ordinary backbone continuity', (_name, mutate) => {
    const design = continuation()
    mutate(design)
    expect(ordinaryBackboneContinuations(design).size).toBe(0)
  })
})
