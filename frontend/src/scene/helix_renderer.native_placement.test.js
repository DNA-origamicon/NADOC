// @vitest-environment node
import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'
import { setNativePoseMap } from '../viewer/native_placement.js'

const source = 'native-full-o5-v1'
const design = { helices: [], strands: [{ id: 's', strand_type: 'staple', domains: [] }] }
const identity = { helix_id: 'h', bp_index: 0, direction: 'FORWARD', strand_id: 's', strand_type: 'staple', domain_index: 0 }
// Accepted backend-authority values for Manual_Benchy h_XY_0_0:0:FORWARD.
// These are a fixed regression oracle, not recomputed by the renderer under test.
const start = () => ({ ...identity, placement_source: source,
  backbone_position: [-0.645612580161337, -0.5515026802631344, -0.0152],
  base_position: [-0.23972062915295275, -0.20218550877476973, 0.0326],
  base_normal: [0.8444255998882265, 0.5255463335640475, -0.10366512205556659], axis_tangent: [0, 0, 1],
  slab_position: [-0.3811934359011157, -0.3239392921967217, 0.0003],
  slab_quaternion: [0.3433681770212042, 0.6181409992947685, 0.6181409992947685, 0.3433681770212042] })
function end() {
  const nuc = start()
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(.9, -.6, 1.3))
  const shift = new THREE.Vector3(7, -5, 11)
  for (const field of ['backbone_position', 'base_position', 'slab_position']) {
    nuc[field] = new THREE.Vector3(...nuc[field]).applyQuaternion(q).add(shift).toArray()
  }
  for (const field of ['axis_tangent', 'base_normal']) nuc[field] = new THREE.Vector3(...nuc[field]).applyQuaternion(q).toArray()
  nuc.slab_quaternion = q.clone().multiply(new THREE.Quaternion(...nuc.slab_quaternion)).toArray()
  return nuc
}
function compact(nucleotides) {
  const data = { bp: [], bb: [], bs: [], bn: [], at: [], sp: [], sq: [], pv: [] }
  for (const n of nucleotides) {
    for (const [field, wire] of Object.entries({ bp_index: 'bp', backbone_position: 'bb', base_position: 'bs', base_normal: 'bn', axis_tangent: 'at', slab_position: 'sp', slab_quaternion: 'sq', placement_source: 'pv' })) data[wire].push(n[field])
  }
  return { h: { FORWARD: data } }
}
function build(nucleotides) { return buildHelixObjects(structuredClone(nucleotides), design, new THREE.Scene()) }
function matrix(entry) { const m = new THREE.Matrix4(); entry.instMesh.getMatrixAt(entry.id, m); return m }
function expectSameRendered(a, b) {
  for (const field of ['backboneEntries', 'slabEntries']) {
    expect(a[field].length).toBe(b[field].length)
    a[field].forEach((entry, i) => {
      const expected = matrix(b[field][i]).elements
      matrix(entry).elements.forEach((v, j) => expect(v).toBeCloseTo(expected[j], 6))
    })
  }
}
function baked(nucleotides) {
  const result = { posMap: new Map(), axesMap: new Map([['h', { start: new THREE.Vector3(0, 0, 0), end: new THREE.Vector3(0, 0, 1) }]]), bnMap: new Map() }
  for (const n of nucleotides) {
    setNativePoseMap(result.posMap, new THREE.Vector3(...n.backbone_position), n)
    result.bnMap.set('h:0:FORWARD', new THREE.Vector3(...n.base_normal))
  }
  return result
}

