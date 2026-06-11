import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { selectionBBox, instanceUnionBox, nucleotideLocalBox, nucleotideBoxOverflow } from './selection_bbox.js'

const nuc = (strand_id, pos, domain_id = null) => ({ strand_id, domain_id, backbone_position: pos })
const geom = [
  nuc('s1', [0, 0, 0]),
  nuc('s1', [2, 4, 6]),
  nuc('s2', [10, 10, 10]),
]

describe('selectionBBox', () => {
  it('boxes the matched strand by multiSelected strandIds', () => {
    const box = selectionBBox(geom, { strandIds: new Set(['s1']) })
    expect(box.min.toArray()).toEqual([0, 0, 0])
    expect(box.max.toArray()).toEqual([2, 4, 6])
  })
  it('matches the single-selected strand id', () => {
    const box = selectionBBox(geom, { selStrandId: 's2' })
    expect(box.min.toArray()).toEqual([10, 10, 10])
    expect(box.max.toArray()).toEqual([10, 10, 10])
  })
  it('matches by domain id', () => {
    const g = [nuc('s1', [1, 1, 1], 'd1'), nuc('s1', [3, 3, 3], 'd2')]
    const box = selectionBBox(g, { domainIds: new Set(['d2']) })
    expect(box.min.toArray()).toEqual([3, 3, 3])
  })
  it('returns null with no selection or no geometry', () => {
    expect(selectionBBox(geom, {})).toBeNull()
    expect(selectionBBox([], { strandIds: new Set(['s1']) })).toBeNull()
    expect(selectionBBox(geom, { strandIds: new Set(['nope']) })).toBeNull()
  })
})

const center = (id, c, size) => ({ id, center: new THREE.Vector3(...c), size })

describe('instanceUnionBox', () => {
  it('unions the half-extents of every wanted instance', () => {
    const centers = [
      center('a', [0, 0, 0], { x: 2, y: 2, z: 2 }),   // → [-1,-1,-1]..[1,1,1]
      center('b', [10, 0, 0], { x: 4, y: 2, z: 2 }),  // → [8,-1,-1]..[12,1,1]
    ]
    const box = instanceUnionBox(centers, new Set(['a', 'b']))
    expect(box.min.toArray()).toEqual([-1, -1, -1])
    expect(box.max.toArray()).toEqual([12, 1, 1])
  })

  it('ignores instances not in the wanted set', () => {
    const centers = [
      center('a', [0, 0, 0], { x: 2, y: 2, z: 2 }),
      center('b', [100, 100, 100], { x: 2, y: 2, z: 2 }),
    ]
    const box = instanceUnionBox(centers, new Set(['a']))
    expect(box.min.toArray()).toEqual([-1, -1, -1])
    expect(box.max.toArray()).toEqual([1, 1, 1])
  })

  it('skips sizeless centers (no `size`)', () => {
    const centers = [
      center('a', [0, 0, 0], { x: 2, y: 2, z: 2 }),
      { id: 'b', center: new THREE.Vector3(50, 50, 50) }, // no size → skipped
    ]
    const box = instanceUnionBox(centers, new Set(['a', 'b']))
    expect(box.max.toArray()).toEqual([1, 1, 1])
  })

  it('returns null when nothing matches / inputs empty', () => {
    const centers = [center('a', [0, 0, 0], { x: 2, y: 2, z: 2 })]
    expect(instanceUnionBox(centers, new Set(['nope']))).toBeNull()
    expect(instanceUnionBox(centers, new Set())).toBeNull()
    expect(instanceUnionBox([], new Set(['a']))).toBeNull()
    expect(instanceUnionBox(null, new Set(['a']))).toBeNull()
    expect(instanceUnionBox(centers, null)).toBeNull()
  })

  it('returns null when every matched center is sizeless (union stays empty)', () => {
    const centers = [{ id: 'a', center: new THREE.Vector3(0, 0, 0) }]
    expect(instanceUnionBox(centers, new Set(['a']))).toBeNull()
  })
})

// A half-circle arc of nucleotides in the XZ plane (radius R), mimicking a part
// bent by a `bend` deformation (e.g. the Arm_pulley pulley = ~167° arc). The two
// ENDPOINTS sit at z=0; the arc bulges out to z=R in the MIDDLE. A box built from
// endpoints/chords only (the old mid-LOD box) collapses to z≈0 and fails to bound
// the bulge — that's the torus-selection-box bug this guards against.
const HALF_ARC_R = 10
function halfArcNucs(R = HALF_ARC_R, stepDeg = 5) {
  const out = []
  for (let a = 0; a <= 180; a += stepDeg) {
    const r = (a * Math.PI) / 180
    out.push({ strand_id: 's', backbone_position: [R * Math.cos(r), 0, R * Math.sin(r)] })
  }
  return out
}

