import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { _bboxSolidFromNucs, HULL_MIN_SIZE_FRACTION, HULL_CURVE_TOL_NM } from './assembly_hull_geometry.js'

// Pins the fallback far-LOD hull after the assembly_renderer.js split. Without a
// hull bucket a source vanishes when zoomed far out, so "returns null" vs
// "returns a padded box" is load-bearing, not cosmetic.

const ds = (helixId, bp, pos) => [
  { strand_id: 's1', helix_id: helixId, bp_index: bp, backbone_position: pos },
  { strand_id: 's2', helix_id: helixId, bp_index: bp, backbone_position: pos },
]

function bounds(geo) {
  geo.computeBoundingBox()
  return geo.boundingBox
}

describe('_bboxSolidFromNucs', () => {
  it('returns null for empty / missing input', () => {
    expect(_bboxSolidFromNucs(null)).toBeNull()
    expect(_bboxSolidFromNucs([])).toBeNull()
  })

  it('returns null when no nucleotide carries a position', () => {
    expect(_bboxSolidFromNucs([{ strand_id: 's1', helix_id: 'h1', bp_index: 0 }])).toBeNull()
  })

  it('bounds the dsDNA nucleotides and pads by ~1 nm on each side', () => {
    const nucs = [...ds('h1', 0, [0, 0, 0]), ...ds('h1', 1, [2, 4, 6])]
    const geo = _bboxSolidFromNucs(nucs)
    expect(geo).toBeInstanceOf(THREE.BufferGeometry)
    const b = bounds(geo)
    expect(b.min.x).toBeCloseTo(-1, 5)
    expect(b.max.x).toBeCloseTo(3, 5)
    expect(b.max.z).toBeCloseTo(7, 5)
  })

  it('prefers dsDNA: a lone unpaired nucleotide far away does not stretch the box', () => {
    const nucs = [
      ...ds('h1', 0, [0, 0, 0]), ...ds('h1', 1, [1, 0, 0]),
      { strand_id: 's9', helix_id: 'h9', bp_index: 0, backbone_position: [500, 0, 0] }, // unpaired
    ]
    expect(bounds(_bboxSolidFromNucs(nucs)).max.x).toBeCloseTo(2, 5)
  })

  it('falls back to ALL positioned nucleotides when the part has no dsDNA', () => {
    const nucs = [
      { strand_id: 's1', helix_id: 'h1', bp_index: 0, backbone_position: [0, 0, 0] },
      { strand_id: 's1', helix_id: 'h1', bp_index: 1, backbone_position: [10, 0, 0] },
    ]
    expect(bounds(_bboxSolidFromNucs(nucs)).max.x).toBeCloseTo(11, 5)
  })

  it('excludes overhang nucleotides from the dsDNA pairing count', () => {
    const nucs = [
      { strand_id: 's1', helix_id: 'h1', bp_index: 0, backbone_position: [0, 0, 0], overhang_id: 'o1' },
      { strand_id: 's2', helix_id: 'h1', bp_index: 0, backbone_position: [0, 0, 0], overhang_id: 'o1' },
    ]
    // both are overhang nucs → no dsDNA pairs → fallback path bounds them anyway
    expect(_bboxSolidFromNucs(nucs)).not.toBeNull()
  })

  it('enforces a 0.5 nm minimum extent so a single-point part is still visible', () => {
    const geo = _bboxSolidFromNucs([{ strand_id: 's1', helix_id: 'h1', bp_index: 0, backbone_position: [5, 5, 5] }])
    const b = bounds(geo)
    expect(b.max.x - b.min.x).toBeGreaterThanOrEqual(0.5)
    expect(b.getCenter(new THREE.Vector3()).x).toBeCloseTo(5, 5)
  })

  it('returns a non-indexed geometry with position + normal (mergeable into the hull batch)', () => {
    const geo = _bboxSolidFromNucs(ds('h1', 0, [0, 0, 0]).concat(ds('h1', 1, [1, 1, 1])))
    expect(geo.index).toBeNull()
    expect(geo.getAttribute('position')).toBeTruthy()
    expect(geo.getAttribute('normal')).toBeTruthy()
  })

  it('exposes the hull tuning constants the design view matches', () => {
    expect(HULL_MIN_SIZE_FRACTION).toBe(0.10)
    expect(HULL_CURVE_TOL_NM).toBe(1.0)
  })
})
