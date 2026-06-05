import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { initAssemblyTransform } from './assembly_transform.js'
import { createMockStore } from '../test-helpers/mock_store.js'

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
  const applyFKLive = vi.fn()
  const t = initAssemblyTransform({ store, api, assemblyRenderer, assemblyJointRenderer, applyFKLive })
  return { store, assemblyRenderer, assemblyJointRenderer, api, applyFKLive, t }
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
    const { t, assemblyRenderer, applyFKLive } = setup()
    expect(t.applyAssemblyPrimaryLive(null, new THREE.Matrix4())).toBeUndefined()
    expect(t.applyAssemblyPrimaryLive({}, null)).toBeUndefined()
    expect(assemblyRenderer.setLiveTransform).not.toHaveBeenCalled()
    expect(applyFKLive).not.toHaveBeenCalled()
  })
  it('applies the delta to every group member and propagates via FK', () => {
    const assembly = {
      instances: [inst('a', IDENTITY), inst('b', IDENTITY)],
      joints: [{ joint_type: 'rigid', instance_a_id: 'a', instance_b_id: 'b' }],
    }
    const { t, assemblyRenderer, assemblyJointRenderer, applyFKLive } = setup({ assembly })
    const ctx = t.createAssemblyTransformContext('a')
    // Move primary 'a' by (10,0,0); delta = same since starts are identity.
    const target = new THREE.Matrix4().makeTranslation(10, 0, 0)
    const delta = t.applyAssemblyPrimaryLive(ctx, target)
    const dp = new THREE.Vector3().applyMatrix4(delta)
    expect([dp.x, dp.y, dp.z]).toEqual([10, 0, 0])
    expect(assemblyRenderer.setLiveTransform).toHaveBeenCalledTimes(2)   // a + b
    expect(assemblyJointRenderer.setLiveJointTransform).toHaveBeenCalledTimes(2)
    expect(applyFKLive).toHaveBeenCalledTimes(1)
    expect(applyFKLive.mock.calls[0][2].sort()).toEqual(['a', 'b'])      // rootIds seed
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
