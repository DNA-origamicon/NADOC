import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { transformPacket } from '../test-helpers/transform_preview.js'
import { createTransformHistoryTool, composeHistoricalResidueDraft } from './transform_history_tool.js'
import { initClusterGizmo } from './cluster_gizmo.js'

const owners = [], tick = async () => { for (let i = 0; i < 5; i++) await Promise.resolve() }
function fixture(packet = transformPacket(), options = {}) {
  packet.evaluated_command_kind = packet.command_kind
  packet.control_context.placement_upgrade ??= { upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64) }
  const source = structuredClone(packet), scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
  const controls = { enabled: false }, canvas = document.createElement('canvas')
  let callbacks
  const binding = { update: vi.fn(), setStatus: vi.fn(), release: vi.fn() }
  const panel = { bindHistorySession: vi.fn(value => { callbacks = value; return binding }) }
  const onChange = vi.fn(), onReset = vi.fn(), onApply = vi.fn(), onCancel = vi.fn(), onError = vi.fn()
  const preview = { candidateGeometry: () => ({ records: packet.candidate?.nucleotides ?? [],
    backboneEntries: (packet.candidate?.nucleotides ?? []).map(nuc => ({ nuc, pos: new THREE.Vector3(...nuc.backbone_position) })),
    helixAxes: {}, native: { residueTransformInfo: target => ({ centroid: new THREE.Vector3(target.bp_index, 0, 0) }) } }) }
  const owner = createTransformHistoryTool({ scene, camera, canvas, controls, panel, preview, onChange, onReset, onApply, onCancel, onError, ...options })
  owners.push(owner); owner.open(packet)
  return { owner, packet, source, scene, camera, controls, canvas, panel, preview, binding, onChange, onReset, onApply, onCancel, onError,
    callbacks: () => callbacks }
}
afterEach(() => { for (const owner of owners.splice(0)) owner.dispose() })
it('uses the real private placement gizmo for exact numeric edits and preserves metadata without mutating packet', async () => {
  const packet = transformPacket(); Object.assign(packet.control_state.inputs, { name: 'Authored name', color: '#abcdef' })
  const f = fixture(packet); expect(f.onChange).not.toHaveBeenCalled()
  f.callbacks().onTransform([3, 2, 1], [0, 0, 90]); await tick()
  expect(f.onChange.mock.lastCall[0]).toMatchObject({ translation: [3, 2, 1], pivot: expect.any(Array) })
  expect(f.packet).toEqual(f.source)
  const helper = f.scene.children.find(node => node.controls)
  expect(helper.layers.isEnabled(31)).toBe(true)
  f.owner.dispose(); expect(f.scene.children).toHaveLength(0); expect(f.controls.enabled).toBe(false)
  expect(f.binding.release).toHaveBeenCalledOnce()
})
it('uses native historical joint limits and delegates frame/snap controls to the existing gizmo', async () => {
  const p = transformPacket(); p.control_state.cluster_joints = [{ id: 'joint', name: 'Hinge', cluster_id: 'placement',
    axis_origin: [0, 0, 0], axis_direction: [0, 0, 1], local_axis_origin: [0, 0, 0], local_axis_direction: [0, 0, 1],
    min_angle_deg: -20, max_angle_deg: 25 }]
  const f = fixture(p); f.callbacks().onPivot('joint'); f.callbacks().onJointAngle(90); await tick()
  const q = f.onChange.mock.lastCall[0].rotation
  expect(2 * Math.atan2(q[2], q[3]) * 180 / Math.PI).toBeCloseTo(25)
  f.callbacks().onFrame('local'); f.callbacks().onSnap(45)
  expect(f.binding.update).toHaveBeenCalledWith(expect.objectContaining({ jointMode: true }))
})
it('uses native duplex rest pivots and existing pose rebase without a canonical request', async () => {
  const p = transformPacket(), owner = p.control_state.cluster_transforms[0]
  owner.overhang_duplex_driver_id = 'driver'; owner.rotation = [0, 0, Math.SQRT1_2, Math.SQRT1_2]
  p.control_state.placement_constraints[0].rotation_points = [{ kind: 'centroid', label: 'Centroid', overhang_id: null, point: [0, 0, 0] },
    { kind: 'overhang_root', label: 'Driver root', overhang_id: 'driver', point: [2, 0, 0] }]
  const f = fixture(p); await f.callbacks().onPivot('dup:root:driver'); await tick()
  expect(f.onChange.mock.lastCall[0]).toMatchObject({ pivot: [2, 0, 0] })
  expect(f.onChange.mock.lastCall[0].translation[0]).toBeCloseTo(-2)
  expect(f.onChange.mock.lastCall[0].translation[1]).toBeCloseTo(2)
})
it('explicitly upgrades one owner with full frame-bound poses and preserves original lease role', async () => {
  const f = fixture(); await f.callbacks().onUpgrade(); f.callbacks().onTransform([1, 0, 0], [0, 0, 0]); await tick()
  const draft = f.onChange.mock.lastCall[0]
  expect(draft).toMatchObject({ upgrade_to: 'placement-poses-v1', expected_definition_sha256: 'a'.repeat(64), definition: {
    _proof_version: 1, primary_cluster_id: 'placement', selected_cluster_ids: ['placement'],
    poses: [{ cluster_id: 'placement', parent_cluster_id: null, overhang_duplex_driver_id: null, translation: [1, 0, 0] }],
    authoring: { mode: 'free', pivot_id: 'centroid', joint_id: null, fixed_cluster_ids: [] } } })
  expect(draft.definition).not.toHaveProperty('primary_authored_fields'); expect(draft.definition).not.toHaveProperty('legacy_source')
  expect(f.packet.command_kind).toBe('cluster_op')
})
it('Reset delegates draft replacement and never invokes canonical reset', () => {
  const f = fixture(); f.callbacks().onReset(); expect(f.onReset).toHaveBeenCalledOnce(); expect(f.onChange).not.toHaveBeenCalled()
})
it('expired or unresolved publication locks private inputs and delegates Cancel without closing locally', async () => {
  const f = fixture(); f.owner.setStatus({ expired: true }); f.callbacks().onTransform([1, 0, 0], [0, 0, 0]); await tick()
  expect(f.onChange).not.toHaveBeenCalled(); f.callbacks().onCancel(); expect(f.onCancel).toHaveBeenCalledOnce()
  expect(f.binding.release).not.toHaveBeenCalled()
})
it('reset feature has no movement gizmo and uses the same owned Apply/Cancel controls', () => {
  const p = transformPacket(); p.command_kind = 'nucleotide-transform-delete'; p.control_state.inputs = { _proof_version: 1, transform_id: 'pose', target: ['base', 'h', 0, 'FORWARD', 0] }
  p.control_context.inputs = structuredClone(p.control_state.inputs)
  const f = fixture(p); expect(f.scene.children).toHaveLength(0)
  expect(f.binding.update).toHaveBeenCalledWith(expect.objectContaining({ role: 'reset' }))
  f.callbacks().onApply(); expect(f.onApply).toHaveBeenCalledOnce()
})
it('composes exact ordinary and extra-base historical bodies without changing compose or target identity', () => {
  const baseline = [{ kind: 'base', helix_id: 'h', bp_index: 3, direction: 'REVERSE', copy_k: 2, compose: false,
    pivot: [1, 0, 0], translation: [2, 0, 0], rotation: [0, 0, 0, 1] },
  { kind: 'extra_base', crossover_id: 'junction', extra_base_k: 1, compose: true,
    pivot: [0, 0, 0], translation: [0, 1, 0], rotation: [0, 0, 0, 1] }]
  const delta = baseline.map(body => ({ ...body, pivot: [0, 0, 0], translation: [3, 4, 0], rotation: [0, 0, 0, 1], compose: true }))
  const out = composeHistoricalResidueDraft(baseline, delta)
  expect(out[0]).toEqual({ ...baseline[0], translation: [5, 4, 0] })
  expect(out[1]).toEqual({ ...baseline[1], translation: [3, 5, 0] })
  expect(() => composeHistoricalResidueDraft(baseline, [delta[1], delta[0]])).toThrow(/target/i)
})
it('drives nucleotide history through exact saved targets, not current selection, retaining compose false', async () => {
  const p = transformPacket(); p.command_kind = 'nucleotide-transform'; p.control_state.inputs = {
    _proof_version: 1, history_seed: '11111111-1111-4111-8111-111111111111', kind: 'base', helix_id: 'h', bp_index: 0,
    direction: 'FORWARD', copy_k: 0, compose: false, pivot: [0, 0, 0], translation: [1, 0, 0], rotation: [0, 0, 0, 1] }
  p.control_context.inputs = structuredClone(p.control_state.inputs)
  const f = fixture(p), tc = f.scene.children.find(node => node.controls).controls
  tc.dispatchEvent({ type: 'dragging-changed', value: true }); tc.object.position.x += 2; tc.dispatchEvent({ type: 'change' })
  tc.dispatchEvent({ type: 'dragging-changed', value: false }); await tick()
  expect(f.onChange.mock.lastCall[0]).toMatchObject({ kind: 'base', helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy_k: 0,
    compose: false, translation: [3, 0, 0] })
  expect(f.packet).toEqual(f.source)
})
it('retains every auxiliary native pending owner only after explicit upgrade, and blocks premature Apply', async () => {
  const packet = transformPacket(), primary = packet.control_state.cluster_transforms[0]
  packet.control_state.cluster_transforms.push({ ...structuredClone(primary), id: 'link', name: 'Link', parent_cluster_id: 'placement' })
  let gizmo
  const f = fixture(packet, { createClusterGizmo: (...args) => (gizmo = initClusterGizmo(...args)) })
  gizmo.setPendingTransform('link', { pivot: [2, 0, 0], translation: [0, 4, 0], rotation: [0, 0, 0, 1] })
  f.callbacks().onTransform([1, 0, 0], [0, 0, 0]); await tick()
  expect(f.onChange).not.toHaveBeenCalled(); expect(f.onError.mock.lastCall[0].message).toMatch(/explicit/i)
  f.callbacks().onApply(); expect(f.onApply).not.toHaveBeenCalled()
  f.callbacks().onUpgrade(); await tick()
  expect(f.onChange.mock.lastCall[0].definition.poses).toEqual([
    { cluster_id: 'placement', pivot: [0, 0, 0], translation: [1, 0, 0], rotation: [0, 0, 0, 1], parent_cluster_id: null, overhang_duplex_driver_id: null },
    { cluster_id: 'link', pivot: [2, 0, 0], translation: [0, 4, 0], rotation: [0, 0, 0, 1], parent_cluster_id: 'placement', overhang_duplex_driver_id: null },
  ])
})
it('locked historical joint blocks both numeric input and the real gesture owner', async () => {
  const p = transformPacket(); p.control_state.cluster_joints = [{ id: 'joint', name: 'Locked', cluster_id: 'placement',
    axis_origin: [0, 0, 0], axis_direction: [0, 0, 1], min_angle_deg: 10, max_angle_deg: 10 }]
  const f = fixture(p); f.callbacks().onPivot('joint')
  expect(f.scene.children).toHaveLength(0)
  f.callbacks().onJointAngle(10); f.callbacks().onTransform([1, 0, 0], [0, 0, 0]); await tick()
  expect(f.onChange).not.toHaveBeenCalled()
})
it('nucleotide Escape delegates Cancel exactly once and retains its owner until the controller closes', () => {
  const p = transformPacket(); p.command_kind = 'nucleotide-transform'; p.control_state.inputs = {
    _proof_version: 1, history_seed: '11111111-1111-4111-8111-111111111111', kind: 'base', helix_id: 'h', bp_index: 0,
    direction: 'FORWARD', copy_k: 0, compose: true, pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1] }
  p.control_context.inputs = structuredClone(p.control_state.inputs)
  const f = fixture(p)
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(f.onCancel).toHaveBeenCalledOnce(); expect(f.binding.release).not.toHaveBeenCalled()
  f.owner.dispose(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(f.onCancel).toHaveBeenCalledOnce()
})
it('controls-only replies update historical constraints without emitting a new draft or changing source controls', () => {
  const f = fixture(), next = structuredClone(f.packet)
  next.candidate = null; next.control_state.placement_constraints[0].tethers = [{ moving: { helix_id: 'h', bp: 0, direction: 'FORWARD' },
    fixed: { helix_id: 'h', bp: 1, direction: 'FORWARD' }, contour_nm: 1, rigid: false }]
  f.owner.update(next)
  expect(f.binding.update.mock.lastCall[0].pivots).toContainEqual({ id: 'ssdna', label: 'Constrained (tethers)' })
  expect(f.onChange).not.toHaveBeenCalled(); expect(f.packet).toEqual(f.source)
})
it('refuses auxiliary motion of an explicitly fixed owner without dropping its pose', async () => {
  const p = transformPacket(), primary = p.control_state.cluster_transforms[0]
  p.command_kind = 'placement-poses'
  p.control_state.cluster_transforms.push({ ...structuredClone(primary), id: 'fixed' })
  const definition = { _proof_version: 1, primary_cluster_id: 'placement', selected_cluster_ids: ['placement'],
    poses: [{ cluster_id: 'placement', pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1], parent_cluster_id: null, overhang_duplex_driver_id: null }],
    authoring: { mode: 'free', joint_id: null, pivot_id: 'centroid', fixed_cluster_ids: ['fixed'] }, primary_authored_fields: {}, legacy_source: 'translate' }
  p.control_state.inputs = structuredClone(definition); p.control_context.inputs = structuredClone(definition)
  let gizmo
  const f = fixture(p, { createClusterGizmo: (...args) => (gizmo = initClusterGizmo(...args)) })
  gizmo.setPendingTransform('fixed', { pivot: [0, 0, 0], translation: [1, 0, 0], rotation: [0, 0, 0, 1] })
  f.callbacks().onTransform([2, 0, 0], [0, 0, 0]); await tick()
  expect(f.onChange).not.toHaveBeenCalled(); expect(f.onError.mock.lastCall[0].message).toMatch(/fixed/i)
  f.callbacks().onApply(); expect(f.onApply).not.toHaveBeenCalled()
})
it('multi-owner numeric fields and relative steps start at group delta, preserving posed owner baselines', async () => {
  const p = transformPacket(), a = p.control_state.cluster_transforms[0]
  a.translation = [5, 2, 0]; a.rotation = [0, 0, Math.SQRT1_2, Math.SQRT1_2]
  p.control_state.cluster_transforms.push({ ...structuredClone(a), id: 'second', name: 'Second', translation: [-3, 1, 0] })
  p.command_kind = 'placement-poses'
  const definition = { _proof_version: 1, primary_cluster_id: 'placement', selected_cluster_ids: ['placement', 'second'],
    poses: p.control_state.cluster_transforms.map(c => ({ cluster_id: c.id, pivot: c.pivot, translation: c.translation,
      rotation: c.rotation, parent_cluster_id: null, overhang_duplex_driver_id: null })),
    authoring: { mode: 'free', joint_id: null, pivot_id: 'centroid', fixed_cluster_ids: [] }, primary_authored_fields: {}, legacy_source: 'translate' }
  p.control_state.inputs = structuredClone(definition); p.control_context.inputs = structuredClone(definition)
  const f = fixture(p)
  for (const field of ['translation', 'euler']) {
    expect(f.binding.update.mock.lastCall[0][field]).toHaveLength(3)
    for (const value of f.binding.update.mock.lastCall[0][field]) expect(value).toBeCloseTo(0)
  }
  f.callbacks().onStep('z', 45, 'world'); await tick()
  const poses = f.onChange.mock.lastCall[0].poses
  expect(2 * Math.atan2(poses[0].rotation[2], poses[0].rotation[3]) * 180 / Math.PI).toBeCloseTo(135)
  const center = [1, 1.5, 0], angle = Math.PI / 4
  for (let i = 0; i < 2; i++) {
    const before = definition.poses[i].translation, x = before[0] - center[0], y = before[1] - center[1]
    expect(poses[i].translation[0]).toBeCloseTo(center[0] + Math.cos(angle) * x - Math.sin(angle) * y)
    expect(poses[i].translation[1]).toBeCloseTo(center[1] + Math.sin(angle) * x + Math.cos(angle) * y)
  }
  f.owner.setStatus({ busy: 'apply' }); f.owner.setStatus({ busy: null, error: new Error('Downstream input needs repair') })
  for (const field of ['translation', 'euler']) {
    expect(f.binding.update.mock.lastCall[0][field]).toHaveLength(3)
    for (const value of f.binding.update.mock.lastCall[0][field]) expect(value).toBeCloseTo(0)
  }
  f.callbacks().onTransform([1, 0, 0], [0, 0, 0]); await tick()
  for (let i = 0; i < 2; i++) {
    expect(f.onChange.mock.lastCall[0].poses[i].translation[0]).toBeCloseTo(poses[i].translation[0] + 1)
    expect(f.onChange.mock.lastCall[0].poses[i].translation[1]).toBeCloseTo(poses[i].translation[1])
  }
})
it('controls-only projection suspends real geometry gestures and numeric drafts until a full accepted pane returns', async () => {
  const f = fixture(), off = structuredClone(f.packet); off.candidate = null
  // The renderer has disposed the old pane before delivering its controls-only packet.
  const native = f.preview.candidateGeometry
  f.preview.candidateGeometry = () => null
  f.owner.update(off)
  expect(f.scene.children).toHaveLength(0)
  f.callbacks().onTransform([1, 0, 0], [0, 0, 0]); await tick(); expect(f.onChange).not.toHaveBeenCalled()
  expect(f.binding.setStatus.mock.lastCall[0]).toMatchObject({ inputsUnavailable: true })
  f.callbacks().onApply(); expect(f.onApply).toHaveBeenCalledOnce()
  f.preview.candidateGeometry = native; f.owner.update(f.packet)
  expect(f.scene.children.some(node => node.controls)).toBe(true)
  f.callbacks().onTransform([1, 0, 0], [0, 0, 0]); await tick(); expect(f.onChange).toHaveBeenCalledOnce()
})
