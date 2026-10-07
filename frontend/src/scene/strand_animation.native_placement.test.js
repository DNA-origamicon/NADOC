// @vitest-environment node
import { describe, expect, it, vi } from 'vitest'
import { existsSync } from 'node:fs'
import * as THREE from 'three'
import positions from './fixtures/native_animation_positions.json'
import { initOverhangStrandAnim } from './overhang_strand_anim.js'
import { initOverhangUnzipOverlay } from './overhang_unzip_overlay.js'
import { buildHelixObjects } from './helix_renderer.js'
import { createStrandRenderer } from '../strand-anim/strand_renderer.js'
import { initStrandAnimApp } from '../strand-anim/app.js'
import * as removedModel from '../strand-anim/model.js'
import { nativePoseFrame, transportNativePose } from './native_pose_transport.js'

// Fixed canonical backend Manual_Benchy h_XY_0_0 sites 0–2, both directions.
// No helix radius, groove, slab solver, or recalculated molecular golden here.
function fixture({ complete = true } = {}) {
  const geometry = structuredClone(positions).filter(n => complete || n.direction !== 'REVERSE' || n.bp_index !== 0)
  for (const n of geometry) Object.assign(n, { copy_k: 0, domain_index: 0, strand_type: 'staple',
    strand_id: n.direction === 'FORWARD' ? 'overhang' : n.bp_index === 0 ? 'target' : 'binder',
    overhang_id: n.direction === 'FORWARD' ? 'oh' : undefined })
  const design = { helices: [{ id: 'h_XY_0_0', axis_start: [0, 0, 0], axis_end: [0, 0, 1] }],
    strands: ['overhang', 'binder', 'target'].map(id => ({ id, strand_type: 'staple', domains: [] })) }
  return { geometry, design }
}
const key = n => `${n.helix_id}:${n.bp_index}:${n.direction}:${n.copy_k ?? 0}`
const local = (n, field) => new THREE.Vector3(...n[field]).sub(new THREE.Vector3(...n.backbone_position))
  .applyQuaternion(new THREE.Quaternion(...n.slab_quaternion).invert())
function sameRegistration(pose, captured) {
  for (const field of ['base_position', 'slab_position']) expect(local(pose, field).distanceTo(local(captured, field))).toBeLessThan(1e-12)
}
function matrix(mesh, index) { const result = new THREE.Matrix4(); mesh.getMatrixAt(index, result); return result }

