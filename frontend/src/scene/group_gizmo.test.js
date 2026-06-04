import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { revoluteCommitValue, initGroupGizmo } from './group_gizmo.js'
import { createMockStore } from '../test-helpers/mock_store.js'

// The pure commit-value math for a finished revolute gizmo drag, lifted from
// main.js's `_revoluteGizmoCommitValue`. Inputs: the motion constraint, the live
// unwrapped-angle accumulator, and the seed joint snapshot.

const REV = { dof: 'revolute', jointId: 'j1' }

describe('revoluteCommitValue', () => {
  it('returns null for a non-revolute constraint', () => {
    expect(revoluteCommitValue({
      constraint: { dof: 'prismatic', jointId: 'j1' },
      gizmoAngle: { jointId: 'j1', accum: 1, sideSign: 1 },
      seedJoint: { current_value: 0 },
    })).toBeNull()
  })

  it('returns null when there is no accumulated angle', () => {
    expect(revoluteCommitValue({
      constraint: REV, gizmoAngle: null, seedJoint: { current_value: 0 },
    })).toBeNull()
  })

  it('returns null when the accumulator belongs to a different joint', () => {
    expect(revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'other', accum: 1, sideSign: 1 },
      seedJoint: { current_value: 0 },
    })).toBeNull()
  })

  it('adds the accumulated angle to the seed value (forward side → endpoint b)', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 0.5, sideSign: 1 },
      seedJoint: { current_value: 1.0 },
    })
    expect(out).toEqual({ current_value: 1.5, endpoint_side: 'b' })
  })

  it('applies sideSign so a backward joint subtracts + reports endpoint a', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 0.5, sideSign: -1 },
      seedJoint: { current_value: 1.0 },
    })
    expect(out).toEqual({ current_value: 0.5, endpoint_side: 'a' })
  })

  it('treats a missing seed current_value as 0', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 0.25, sideSign: 1 },
      seedJoint: {},
    })
    expect(out.current_value).toBeCloseTo(0.25)
  })

  it('clamps the committed value to the joint limits', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 99, sideSign: 1 },
      seedJoint: { current_value: 0, min_limit: -1, max_limit: 2 },
    })
    expect(out).toEqual({ current_value: 2, endpoint_side: 'b' })
  })
})

// ── initGroupGizmo factory ───────────────────────────────────────────────────
// A fake TransformControls wrapper that records attach()/detach()/applyConstraint
// so the test can invoke the captured onLive/onCommit callbacks directly (driving
// the gizmo's real wiring without a GPU drag).
function makeGizmo() {
  const calls = { attach: [], detach: 0, applyConstraint: [], last: null }
  return {
    _calls: calls,
    attach: (...args) => { calls.attach.push(args); calls.last = args },
    detach: () => { calls.detach++ },
    applyConstraint: (o) => { calls.applyConstraint.push(o) },
    // onLive=args[4], onCommit=args[5], primaryStart=args[6], centroidWorld=args[7]
    _onLive: () => calls.last?.[4],
    _onCommit: () => calls.last?.[5],
    _centroid: () => calls.last?.[7],
  }
}

const I16 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
const ctxFor = (id) => ({
  instanceId: id,
  groupStartTransforms: new Map([[id, new THREE.Matrix4()]]),
  primaryStart: new THREE.Matrix4(),
})

function makeDeps(o = {}) {
  const assembly = o.assembly ?? { joints: [], instances: [], gear_relations: [], belt_paths: [] }
  const store = createMockStore({ currentAssembly: assembly })
  const instanceGizmo = makeGizmo()
  const assemblyRenderer = {
    setLiveTransform: vi.fn(),
    getInstanceCenters: vi.fn(() => o.centers ?? []),
  }
  const assemblyJointRenderer = { setLiveJointTransform: vi.fn() }
  const api = { patchAssemblyJoint: vi.fn() }
  const deps = {
    store, scene: {}, camera: {}, canvas: {},
    instanceGizmo, assemblyRenderer, assemblyJointRenderer, api,
    analyzeMotionConstraints: vi.fn(() => o.constraint ?? { dof: 'free' }),
    setMotionChip: vi.fn(),
    createAssemblyTransformContext: vi.fn((id) => ('ctx' in o ? o.ctx : ctxFor(id))),
    applyAssemblyPrimaryLive: vi.fn(() => o.delta ?? null),
    queueAssemblyPrimaryCommit: vi.fn(),
    getMrAssemblyCtx: vi.fn(() => o.mrCtx ?? null),
    setMrTransformValuesFromMatrix: vi.fn(),
  }
  return deps
}

