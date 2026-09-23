import { describe, it, expect } from 'vitest'
import { canonicalVREndSource } from './vr_continuation_source.js'

const helix = { id:'h', lattice_frame_id:'f', bp_start:-21, length_bp:42,
  axis_start:{ x:2,y:3,z:-7.014 }, axis_end:{ x:2,y:3,z:7.014 } }
const design = { lattice_frames:[{ id:'f', plane:'XY', placement_cluster_id:'c' }],
  cluster_transforms:[{ id:'c', helix_ids:['h'], translation:[50,-80,10], rotation:[0,0.6,0,0.8] }] }

describe('canonical VR end source', () => {
  it('uses local axial coordinates despite a rotated translated placement', () => {
    expect(canonicalVREndSource(helix,-21,design)).toEqual({ sourceFrameId:'f',plane:'XY',offsetNm:-7.014 })
    expect(canonicalVREndSource(helix,21,design)).toEqual({ sourceFrameId:'f',plane:'XY',offsetNm:7.014 })
    expect(canonicalVREndSource(helix,0,design).offsetNm).toBeCloseTo(0)
  })
  it('rejects missing/ambiguous placement, noncanonical axes and out-of-range ends', () => {
    expect(canonicalVREndSource(helix,22,design)).toBeNull()
    expect(canonicalVREndSource(helix,0,{ ...design,cluster_transforms:[] })).toBeNull()
    expect(canonicalVREndSource(helix,0,{ ...design,cluster_transforms:[...design.cluster_transforms,...design.cluster_transforms] })).toBeNull()
    expect(canonicalVREndSource({ ...helix,axis_end:{ x:3,y:3,z:7.014 } },0,design)).toBeNull()
  })
})


it('rejects a domain-specific placement layered over the source frame', () => {
  const layered = { ...design, strands:[{ id:'s',domains:[{ helix_id:'h' }] }],
    cluster_transforms:[...design.cluster_transforms,{ id:'domain',
      domain_ids:[{ strand_id:'s',domain_index:0 }],translation:[2,0,0] }] }
  expect(canonicalVREndSource(helix,0,layered)).toBeNull()
})
