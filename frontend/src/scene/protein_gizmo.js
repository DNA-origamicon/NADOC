/**
 * Protein transform gizmo.
 *
 * A TransformControls handle on a dummy placed at the selected protein's
 * centroid. Translate (T) / rotate (R) toggling; movement remains a local
 * preview until Apply commits a world-space `gizmo_move` to the backend,
 * which left-multiplies it into the attachment's pose (works for free and
 * overhang-anchored proteins alike — see backend/core/protein.gizmo_move_to_pose).
 * The move is logged in the feature log by the PATCH route.
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

import { patchProteinAttachment } from '../api/client.js'
import { showToast } from '../ui/toast.js'

export function clampPointToSphere(point, root, radius) {
  if (!root || !Number.isFinite(radius)) return point.clone()
  const delta = point.clone().sub(root)
  if (radius <= 1e-12) return root.clone()
  if (delta.lengthSq() <= 1e-24) return root.clone().add(new THREE.Vector3(radius, 0, 0))
  return root.clone().add(delta.normalize().multiplyScalar(radius))
}

export function constrainCentroidTransform({ centroid, position, rotation, joint, root, radius }) {
  const translation = position.clone().sub(centroid)
  const proposedJoint = joint.clone()
    .sub(centroid)
    .applyQuaternion(rotation)
    .add(centroid)
    .add(translation)
  const constrainedJoint = clampPointToSphere(proposedJoint, root, radius)
  return {
    position: position.clone().add(constrainedJoint.clone().sub(proposedJoint)),
    joint: constrainedJoint,
  }
}

/** Exact world delta used by both live rendering and the persisted gizmo_move. */
export function proteinPreviewMatrix(pivot, position, rotation) {
  return new THREE.Matrix4()
    .makeTranslation(position.x, position.y, position.z)
    .multiply(new THREE.Matrix4().makeRotationFromQuaternion(rotation))
    .multiply(new THREE.Matrix4().makeTranslation(-pivot.x, -pivot.y, -pivot.z))
}

