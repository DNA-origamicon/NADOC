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

// Deliberately collinear or planar fixtures: the existing native solver runs;
// these tests exercise its adapter/ownership contract, not molecular placement.
function constrainedPacket({ kind = 'flexible', reverse = false, compound = false, fixed = [] } = {}) {
  const p = transformPacket(), c = p.control_state, template = p.candidate.nucleotides[0]
  const positions = kind === 'link'
    ? [['h', 0, [0, 0, 0]], ['link-h', 0, [2, 0, 0]], ['link-h', 1, [4, 0, 0]], ['fixed-h', 0, [6, 0, 0]]]
    : [['h', 0, [0, 0, 0]], ['fixed-h', 0, [3, 0, 0]]]
  p.candidate.nucleotides = positions.map(([helix_id, bp_index, backbone_position]) => ({
    ...structuredClone(template), helix_id, bp_index, direction: 'FORWARD', copy_k: 0, backbone_position,
  }))
  c.strands = positions.map(([id]) => ({ id: `strand-${id}`, domains: [{ helix_id: id }] }))
  const primary = c.cluster_transforms[0]
  c.cluster_transforms = [primary,
    ...(kind === 'link' ? [{ ...structuredClone(primary), id: 'link', name: 'Duplex link', helix_ids: ['link-h'], pivot: [3, 0, 0] }] : []),
    { ...structuredClone(primary), id: 'fixed', name: 'Fixed partner', helix_ids: ['fixed-h'], pivot: [kind === 'link' ? 6 : 3, 0, 0] }]
  const anchor = (helix_id, bp = 0) => ({ helix_id, bp, direction: 'FORWARD' })
  if (kind === 'flexible') {
    const a = { strand_id: 'strand-h', domain_index: 0, bp_index: 0, direction: 'FORWARD' }
    const b = { strand_id: 'strand-fixed-h', domain_index: 0, bp_index: 0, direction: 'FORWARD' }
    c.flexible_connections = [{ cluster_a_id: reverse ? 'fixed' : 'placement', cluster_b_id: reverse ? 'placement' : 'fixed',
      anchor_a: reverse ? b : a, anchor_b: reverse ? a : b, contour_length_nm: 3 }]
    c.flexible_gates.placement.gate = true
  } else if (kind === 'taut') {
    primary.overhang_duplex_driver_id = 'driver'
    c.placement_constraints[0].tethers = [{ moving: anchor('h'), fixed: anchor('fixed-h'), contour_nm: 3, rigid: true }]
  } else {
    c.placement_constraints[0].movable_links = [{ kind: 'duplex', link_cluster_id: 'link', helix_ids: ['link-h'], domain_ids: [],
      tethers: [{ l: anchor('link-h'), part: anchor('h'), contour_nm: 2, part_dragged: true },
        { l: anchor('link-h', 1), part: anchor('fixed-h'), contour_nm: 2, part_dragged: false }] }]
  }
  if (compound) {
    p.command_kind = 'placement-poses'
    c.inputs = { _proof_version: 1, primary_cluster_id: 'placement', selected_cluster_ids: ['placement'],
      poses: [{ cluster_id: primary.id, pivot: [...primary.pivot], translation: [...primary.translation], rotation: [...primary.rotation],
        parent_cluster_id: null, overhang_duplex_driver_id: primary.overhang_duplex_driver_id }],
      authoring: { mode: 'tethers', joint_id: null, pivot_id: kind === 'taut' ? 'dup:taut' : 'ssdna', fixed_cluster_ids: fixed },
      primary_authored_fields: { name: 'Preserved authored primary' }, legacy_source: 'translate' }
  }
  p.control_context = { ...structuredClone(c), placement_upgrade: p.control_context.placement_upgrade }
  return p
}
function nativeDrag(f, delta, { release = true } = {}) {
  const tc = f.scene.children.find(node => node.controls).controls
  tc.dispatchEvent({ type: 'dragging-changed', value: true })
  tc.object.position.add(new THREE.Vector3(...delta))
  tc.dispatchEvent({ type: 'change' })
  if (release) tc.dispatchEvent({ type: 'dragging-changed', value: false })
  return tc
}
function ringFixture(initial = {}) {
  const p = transformPacket()
  Object.assign(p.control_state.cluster_transforms[0], structuredClone(initial))
  Object.assign(p.control_state.inputs, structuredClone(initial))
  p.control_context.inputs = structuredClone(p.control_state.inputs)
  p.control_state.cluster_joints = [{ id: 'joint', name: 'Offset hinge', cluster_id: 'placement',
    axis_origin: [2, 0, 0], axis_direction: [0, 0, 1], local_axis_origin: [2, 0, 0], local_axis_direction: [0, 0, 1],
    min_angle_deg: -20, max_angle_deg: 25 }]
  let gizmo
  const f = fixture(p, { createClusterGizmo: (...args) => (gizmo = initClusterGizmo(...args)) })
  f.camera.position.set(2, 0, 40); f.camera.lookAt(2, 0, 0); f.camera.updateMatrixWorld(true)
  f.canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 800 })
  f.canvas.setPointerCapture = vi.fn(); f.canvas.releasePointerCapture = vi.fn()
  f.callbacks().onPivot('joint')
  const ring = f.scene.children.find(node => node.geometry?.type === 'TorusGeometry')
  const r = ring.geometry.parameters.radius
  const pointer = (type, point) => {
    const projected = new THREE.Vector3(...point).project(f.camera)
    f.canvas.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0,
      clientX: (projected.x + 1) * 400, clientY: (1 - projected.y) * 400 }))
  }
  const start = () => pointer('pointerdown', [2 + r, 0, 0])
  const move = (degrees = 90) => pointer('pointermove', [2 + r * Math.cos(degrees * Math.PI / 180), r * Math.sin(degrees * Math.PI / 180), 0])
  const end = () => pointer('pointerup', [2, r, 0])
  return { ...f, gizmo, start, move, end }
}
function expectJointWorldPose(actual, baseline, degrees) {
  const axis = new THREE.Vector3(2, 0, 0)
  for (const coordinates of [[0, 0, 0], [5, -1, 2]]) {
    const point = new THREE.Vector3(...coordinates)
    const expected = point.clone().sub(new THREE.Vector3(...baseline.pivot)).applyQuaternion(new THREE.Quaternion(...baseline.rotation))
      .add(new THREE.Vector3(...baseline.pivot)).add(new THREE.Vector3(...baseline.translation))
      .sub(axis).applyAxisAngle(new THREE.Vector3(0, 0, 1), degrees * Math.PI / 180).add(axis)
    const result = point.clone().sub(new THREE.Vector3(...actual.pivot)).applyQuaternion(new THREE.Quaternion(...actual.rotation))
      .add(new THREE.Vector3(...actual.pivot)).add(new THREE.Vector3(...actual.translation))
    expect(result.distanceTo(expected)).toBeLessThan(1e-10)
  }
}