describe('nucleotideLocalBox', () => {
  it('bounds a straight bundle tightly', () => {
    const nucs = [
      { strand_id: 's', backbone_position: [0, 0, 0] },
      { strand_id: 's', backbone_position: [0, 20, 0] },
      { strand_id: 's', backbone_position: [2, 10, 1] },
    ]
    const box = nucleotideLocalBox(nucs)
    expect(box.min.toArray()).toEqual([0, 0, 0])
    expect(box.max.toArray()).toEqual([2, 20, 1])
  })

  it('FOLLOWS THE BEND — bounds the arc bulge a chord box would miss', () => {
    const nucs = halfArcNucs()
    const box = nucleotideLocalBox(nucs)
    // x spans the full diameter, z spans 0..R (the bulge) — NOT collapsed.
    expect(box.min.x).toBeCloseTo(-HALF_ARC_R, 5)
    expect(box.max.x).toBeCloseTo(HALF_ARC_R, 5)
    expect(box.max.z).toBeCloseTo(HALF_ARC_R, 5)   // bulge captured
    // every nucleotide is contained (this is the property the selection box must hold)
    expect(nucleotideBoxOverflow(nucs, box)).toBe(0)
  })

  it('includes overhang nucleotides (no strand-type filter)', () => {
    const nucs = [
      { strand_id: 's', backbone_position: [0, 0, 0] },
      { overhang_id: 'o', backbone_position: [0, 0, 9] }, // poking overhang, no strand_id
    ]
    expect(nucleotideLocalBox(nucs).max.z).toBe(9)
  })

  it('returns null for empty / unpositioned input', () => {
    expect(nucleotideLocalBox([])).toBeNull()
    expect(nucleotideLocalBox(null)).toBeNull()
    expect(nucleotideLocalBox([{ strand_id: 's' }])).toBeNull()
  })
})

describe('nucleotideBoxOverflow (geometry-fits-its-box validation)', () => {
  it('detects geometry extending beyond a chord-collapsed box (the bug)', () => {
    const nucs = halfArcNucs()
    // The OLD-style box: built only from the two endpoints (z=0 both) → a flat
    // slab that misses the bulge, exactly like the per-helix mid-LOD chord box.
    const endpoints = [nucs[0], nucs[nucs.length - 1]]
    const chordBox = nucleotideLocalBox(endpoints)
    expect(chordBox.max.z).toBeCloseTo(0, 5)             // collapsed
    // validation flags the overflow ≈ the arc radius
    expect(nucleotideBoxOverflow(nucs, chordBox)).toBeCloseTo(HALF_ARC_R, 1)
  })

  it('reports 0 when every nucleotide is inside the box', () => {
    const nucs = halfArcNucs()
    expect(nucleotideBoxOverflow(nucs, nucleotideLocalBox(nucs))).toBe(0)
  })

  it('honours tol slack', () => {
    const nucs = [{ strand_id: 's', backbone_position: [0, 0, 0] }, { strand_id: 's', backbone_position: [0, 0, 10.3] }]
    const box = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, 10))
    expect(nucleotideBoxOverflow(nucs, box)).toBeCloseTo(0.3, 5)  // no tol → flagged
    expect(nucleotideBoxOverflow(nucs, box, { tol: 0.5 })).toBe(0) // within slack → clean
  })

  it('validates a GROUP: transformed members stay inside the world union box', () => {
    // Two instances of the bent part, each placed by a different rigid transform.
    // Build each instance box from the local box, union them like the renderer's
    // getInstanceCenters + instanceUnionBox path, then assert no transformed
    // member nucleotide escapes the union (overflow 0 per instance).
    const nucs = halfArcNucs()
    const localBox = nucleotideLocalBox(nucs)
    const size = localBox.getSize(new THREE.Vector3())
    const center = localBox.getCenter(new THREE.Vector3())

    const tA = new THREE.Matrix4().makeTranslation(0, 0, 0)
    const tB = new THREE.Matrix4()
      .makeRotationY(Math.PI)
      .premultiply(new THREE.Matrix4().makeTranslation(0, 40, 0))

    const centers = [tA, tB].map((m, i) => ({
      id: `i${i}`,
      center: center.clone().applyMatrix4(m),
      size: { x: size.x, y: size.y, z: size.z },
    }))
    // NOTE: instanceUnionBox uses the AABB center+size, so a rotated instance's
    // world box is the (rotation-grown) AABB — still a valid OUTER bound.
    const union = instanceUnionBox(centers, new Set(['i0', 'i1']))

    // pad the union by the rotation-induced AABB growth tolerance and assert
    // every transformed nucleotide is contained.
    expect(nucleotideBoxOverflow(nucs, union, { transform: tA })).toBe(0)
    expect(nucleotideBoxOverflow(nucs, union, { transform: tB })).toBe(0)
  })
})
