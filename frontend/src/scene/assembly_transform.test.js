import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'
import { initAssemblyTransform } from './assembly_transform.js'
import { createMockStore } from '../test-helpers/mock_store.js'

// Each initAssemblyTransform() appends a #assembly-motion-chip to document.body;
// reset between tests so the chip queries below are deterministic.
beforeEach(() => { document.body.innerHTML = '' })

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
// Row-major translation by (x,y,z) — matrixFromInstance transposes from row-major.
const translate = (x, y, z) => [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1]
const inst = (id, values, extra = {}) => ({ id, transform: { values }, ...extra })

function setup({ assembly = null } = {}) {
  const store = createMockStore({ currentAssembly: assembly })
  const assemblyRenderer = { setLiveTransform: vi.fn() }
  const assemblyJointRenderer = { setLiveJointTransform: vi.fn() }
  const api = {
    patchInstanceClusterTransform: vi.fn().mockResolvedValue(undefined),
    propagateFk: vi.fn().mockResolvedValue(undefined),
  }
  const t = initAssemblyTransform({ store, api, assemblyRenderer, assemblyJointRenderer })
  return { store, assemblyRenderer, assemblyJointRenderer, api, t }
}

describe('effectiveInstanceMatrix', () => {
  it('falls back to the committed matrix when no pending transform exists', () => {
    const { t } = setup()
    const m = t.effectiveInstanceMatrix(inst('a', translate(5, 6, 7)))
    const p = new THREE.Vector3().applyMatrix4(m)
    expect([p.x, p.y, p.z]).toEqual([5, 6, 7])
  })
  it('returns a CLONE of the pending transform when one is set', () => {
    const { t } = setup()
    const pending = new THREE.Matrix4().makeTranslation(1, 2, 3)
    t.pendingTransforms.set('a', pending)
    const m = t.effectiveInstanceMatrix(inst('a', IDENTITY))
    const p = new THREE.Vector3().applyMatrix4(m)
    expect([p.x, p.y, p.z]).toEqual([1, 2, 3])
    expect(m).not.toBe(pending) // cloned, not the stored object
  })
})

describe('createAssemblyTransformContext', () => {
  it('returns null when there is no current assembly', () => {
    const { t } = setup({ assembly: null })
    expect(t.createAssemblyTransformContext('a')).toBeNull()
  })
  it('returns null when the instance is anchored (rigidly mated to a fixed part)', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('f', IDENTITY, { fixed: true })],
      joints: [{ joint_type: 'rigid', instance_a_id: 'a', instance_b_id: 'f' }],
    }
    const { t } = setup({ assembly })
    expect(t.createAssemblyTransformContext('a')).toBeNull()
  })
  it('builds a context with primaryStart + every rigid-group member', () => {
    const assembly = {
      instances: [inst('a', translate(1, 0, 0)), inst('b', translate(0, 2, 0))],
      joints: [{ joint_type: 'rigid', instance_a_id: 'a', instance_b_id: 'b' }],
    }
    const { t } = setup({ assembly })
    const ctx = t.createAssemblyTransformContext('a')
    expect(ctx.instanceId).toBe('a')
    expect([...ctx.groupStartTransforms.keys()].sort()).toEqual(['a', 'b'])
    const pa = new THREE.Vector3().applyMatrix4(ctx.primaryStart)
    expect([pa.x, pa.y, pa.z]).toEqual([1, 0, 0])
  })
})

describe('applyAssemblyPrimaryLive', () => {
  it('no-ops on a null ctx or matrix', () => {
    const { t, assemblyRenderer } = setup()
    expect(t.applyAssemblyPrimaryLive(null, new THREE.Matrix4())).toBeUndefined()
    expect(t.applyAssemblyPrimaryLive({}, null)).toBeUndefined()
    expect(assemblyRenderer.setLiveTransform).not.toHaveBeenCalled()
  })
  it('applies the delta to every rigid-group member and runs internal FK propagation', () => {
    // a & b are a rigid group; b also has a revolute child c → internal applyFKLive moves c.
    const assembly = {
      instances: [inst('a', IDENTITY), inst('b', IDENTITY), inst('c', IDENTITY)],
      joints: [
        { joint_type: 'rigid', instance_a_id: 'a', instance_b_id: 'b' },
        { joint_type: 'revolute', instance_a_id: 'b', instance_b_id: 'c' },
      ],
    }
    const { t, assemblyRenderer, assemblyJointRenderer } = setup({ assembly })
    const ctx = t.createAssemblyTransformContext('a')
    // Move primary 'a' by (10,0,0); delta = same since starts are identity.
    const target = new THREE.Matrix4().makeTranslation(10, 0, 0)
    const delta = t.applyAssemblyPrimaryLive(ctx, target)
    const dp = new THREE.Vector3().applyMatrix4(delta)
    expect([dp.x, dp.y, dp.z]).toEqual([10, 0, 0])
    // a + b (rigid group, in the live loop) + c (kinematic child, via internal FK).
    const moved = assemblyRenderer.setLiveTransform.mock.calls.map(call => call[0]).sort()
    expect(moved).toEqual(['a', 'b', 'c'])
    expect(assemblyJointRenderer.setLiveJointTransform).toHaveBeenCalledTimes(3)
  })
})