describe('[native-placement] actual Full renderer authority', () => {
  it('renders the backend slab center and quaternion without solving from a partner', () => {
    const n = start(), ctrl = build([n])
    const position = new THREE.Vector3(), quaternion = new THREE.Quaternion()
    matrix(ctrl.slabEntries[0]).decompose(position, quaternion, new THREE.Vector3())
    expect(position.distanceTo(new THREE.Vector3(...n.slab_position))).toBeLessThan(1e-7)
    expect(Math.abs(quaternion.dot(new THREE.Quaternion(...n.slab_quaternion)))).toBeCloseTo(1, 7)
  })

  it('makes incremental edits, history return, and rebuilding produce identical bead/slab matrices', () => {
    const a = start(), b = end()
    // A new canonical response can legitimately represent different authored
    // chemistry; cached first-build offsets must never override its actual pose.
    b.placement_source = 'authored-residue-c1-v1'
    b.slab_position[0] += .041
    const ctrl = build([a])
    ctrl.applyPositionsUpdate(compact([b]))
    expectSameRendered(ctrl, build([b]))
    ctrl.applyPositionsUpdate(compact([a]))
    expectSameRendered(ctrl, build([a]))
  })

  it('preserves authoritative slab poses when patching partial geometry after a cluster edit', () => {
    const a = start(), b = end(), ctrl = build([a])
    b.placement_source = 'authored-residue-c1-v1'
    b.slab_position[0] += .041
    ctrl.patchNucleotides([b], {}, new Set())
    expectSameRendered(ctrl, build([b]))
    ctrl.patchNucleotides([a], {}, new Set())
    expectSameRendered(ctrl, build([a]))
  })

  it('updates bridge poses with the same authority as a fresh build', () => {
    const ctrl = build([start()]), target = end()
    target.placement_source = 'authored-residue-c1-v1'
    target.slab_position[2] += .017
    ctrl.applyBridgeNucsUpdate([target])
    expectSameRendered(ctrl, build([target]))
  })

  it('preserves distinct inserted nucleotide copies during a positions-only update', () => {
    const a = start(), b = start(); b.backbone_position[2] += .16; b.base_position[2] += .16; b.slab_position[2] += .16
    const targetA = end(), targetB = end(); targetB.backbone_position[1] += .3; targetB.base_position[1] += .3; targetB.slab_position[1] += .3
    const ctrl = build([a, b])
    ctrl.applyPositionsUpdate(compact([targetA, targetB]))
    expectSameRendered(ctrl, build([targetA, targetB]))
  })

  it('renders both deformation and baked animation endpoints exactly as fresh Full builds', () => {
    const a = start(), b = end(), straight = baked([a]), bent = baked([b])
    const ctrl = build([b])
    ctrl.applyDeformLerp(straight.posMap, straight.axesMap, straight.bnMap, null, 0)
    expectSameRendered(ctrl, build([a]))
    ctrl.applyDeformLerp(straight.posMap, straight.axesMap, straight.bnMap, null, 1)
    expectSameRendered(ctrl, build([b]))
    ctrl.applyPositionLerp(straight, bent, 0)
    expectSameRendered(ctrl, build([a]))
    ctrl.applyPositionLerp(straight, bent, 1)
    expectSameRendered(ctrl, build([b]))
  })

  it('uses the complete local straight pose even when helix endpoint axes are unavailable', () => {
    const a = start(), b = end(), straight = baked([a]), ctrl = build([b])
    ctrl.applyDeformLerp(straight.posMap, new Map(), straight.bnMap, null, 0)
    expectSameRendered(ctrl, build([a]))
    ctrl.revertToGeometry(straight.posMap, new Map())
    expectSameRendered(ctrl, build([a]))
  })

  it('preserves bead-to-slab distance throughout deformation and history animation', () => {
    const a = start(), b = end(), straight = baked([a]), bent = baked([b])
    const expected = new THREE.Vector3(...a.slab_position).distanceTo(new THREE.Vector3(...a.backbone_position))
    const ctrl = build([b])
    for (const t of [.1, .25, .5, .8]) {
      for (const apply of [() => ctrl.applyDeformLerp(straight.posMap, straight.axesMap, straight.bnMap, null, t),
        () => ctrl.applyPositionLerp(straight, bent, t)]) {
        apply()
        const bead = new THREE.Vector3().setFromMatrixPosition(matrix(ctrl.backboneEntries[0]))
        const slab = new THREE.Vector3().setFromMatrixPosition(matrix(ctrl.slabEntries[0]))
        expect(bead.distanceTo(slab)).toBeCloseTo(expected, 6)
      }
    }
  })

  it('keeps committed rigid transforms identical to rebuilding the committed authority', () => {
    const a = start(), b = start(); b.backbone_position[2] += .167; b.base_position[2] += .167; b.slab_position[2] += .167
    const ctrl = build([a, b])
    ctrl.captureClusterBase(['h'])
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(.3, .7, -.5))
    ctrl.applyClusterTransform(['h'], new THREE.Vector3(), new THREE.Vector3(3, 5, -2), q)
    ctrl.commitClusterPositions(['h'])
    expectSameRendered(ctrl, build(ctrl.backboneEntries.map(e => e.nuc)))
  })

  it.each(['placement_source', 'slab_position', 'slab_quaternion', 'backbone_position', 'base_position'])('refuses missing %s before adding anything to a scene', field => {
    const n = start(), scene = new THREE.Scene(); delete n[field]
    expect(() => buildHelixObjects([n], design, scene)).toThrow(/DNA positioning could not be verified/)
    expect(scene.children).toHaveLength(0)
  })

  it.each([['slab_position', [NaN, 0, 0]], ['slab_quaternion', [0, 0, 0, 0]], ['placement_source', 'legacy']])('refuses invalid %s', (field, value) => {
    const n = start(); n[field] = value
    expect(() => build([n])).toThrow(/DNA positioning could not be verified/)
  })

  it('rejects an incomplete position patch before any existing matrix changes', () => {
    const ctrl = build([start()]), before = matrix(ctrl.backboneEntries[0]).elements.slice()
    const patch = compact([end()]); delete patch.h.FORWARD.sp
    expect(() => ctrl.applyPositionsUpdate(patch)).toThrow(/DNA positioning could not be verified/)
    expect(matrix(ctrl.backboneEntries[0]).elements).toEqual(before)
  })

  it('rejects a native animation endpoint with only a bead position', () => {
    const ctrl = build([start()]), endpoint = baked([start()])
    endpoint.posMap.get('h:0:FORWARD').nativePlacement = null
    expect(() => ctrl.applyPositionLerp(endpoint, endpoint, .5)).toThrow(/DNA positioning could not be verified/)
  })
})