describe('[native-placement] captured strand animation', () => {
  it('keeps the canonical internal registration throughout unzip and restores exact complete poses', () => {
    const { geometry, design } = fixture(), setBeadOverrides = vi.fn()
    const driver = initOverhangStrandAnim({ getHelixCtrl: () => ({ setBeadOverrides }),
      getGeometry: () => geometry, getDesign: () => design })
    expect(driver.bind('oh', 'binder').ok).toBe(true)
    const captured = new Map(geometry.map(n => [key(n), n]))
    for (const phi of [1, .7, .25, 0]) {
      driver.setPhi(phi, { mode: 'unzip', form: 'helical', thetaDeg: 35 })
      for (const pose of setBeadOverrides.mock.lastCall[0]) sameRegistration(pose, captured.get(key(pose)))
    }
    driver.clear()
    for (const restored of setBeadOverrides.mock.lastCall[0]) expect(restored).toEqual(captured.get(key(restored)))
  })

  it('draws a bound invader from exact captured opposite positions and slab poses', () => {
    const { geometry, design } = fixture(), scene = new THREE.Scene()
    const driver = initOverhangStrandAnim({ getHelixCtrl: () => ({ setBeadOverrides: vi.fn() }),
      getGeometry: () => geometry, getDesign: () => design, getScene: () => scene })
    expect(driver.bind('oh', 'binder').hasToehold).toBe(true)
    driver.setPhi(1, { mode: 'displacement', form: 'helical', thetaDeg: 35 })
    const beads = scene.getObjectByName('strandBeads'), slabs = scene.getObjectByName('strandSlabs')
    const targets = geometry.filter(n => n.direction === 'REVERSE')
    for (let i = 0; i < targets.length; i++) {
      expect(new THREE.Vector3().setFromMatrixPosition(matrix(beads, i)).distanceTo(new THREE.Vector3(...targets[i].backbone_position))).toBeLessThan(1e-7)
      expect(new THREE.Vector3().setFromMatrixPosition(matrix(slabs, i)).distanceTo(new THREE.Vector3(...targets[i].slab_position))).toBeLessThan(1e-7)
    }
    driver.dispose()
  })

  it('fails before moving any molecule when a toehold lacks an authoritative invader target', () => {
    const { geometry, design } = fixture({ complete: false }), setBeadOverrides = vi.fn(), scene = new THREE.Scene()
    const driver = initOverhangStrandAnim({ getHelixCtrl: () => ({ setBeadOverrides }),
      getGeometry: () => geometry, getDesign: () => design, getScene: () => scene })
    expect(driver.bind('oh', 'binder').ok).toBe(true)
    expect(() => driver.setPhi(.5, { mode: 'displacement' })).toThrow(/complementary pose/)
    expect(setBeadOverrides).not.toHaveBeenCalled()
    expect(scene.children).toHaveLength(0)
  })

  it('preserves complete pose and loop-copy identity through actual renderer overrides', () => {
    const { geometry, design } = fixture(), original = geometry[0]
    const second = { ...structuredClone(original), copy_k: 1 }
    const ctrl = buildHelixObjects([original, second], design, new THREE.Scene())
    const q = nativePoseFrame(second, [1, .3, 0], [0, 0, 1])
    const moved = transportNativePose(second, [3, 4, 5], q)
    ctrl.setBeadOverrides([moved])
    const entries = ctrl.backboneEntries
    expect(entries[0].pos.toArray()).toEqual(original.backbone_position)
    expect(entries[1].pos.toArray()).toEqual([3, 4, 5])
    const slab = ctrl.slabEntries[1]
    expect(new THREE.Vector3().setFromMatrixPosition(matrix(slab.instMesh, slab.id))
      .distanceTo(new THREE.Vector3(...moved.slab_position))).toBeLessThan(4e-7)
    expect(() => ctrl.setBeadOverrides([{ ...moved, slab_position: undefined }])).toThrow(/slab_position/)
    const sparse = buildHelixObjects([second], design, new THREE.Scene())
    sparse.setBeadOverrides([moved])
    expect(sparse.backboneEntries[0].pos.toArray()).toEqual([3, 4, 5])
  })

  it('transports slab orientation with the hinge in the second document animation driver', () => {
    const { geometry, design } = fixture(), setBeadOverrides = vi.fn()
    geometry.filter(n => n.direction === 'REVERSE').forEach(n => { n.overhang_id = 'oh2' })
    design.cluster_transforms = [{ id: 'cluster', helix_ids: ['h_XY_0_0'] }]
    const overlay = initOverhangUnzipOverlay({ getHelixCtrl: () => ({ setBeadOverrides }), getDesign: () => design })
    overlay.update([{ binding: { overhang_a_id: 'oh', overhang_b_id: 'oh2' }, phi: .4,
      hinge: { clusterId: 'cluster', axisDir: [0, 1, 0], deltaRad: .7, J: [0, 0, 0] } }], geometry)
    const captured = new Map(geometry.map(n => [key(n), n]))
    for (const pose of setBeadOverrides.mock.lastCall[0]) sameRegistration(pose, captured.get(key(pose)))
    overlay.clear()
    for (const restored of setBeadOverrides.mock.lastCall[0]) expect(restored).toEqual(captured.get(key(restored)))
  })

  it('rejects the old partial renderer contract and removes synthetic placement generators', () => {
    const scene = new THREE.Scene(), renderer = createStrandRenderer(scene)
    expect(() => renderer.update([{ pos: new Float32Array(3), tan: [0, 0, 1], bn: [1, 0, 0] }])).toThrow(/complete backend-authorized poses/)
    expect(scene.children).toHaveLength(0)
    expect(() => initStrandAnimApp()).toThrow(/unavailable/)
    expect(removedModel.buildStrandGeometry).toBeUndefined()
    for (const name of ['geometry_helical', 'geometry_straight', 'geometry_displacement']) {
      expect(existsSync(new URL(`../strand-anim/${name}.js`, import.meta.url))).toBe(false)
    }
  })
})