export function initProteinGizmo(store, controls, {
  onCommitted, onCancelled, onLiveStart, onLive, onLiveEnd, onTransform,
} = {}) {
  let _tc = null
  let _dummy = null
  let _attachmentId = null
  let _pivot = null           // [x,y,z] centroid at attach time
  let _dragging = false
  let _mode = 'translate'
  let _scene = null
  let _constraint = null
  let _dirty = false
  let _sessionStarted = false

  function _ensureSession() {
    if (_sessionStarted) return
    _sessionStarted = true
    onLiveStart?.(_attachmentId)
  }

  function _onKey(e) {
    if (!_tc) return
    // Ignore while typing in a text field (e.g. the PDB-code input).
    const ae = document.activeElement
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)) return
    if (e.key === 't' || e.key === 'T') _setMode('translate')
    else if (e.key === 'r' || e.key === 'R') _setMode('rotate')
    else if (e.key === 'Tab') {
      e.preventDefault()
      _setMode(_mode === 'translate' ? 'rotate' : 'translate')
    }
    else if (e.key === 'Escape') cancel()
  }

  function _setMode(mode) {
    _mode = mode
    _tc?.setMode(mode)
  }

  function _previewCurrentTransform() {
    if (!_dummy || !_pivot) return
    let constrainedJoint = null
    if (_constraint?.mode === 'two_ball_joint') {
      const solved = constrainCentroidTransform({
        centroid: new THREE.Vector3(..._pivot),
        position: _dummy.position,
        rotation: _dummy.quaternion,
        joint: new THREE.Vector3(..._constraint.joint),
        root: new THREE.Vector3(..._constraint.root),
        radius: _constraint.radius_nm,
      })
      constrainedJoint = solved.joint
      _dummy.position.copy(solved.position)
    }
    const [px, py, pz] = _pivot
    const m = proteinPreviewMatrix(
      new THREE.Vector3(px, py, pz), _dummy.position, _dummy.quaternion,
    )
    onLive?.(m, {
      constraint: _constraint,
      pivot: new THREE.Vector3(px, py, pz),
      position: _dummy.position.clone(),
      constrainedJoint,
      rotation: _dummy.quaternion.clone(),
    })
    onTransform?.(
      [_dummy.position.x - px, _dummy.position.y - py, _dummy.position.z - pz],
      _dummy.quaternion.toArray(),
    )
    _dirty = true
  }

  function attach(attachmentId, scene, camera, canvas, centroid, constraint = null) {
    detach()
    if (!centroid) return
    _attachmentId = attachmentId
    _pivot = [centroid.x, centroid.y, centroid.z]
    _scene = scene
    _constraint = constraint
    _dirty = false
    _sessionStarted = false

    _dummy = new THREE.Object3D()
    _dummy.position.set(centroid.x, centroid.y, centroid.z)
    scene.add(_dummy)

    _tc = new TransformControls(camera, canvas)
    _tc.attach(_dummy)
    _tc.setMode(_mode)
    _tc.setSpace('world')
    scene.add(_tc.getHelper())

    _tc.addEventListener('dragging-changed', (e) => {
      controls.enabled = !e.value
      if (e.value) {
        _dragging = true
        _ensureSession()
      } else {
        _dragging = false
      }
    })

    // Live preview: move the protein mesh with the gizmo (world delta about pivot).
    _tc.addEventListener('change', () => {
      if (_dragging) _previewCurrentTransform()
    })

    document.addEventListener('keydown', _onKey)
  }

  async function _commit() {
    if (!_attachmentId || !_dummy || !_pivot) return false
    if (!_dirty) {
      if (_sessionStarted) onLiveEnd?.(_attachmentId)
      _sessionStarted = false
      return false
    }
    const p = _dummy.position
    const [px, py, pz] = _pivot
    const q = _dummy.quaternion
    const move = {
      pivot: [px, py, pz],
      translation: [p.x - px, p.y - py, p.z - pz],
      rotation: [q.x, q.y, q.z, q.w],
    }
    const id = _attachmentId
    _dirty = false
    if (_sessionStarted) onLiveEnd?.(_attachmentId)
    _sessionStarted = false
    try {
      await patchProteinAttachment(id, { gizmo_move: move })
    } catch (error) {
      _dirty = true
      throw error
    }
    // The PATCH has succeeded and its feature-log entry now exists. Notify
    // immediately rather than waiting for the authoritative geometry refresh.
    showToast('Protein move applied — Feature Log entry created.', { severity: 'success' })
    // Pose changed server-side; refresh the render and re-anchor the gizmo at
    // the protein's new centroid for the next incremental move.
    if (onCommitted) await onCommitted(id)
    return true
  }

  function setTransform(translation, rotation) {
    if (!_dummy || !_pivot) return false
    _ensureSession()
    _dummy.position.set(
      _pivot[0] + translation[0], _pivot[1] + translation[1], _pivot[2] + translation[2],
    )
    _dummy.quaternion.set(...rotation).normalize()
    _previewCurrentTransform()
    return true
  }

  function reset() {
    if (!_dummy || !_pivot) return false
    _ensureSession()
    _dummy.position.set(..._pivot)
    _dummy.quaternion.identity()
    _previewCurrentTransform()
    // Identity is the session baseline, so Apply after Reset is a no-op.
    _dirty = false
    return true
  }

  async function cancel() {
    if (!_attachmentId) return false
    const id = _attachmentId
    if (_sessionStarted) {
      reset()
      onLiveEnd?.(id)
    }
    _sessionStarted = false
    _dirty = false
    detach()
    await onCancelled?.(id)
    return true
  }

  function detach() {
    if (_tc) {
      _tc.detach()
      _scene?.remove(_tc.getHelper())
      _tc.dispose?.()
      _tc = null
    }
    if (_dummy) {
      _dummy.parent?.remove(_dummy)
      _dummy = null
    }
    document.removeEventListener('keydown', _onKey)
    _attachmentId = null
    _pivot = null
    _dragging = false
    _constraint = null
    _dirty = false
    _sessionStarted = false
  }

  return {
    attach,
    detach,
    setMode: _setMode,
    setTransform,
    commit: _commit,
    reset,
    cancel,
    isDirty: () => _dirty,
    setRotationSnap: (degrees) => _tc?.setRotationSnap(degrees == null ? null : THREE.MathUtils.degToRad(degrees)),
    isAttached: () => _tc != null,
    getAttachmentId: () => _attachmentId,
    getMode: () => _mode,
  }
}