describe('initGroupGizmo — attachGroupGizmo (single instance)', () => {
  it('clears the motion chip and does NOT attach when there is no transform context', () => {
    const deps = makeDeps({ ctx: null })
    initGroupGizmo(deps).attachGroupGizmo('i1')
    expect(deps.setMotionChip).toHaveBeenCalledWith(null)
    expect(deps.instanceGizmo._calls.attach).toHaveLength(0)
  })

  it('detaches (no attach) for an anchored / over-constrained instance', () => {
    const deps = makeDeps({ constraint: { dof: 'anchored' } })
    initGroupGizmo(deps).attachGroupGizmo('i1')
    expect(deps.instanceGizmo._calls.detach).toBe(1)
    expect(deps.instanceGizmo._calls.attach).toHaveLength(0)
  })

  it('attaches a free instance at the renderer-centroid fallback, no axis constraint', () => {
    const center = new THREE.Vector3(5, 0, 0)
    const deps = makeDeps({ constraint: { dof: 'free' }, centers: [{ id: 'i1', center }] })
    initGroupGizmo(deps).attachGroupGizmo('i1')
    expect(deps.instanceGizmo._calls.attach).toHaveLength(1)
    expect(deps.instanceGizmo._calls.last[0]).toBe('i1')
    expect(deps.instanceGizmo._centroid()).toBe(center)
    expect(deps.instanceGizmo._calls.applyConstraint).toHaveLength(0)
  })

  it('anchors at the joint origin + applies a 1-DOF rotate for a revolute mate', () => {
    const origin = new THREE.Vector3(0, 0, 3)
    const axis = new THREE.Vector3(0, 1, 0)
    const deps = makeDeps({ constraint: { dof: 'revolute', jointId: 'jA', axis, origin } })
    initGroupGizmo(deps).attachGroupGizmo('i1')
    expect(deps.instanceGizmo._centroid()).toBe(origin)
    expect(deps.instanceGizmo._calls.applyConstraint[0]).toMatchObject({ mode: 'rotate', axis, showZ: true })
  })

  it('onLive applies the primary delta and pushes Move/Rotate fields when its ctx matches', () => {
    const deps = makeDeps({
      constraint: { dof: 'free' }, delta: new THREE.Matrix4(),
      mrCtx: { instanceId: 'i1' },
    })
    initGroupGizmo(deps).attachGroupGizmo('i1')
    const mat = new THREE.Matrix4().makeTranslation(1, 2, 3)
    deps.instanceGizmo._onLive()(mat)
    expect(deps.applyAssemblyPrimaryLive).toHaveBeenCalledTimes(1)
    expect(deps.setMrTransformValuesFromMatrix).toHaveBeenCalledWith(mat)
  })

  it('onCommit for a non-revolute DOF queues the primary transform (no joint patch)', () => {
    const deps = makeDeps({ constraint: { dof: 'free' } })
    initGroupGizmo(deps).attachGroupGizmo('i1')
    deps.instanceGizmo._onCommit()(new THREE.Matrix4())
    expect(deps.queueAssemblyPrimaryCommit).toHaveBeenCalledTimes(1)
    expect(deps.api.patchAssemblyJoint).not.toHaveBeenCalled()
  })
})

describe('initGroupGizmo — gear-live revolute drag engine', () => {
  // jA (the dragged joint) is gear-coupled to jB at ratio 2; rotating jA must
  // drive jB's child instance live and leave a committable accumulated angle.
  function gearAssembly() {
    return {
      joints: [
        { id: 'jA', joint_type: 'revolute', current_value: 0, instance_a_id: 'i0', instance_b_id: 'i1', axis_origin: [0, 0, 0], axis_direction: [0, 0, 1] },
        { id: 'jB', joint_type: 'revolute', current_value: 0, instance_a_id: 'i2', instance_b_id: 'i3', axis_origin: [0, 0, 0], axis_direction: [0, 0, 1] },
      ],
      gear_relations: [{ joint_a_id: 'jA', joint_b_id: 'jB', ratio: 2, invert: false }],
      instances: [{ id: 'i0' }, { id: 'i1' }, { id: 'i2' }, { id: 'i3', transform: { values: I16 } }],
      belt_paths: [], belt_riders: [],
    }
  }

  it('drives the coupled joint child live and records a committable angle', () => {
    const assembly = gearAssembly()
    const deps = makeDeps({ assembly })
    const gz = initGroupGizmo(deps)
    const constraint = { dof: 'revolute', jointId: 'jA', axis: new THREE.Vector3(0, 0, 1) }
    const delta = new THREE.Matrix4().makeRotationZ(0.4)

    gz.applyGearLiveForRevoluteDrag(assembly, constraint, new Set(['i1']), delta)

    // jB's child instance got a live transform (the coupling fired).
    expect(deps.assemblyRenderer.setLiveTransform).toHaveBeenCalledWith('i3', expect.anything())
    expect(deps.assemblyJointRenderer.setLiveJointTransform).toHaveBeenCalled()

    // The accumulated rotation commits as jA's new current_value.
    const rev = gz.revoluteGizmoCommitValue(constraint)
    expect(rev).not.toBeNull()
    expect(rev.endpoint_side).toBe('b')
    expect(rev.current_value).toBeCloseTo(0.4, 5)
  })

  it('resetRevoluteAngle discards an in-progress accumulator (next commit is null)', () => {
    const assembly = gearAssembly()
    const deps = makeDeps({ assembly })
    const gz = initGroupGizmo(deps)
    const constraint = { dof: 'revolute', jointId: 'jA', axis: new THREE.Vector3(0, 0, 1) }
    gz.applyGearLiveForRevoluteDrag(assembly, constraint, new Set(['i1']), new THREE.Matrix4().makeRotationZ(0.3))
    gz.resetRevoluteAngle()
    expect(gz.revoluteGizmoCommitValue(constraint)).toBeNull()
  })

  it('is a no-op for a non-revolute constraint', () => {
    const assembly = gearAssembly()
    const deps = makeDeps({ assembly })
    const gz = initGroupGizmo(deps)
    gz.applyGearLiveForRevoluteDrag(assembly, { dof: 'free' }, new Set(['i1']), new THREE.Matrix4())
    expect(deps.assemblyRenderer.setLiveTransform).not.toHaveBeenCalled()
  })
})