it.each([false, true])('uses real flexible-tether projection for either native anchor side (reverse=%s)', async reverse => {
  const f = fixture(constrainedPacket({ reverse })); f.callbacks().onPivot('ssdna')
  nativeDrag(f, [-2, 0, 0]); await tick()
  const result = f.onChange.mock.lastCall[0]
  // A slack-only tether rejects stretching, without imposing a new solver tolerance.
  expect(result.translation[0]).toBeLessThan(0)
  expect(result.translation[0]).toBeGreaterThan(-.05)
  expect(result.translation.slice(1)).toEqual([0, 0])
  expect(f.packet).toEqual(f.source); expect(f.onError).not.toHaveBeenCalled()
})
it('preserves the native rigid duplex taut constraint when a drag would shorten its bond', async () => {
  const f = fixture(constrainedPacket({ kind: 'taut' })); f.callbacks().onPivot('dup:taut')
  nativeDrag(f, [1, 0, 0]); await tick()
  const result = f.onChange.mock.lastCall[0]
  expect(result.translation[0]).toBeGreaterThan(0)
  expect(result.translation[0]).toBeLessThan(.05)
  expect(f.packet).toEqual(f.source); expect(f.onError).not.toHaveBeenCalled()
})
it('records all real solved link poses after explicit upgrade and excludes the unmoved fixed partner', async () => {
  let gizmo
  const f = fixture(constrainedPacket({ kind: 'link' }), { createClusterGizmo: (...args) => (gizmo = initClusterGizmo(...args)) })
  f.callbacks().onPivot('ssdna'); nativeDrag(f, [-2, 2, 0]); await tick()
  const native = gizmo.getAllPendingTransforms()
  expect(native.map(value => value.clusterId).sort()).toEqual(['link', 'placement'])
  expect(native.find(value => value.clusterId === 'link').translation.some(value => Math.abs(value) > .01)).toBe(true)
  expect(f.onChange).not.toHaveBeenCalled(); expect(f.onError.mock.lastCall[0].message).toMatch(/explicit/i)
  f.callbacks().onApply(); expect(f.onApply).not.toHaveBeenCalled()
  f.callbacks().onUpgrade(); await tick()
  const definition = f.onChange.mock.lastCall[0].definition
  expect(definition.poses.map(value => value.cluster_id)).toEqual(['placement', 'link'])
  for (const value of native) expect(definition.poses.find(row => row.cluster_id === value.clusterId)).toMatchObject({
    pivot: value.pivot, translation: value.translation, rotation: value.rotation,
    parent_cluster_id: null, overhang_duplex_driver_id: null,
  })
  expect(definition.authoring).toEqual({ mode: 'tethers', pivot_id: 'ssdna', joint_id: null, fixed_cluster_ids: [] })
  expect(f.packet).toEqual(f.source)
})
it('retains complete solved poses and fixed-owner provenance after a failed Apply without another draft', async () => {
  const f = fixture(constrainedPacket({ kind: 'link', compound: true, fixed: ['fixed'] }))
  nativeDrag(f, [-2, 2, 0]); await tick()
  const definition = structuredClone(f.onChange.mock.lastCall[0]), calls = f.onChange.mock.calls.length
  expect(definition.poses.map(value => value.cluster_id)).toEqual(['placement', 'link'])
  expect(definition.authoring.fixed_cluster_ids).toEqual(['fixed'])
  expect(definition.primary_authored_fields).toEqual({ name: 'Preserved authored primary' })
  f.callbacks().onApply(); expect(f.onApply).toHaveBeenCalledOnce()
  f.owner.setStatus({ busy: 'apply' }); f.owner.setStatus({ busy: null, error: new Error('Downstream input needs repair') })
  expect(f.onChange).toHaveBeenCalledTimes(calls)
  expect(f.onChange.mock.lastCall[0]).toEqual(definition)
  f.callbacks().onApply(); expect(f.onApply).toHaveBeenCalledTimes(2)
  expect(f.packet).toEqual(f.source)
})
it('blocks an actual solver-produced write to an explicitly fixed owner instead of dropping it', async () => {
  const f = fixture(constrainedPacket({ kind: 'link', compound: true, fixed: ['link'] }))
  nativeDrag(f, [-2, 2, 0]); await tick()
  expect(f.onChange).not.toHaveBeenCalled(); expect(f.onError.mock.lastCall[0].message).toMatch(/fixed/i)
  f.callbacks().onApply(); expect(f.onApply).not.toHaveBeenCalled()
  expect(f.packet).toEqual(f.source)
})
it('drops queued native solved writes when cancellation tears down their private owner', async () => {
  const f = fixture(constrainedPacket({ kind: 'link', compound: true }))
  nativeDrag(f, [-2, 2, 0])
  f.callbacks().onCancel(); f.owner.dispose(); await tick()
  expect(f.onCancel).toHaveBeenCalledOnce(); expect(f.onChange).not.toHaveBeenCalled()
  expect(f.scene.children).toHaveLength(0); expect(f.controls.enabled).toBe(false)
  expect(f.packet).toEqual(f.source)
})
it('adopts the native final joint-ring pose after release and keeps the offset axis fixed', async () => {
  const f = ringFixture(); f.start(); expect(f.gizmo.isDragging()).toBe(true)
  f.move(); await tick(); f.end(); await tick()
  const result = f.onChange.mock.lastCall[0], pending = f.gizmo.getPendingTransform('placement')
  expect(result).toEqual({ pivot: pending.pivot, rotation: pending.rotation, translation: pending.translation })
  const point = new THREE.Vector3(0, 0, 0), axis = new THREE.Vector3(2, 0, 0)
  const expected = point.clone().sub(axis).applyAxisAngle(new THREE.Vector3(0, 0, 1), 25 * Math.PI / 180).add(axis)
  const actual = point.clone().sub(new THREE.Vector3(...result.pivot)).applyQuaternion(new THREE.Quaternion(...result.rotation))
    .add(new THREE.Vector3(...result.pivot)).add(new THREE.Vector3(...result.translation))
  expect(actual.distanceTo(expected)).toBeLessThan(1e-10)
  expect(f.packet).toEqual(f.source)
})
it('previews both native ring motions about the joint axis before pointer release without accumulating the first delta', async () => {
  const f = ringFixture(), baseline = structuredClone(f.packet.control_state.cluster_transforms[0])
  f.start(); f.move(10); await tick()
  expectJointWorldPose(f.onChange.mock.lastCall[0], baseline, 10)
  f.move(20); await tick()
  expectJointWorldPose(f.onChange.mock.lastCall[0], baseline, 20)
  expect(f.gizmo.isDragging()).toBe(true)
  f.end(); await tick()
  expectJointWorldPose(f.onChange.mock.lastCall[0], baseline, 20)
})
it('keeps the captured native ring baseline when an accepted intermediate projection arrives during the gesture', async () => {
  const f = ringFixture({ pivot: [.5, 1, 0], translation: [1, 2, 0],
    rotation: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), 5 * Math.PI / 180).toArray() })
  const baseline = structuredClone(f.packet.control_state.cluster_transforms[0])
  f.start(); f.move(8); await tick()
  const accepted = structuredClone(f.packet), first = f.onChange.mock.lastCall[0]
  Object.assign(accepted.control_state.cluster_transforms[0], structuredClone(first))
  Object.assign(accepted.control_state.inputs, structuredClone(first))
  f.owner.update(accepted)
  f.move(15); await tick()
  expectJointWorldPose(f.onChange.mock.lastCall[0], baseline, 15)
  f.end(); await tick()
  expectJointWorldPose(f.onChange.mock.lastCall[0], baseline, 15)
  expect(f.packet).toEqual(f.source)
})
it('refuses Apply while a native ring drag is active, then adopts its finalized pose synchronously', async () => {
  const f = ringFixture(); f.start(); f.move(); await tick()
  f.callbacks().onApply(); expect(f.onApply).not.toHaveBeenCalled()
  expect(f.onError.mock.lastCall[0].message).toMatch(/finish|release|drag/i)
  f.end(); f.callbacks().onApply()
  const pending = f.gizmo.getPendingTransform('placement')
  expect(f.onChange.mock.lastCall[0]).toEqual({ pivot: pending.pivot, rotation: pending.rotation, translation: pending.translation })
  expect(f.onApply).toHaveBeenCalledOnce(); await tick()
})
it('keeps a newer numeric pose when a released joint gesture still has queued completion work', async () => {
  const f = ringFixture(); f.start(); f.move(); await tick(); f.end()
  f.callbacks().onTransform([7, 8, 9], [0, 0, 10]); f.callbacks().onApply(); await tick()
  expect(f.onChange.mock.lastCall[0].translation).toEqual([7, 8, 9])
  expect(f.onApply).toHaveBeenCalledOnce()
})
it.each(['reset', 'dispose', 'locked'])('does not adopt a released ring from a retired or locked gesture (%s)', async action => {
  const f = ringFixture(); f.start(); f.move(); await tick(); f.end()
  f.onChange.mockClear()
  if (action === 'reset') f.owner.reset(f.packet)
  else if (action === 'dispose') f.owner.dispose()
  else f.owner.setStatus({ busy: 'cancel' })
  await tick(); expect(f.onChange).not.toHaveBeenCalled()
})
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