describe('queueAssemblyPrimaryCommit', () => {
  it('records a CLONE keyed by the ctx instanceId', () => {
    const { t } = setup()
    const mat = new THREE.Matrix4().makeTranslation(4, 5, 6)
    t.queueAssemblyPrimaryCommit({ instanceId: 'a' }, mat)
    expect(t.pendingTransforms.has('a')).toBe(true)
    expect(t.pendingTransforms.get('a')).not.toBe(mat)
    expect(t.hasAssemblyPending()).toBe(true)
  })
  it('no-ops on null ctx/matrix', () => {
    const { t } = setup()
    t.queueAssemblyPrimaryCommit(null, new THREE.Matrix4())
    t.queueAssemblyPrimaryCommit({ instanceId: 'a' }, null)
    expect(t.hasAssemblyPending()).toBe(false)
  })
})

describe('commitAssemblyPending', () => {
  it('drains part-joints then transforms, calling the right api, and clears both maps', async () => {
    const { t, api } = setup()
    t.pendingPartJoints.set('j1', { instanceId: 'a', body: { joint_value: 1 } })
    t.pendingTransforms.set('a', new THREE.Matrix4().makeTranslation(1, 2, 3))
    await t.commitAssemblyPending()
    expect(api.patchInstanceClusterTransform).toHaveBeenCalledWith('a', { joint_value: 1 })
    expect(api.propagateFk).toHaveBeenCalledTimes(1)
    expect(api.propagateFk.mock.calls[0][0]).toBe('a')
    // propagateFk receives the transposed (row-major) array; translation lands in the last row.
    const arr = api.propagateFk.mock.calls[0][1]
    expect([arr[3], arr[7], arr[11]]).toEqual([1, 2, 3])
    expect(t.hasAssemblyPending()).toBe(false)
  })
})

describe('applyFKLive', () => {
  it('no-ops on a null assembly', () => {
    const { t, assemblyRenderer } = setup()
    t.applyFKLive(null, new THREE.Matrix4(), 'a')
    expect(assemblyRenderer.setLiveTransform).not.toHaveBeenCalled()
  })
  it('propagates the delta to a non-rigid (revolute) kinematic child, skipping the seed root', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('b', translate(0, 0, 0))],
      joints: [{ joint_type: 'revolute', instance_a_id: 'a', instance_b_id: 'b' }],
    }
    const { t, assemblyRenderer } = setup({ assembly })
    const delta = new THREE.Matrix4().makeTranslation(3, 0, 0)
    t.applyFKLive(assembly, delta, ['a']) // 'a' is the seed root → not re-moved
    expect(assemblyRenderer.setLiveTransform).toHaveBeenCalledTimes(1)
    const [movedId, mat] = assemblyRenderer.setLiveTransform.mock.calls[0]
    expect(movedId).toBe('b')
    const p = new THREE.Vector3().applyMatrix4(mat)
    expect([p.x, p.y, p.z]).toEqual([3, 0, 0])
  })
  it('skips a fixed child', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('b', IDENTITY, { fixed: true })],
      joints: [{ joint_type: 'revolute', instance_a_id: 'a', instance_b_id: 'b' }],
    }
    const { t, assemblyRenderer } = setup({ assembly })
    t.applyFKLive(assembly, new THREE.Matrix4().makeTranslation(3, 0, 0), ['a'])
    expect(assemblyRenderer.setLiveTransform).not.toHaveBeenCalled()
  })
})

