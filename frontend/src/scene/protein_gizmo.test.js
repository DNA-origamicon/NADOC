import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'

const { patchProteinAttachment, showToast } = vi.hoisted(() => ({
  patchProteinAttachment: vi.fn(() => Promise.resolve({})),
  showToast: vi.fn(),
}))
vi.mock('../api/client.js', () => ({ patchProteinAttachment }))
vi.mock('../ui/toast.js', () => ({ showToast }))
vi.mock('three/addons/controls/TransformControls.js', async () => {
  const ThreeActual = await vi.importActual('three')
  return { TransformControls: class {
    constructor() { this.listeners = {}; this.helper = new ThreeActual.Object3D() }
    attach(object) { this.object = object }
    detach() {}
    setMode() {}
    setSpace() {}
    setRotationSnap() {}
    getHelper() { return this.helper }
    addEventListener(name, fn) { this.listeners[name] = fn }
    dispose() {}
  } }
})

import { clampPointToSphere, constrainCentroidTransform, initProteinGizmo, proteinPreviewMatrix } from './protein_gizmo.js'

beforeEach(() => {
  patchProteinAttachment.mockClear()
  showToast.mockClear()
})

describe('two-ball-joint protein constraint', () => {
  it('projects under- and over-length drags to the fixed oligo radius', () => {
    const root = new THREE.Vector3(1, 2, 3)
    for (const requested of [
      new THREE.Vector3(1.1, 2, 3),
      new THREE.Vector3(101, 2, 3),
    ]) {
      const clamped = clampPointToSphere(requested, root, 5)
      expect(clamped.distanceTo(root)).toBeCloseTo(5, 12)
      expect(clamped.x).toBeCloseTo(6, 12)
    }
  })

  it('handles a zero-length unequal-strand endpoint at the root', () => {
    const root = new THREE.Vector3(-2, 4, 1)
    const clamped = clampPointToSphere(new THREE.Vector3(99, 99, 99), root, 0)
    expect(clamped.toArray()).toEqual(root.toArray())
  })

  it('keeps the gizmo at the centroid while constraining an off-centre joint', () => {
    const centroid = new THREE.Vector3(10, 0, 0)
    const joint = new THREE.Vector3(8, 0, 0)
    const root = new THREE.Vector3(0, 0, 0)
    const rotation = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 0, 1), Math.PI / 2,
    )
    const solved = constrainCentroidTransform({
      centroid,
      position: centroid.clone().add(new THREE.Vector3(100, 0, 0)),
      rotation,
      joint,
      root,
      radius: 8,
    })
    // Endpoint is clamped, while centroid→joint retains the rotated rigid offset.
    const transformedJoint = joint.clone().sub(centroid).applyQuaternion(rotation)
      .add(solved.position)
    expect(transformedJoint.distanceTo(root)).toBeCloseTo(8, 10)
    expect(transformedJoint.distanceTo(solved.joint)).toBeCloseTo(0, 10)
    expect(solved.position.distanceTo(solved.joint)).toBeCloseTo(
      centroid.distanceTo(joint), 10,
    )
  })

  it('allows a full centroid rotation while correcting only the centroid translation', () => {
    const centroid = new THREE.Vector3(4, 1, -2)
    const joint = centroid.clone().add(new THREE.Vector3(1, 0, 0))
    const root = new THREE.Vector3(0, 0, 0)
    const rotation = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 1, 0), Math.PI,
    )
    const solved = constrainCentroidTransform({
      centroid, position: centroid, rotation, joint, root, radius: 3,
    })
    const rigidOffset = joint.clone().sub(centroid).applyQuaternion(rotation)
    expect(solved.joint.clone().sub(solved.position).distanceTo(rigidOffset)).toBeCloseTo(0, 10)
    expect(solved.joint.distanceTo(root)).toBeCloseTo(3, 10)
  })
})

describe('protein move preview lifecycle', () => {
  it('uses the same T(translation)·T(pivot)·R·T(-pivot) convention as Apply', () => {
    const pivot = new THREE.Vector3(2, -1, 3)
    const translation = new THREE.Vector3(4, 5, -2)
    const position = pivot.clone().add(translation)
    const rotation = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 0, 1), Math.PI / 2,
    )
    const point = new THREE.Vector3(3, -1, 3)
    const preview = point.clone().applyMatrix4(proteinPreviewMatrix(pivot, position, rotation))
    const expected = point.clone().sub(pivot).applyQuaternion(rotation).add(pivot).add(translation)
    expect(preview.distanceTo(expected)).toBeLessThan(1e-12)
  })

  function setup() {
    const callbacks = {
      onLiveStart: vi.fn(), onLive: vi.fn(), onLiveEnd: vi.fn(),
      onCommitted: vi.fn(), onCancelled: vi.fn(), onTransform: vi.fn(),
    }
    const gizmo = initProteinGizmo({}, { enabled: true }, callbacks)
    gizmo.attach('p1', new THREE.Scene(), {}, {}, new THREE.Vector3(1, 2, 3))
    return { gizmo, callbacks }
  }

  it('keeps movement local until Apply, then commits exactly once', async () => {
    const { gizmo, callbacks } = setup()
    gizmo.setTransform([4, 5, 6], [0, 0, 0, 1])
    expect(callbacks.onLiveStart).toHaveBeenCalledTimes(1)
    expect(callbacks.onLive).toHaveBeenCalled()
    expect(patchProteinAttachment).not.toHaveBeenCalled()

    await gizmo.commit()
    expect(patchProteinAttachment).toHaveBeenCalledTimes(1)
    expect(patchProteinAttachment).toHaveBeenCalledWith('p1', {
      gizmo_move: {
        pivot: [1, 2, 3], translation: [4, 5, 6], rotation: [0, 0, 0, 1],
      },
    })
    expect(callbacks.onLiveEnd).toHaveBeenCalledTimes(1)
    expect(callbacks.onCommitted).toHaveBeenCalledWith('p1')
    expect(showToast).toHaveBeenCalledWith(
      'Protein move applied — Feature Log entry created.',
      { severity: 'success' },
    )
  })

  it('Reset restores the identity preview and makes Apply a no-op', async () => {
    const { gizmo, callbacks } = setup()
    gizmo.setTransform([3, 0, 0], [0, 0, 0, 1])
    gizmo.reset()
    expect(gizmo.isDirty()).toBe(false)
    const lastMatrix = callbacks.onLive.mock.calls.at(-1)[0]
    expect(new THREE.Vector3(1, 2, 3).applyMatrix4(lastMatrix).toArray()).toEqual([1, 2, 3])
    await gizmo.commit()
    expect(patchProteinAttachment).not.toHaveBeenCalled()
    expect(showToast).not.toHaveBeenCalled()
    expect(callbacks.onLiveEnd).toHaveBeenCalledTimes(1)
  })

  it('Cancel restores the identity preview and reloads authoritative geometry', async () => {
    const { gizmo, callbacks } = setup()
    gizmo.setTransform([2, -1, 0], [0, 0, 0, 1])
    await gizmo.cancel()
    expect(patchProteinAttachment).not.toHaveBeenCalled()
    expect(callbacks.onLiveEnd).toHaveBeenCalledTimes(1)
    expect(callbacks.onCancelled).toHaveBeenCalledWith('p1')
    expect(gizmo.isDirty()).toBe(false)
  })

  it('Tab cycles translate and rotate while attached', () => {
    const { gizmo } = setup()
    expect(gizmo.getMode()).toBe('translate')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }))
    expect(gizmo.getMode()).toBe('rotate')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }))
    expect(gizmo.getMode()).toBe('translate')
  })
})