describe('applyClusterMateFKLive', () => {
  it('moves the mate on the OTHER side of a cluster-matched joint', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('b', translate(0, 0, 0))],
      joints: [{
        joint_type: 'revolute', instance_a_id: 'a', instance_b_id: 'b',
        cluster_id_a: 'c1',
      }],
    }
    const { t, assemblyRenderer } = setup({ assembly })
    const delta = new THREE.Matrix4().makeTranslation(0, 5, 0)
    // Dragging instance 'a' by cluster 'c1' should drag mate 'b'.
    t.applyClusterMateFKLive(assembly, 'a', 'c1', delta, new Map())
    const moved = assemblyRenderer.setLiveTransform.mock.calls.map(c => c[0])
    expect(moved).toContain('b')
  })
  it('does nothing when the clusterId matches no joint side', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('b', IDENTITY)],
      joints: [{ joint_type: 'revolute', instance_a_id: 'a', instance_b_id: 'b', cluster_id_a: 'c1' }],
    }
    const { t, assemblyRenderer } = setup({ assembly })
    t.applyClusterMateFKLive(assembly, 'a', 'NOPE', new THREE.Matrix4(), new Map())
    expect(assemblyRenderer.setLiveTransform).not.toHaveBeenCalled()
  })
})

describe('analyzeMotionConstraints', () => {
  it('returns free when there is no assembly or no target', () => {
    expect(setup().t.analyzeMotionConstraints({ id: 'a' })).toEqual({ dof: 'free' })
    const { t } = setup({ assembly: { instances: [inst('a', IDENTITY)], joints: [] } })
    expect(t.analyzeMotionConstraints(null)).toEqual({ dof: 'free' })
  })
  it('returns free when the part has no anchored mates', () => {
    const assembly = { instances: [inst('a', IDENTITY), inst('b', IDENTITY)], joints: [] }
    expect(setup({ assembly }).t.analyzeMotionConstraints({ id: 'a' }).dof).toBe('free')
  })
  it('returns anchored when the moving part is rigidly mated to a fixed part', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('f', IDENTITY, { fixed: true })],
      joints: [{ joint_type: 'rigid', instance_a_id: 'a', instance_b_id: 'f' }],
    }
    expect(setup({ assembly }).t.analyzeMotionConstraints({ id: 'a' }).dof).toBe('anchored')
  })
  it('returns revolute (1 DOF) for a single revolute mate to an anchored part', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('f', IDENTITY, { fixed: true })],
      joints: [{
        id: 'j1', name: 'hinge', joint_type: 'revolute',
        instance_a_id: 'a', instance_b_id: 'f',
        axis_origin: [1, 2, 3], axis_direction: [0, 1, 0],
        min_limit: -90, max_limit: 90, current_value: 10,
      }],
    }
    const r = setup({ assembly }).t.analyzeMotionConstraints({ id: 'a' })
    expect(r.dof).toBe('revolute')
    expect(r.jointId).toBe('j1')
    expect(r.limits).toEqual({ min: -90, max: 90, current: 10 })
    expect([r.origin.x, r.origin.y, r.origin.z]).toEqual([1, 2, 3])
  })
  it('returns over-constrained for two external mates to anchored parts', () => {
    const assembly = {
      instances: [
        inst('a', IDENTITY), inst('f1', IDENTITY, { fixed: true }), inst('f2', IDENTITY, { fixed: true }),
      ],
      joints: [
        { id: 'j1', joint_type: 'revolute', instance_a_id: 'a', instance_b_id: 'f1' },
        { id: 'j2', joint_type: 'revolute', instance_a_id: 'a', instance_b_id: 'f2' },
      ],
    }
    const r = setup({ assembly }).t.analyzeMotionConstraints({ id: 'a' })
    expect(r.dof).toBe('over-constrained')
    expect(r.count).toBe(2)
  })
})

describe('setMotionChip', () => {
  const lastChip = () => [...document.querySelectorAll('#assembly-motion-chip')].pop()
  it('appends the chip element to the document on init', () => {
    setup()
    // (jsdom drops display:none from the cssText round-trip; the show/hide
    // behaviour is asserted via the direct style sets in the next test.)
    expect(lastChip()).toBeTruthy()
    expect(lastChip().id).toBe('assembly-motion-chip')
  })
  it('shows the chip with text + severity colours, hides on empty text', () => {
    const { t } = setup()
    t.setMotionChip('1 DOF — revolute', 'warn')
    const chip = lastChip()
    expect(chip.style.display).toBe('')
    expect(chip.textContent).toBe('1 DOF — revolute')
    expect(chip.style.color).toBeTruthy()
    t.setMotionChip(null)
    expect(lastChip().style.display).toBe('none')
  })
})

describe('hasAssemblyPending', () => {
  it('is true if either map is non-empty, false when both are empty', () => {
    const { t } = setup()
    expect(t.hasAssemblyPending()).toBe(false)
    t.pendingPartJoints.set('j', {})
    expect(t.hasAssemblyPending()).toBe(true)
    t.pendingPartJoints.clear()
    t.pendingTransforms.set('a', new THREE.Matrix4())
    expect(t.hasAssemblyPending()).toBe(true)
  })
})
