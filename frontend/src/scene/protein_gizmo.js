/**
 * Protein transform gizmo.
 *
 * A TransformControls handle on a dummy placed at the selected protein's
 * centroid. Translate (T) / rotate (R) toggling; on drag-end it commits a
 * world-space `gizmo_move` { pivot, translation, rotation } to the backend,
 * which left-multiplies it into the attachment's pose (works for free and
 * overhang-anchored proteins alike — see backend/core/protein.gizmo_move_to_pose).
 * The move is logged in the feature log by the PATCH route.
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

import { patchProteinAttachment } from '../api/client.js'

export function initProteinGizmo(store, controls, { onCommitted, onLiveStart, onLive, onLiveEnd } = {}) {
  let _tc = null
  let _dummy = null
  let _attachmentId = null
  let _pivot = null           // [x,y,z] centroid at attach time
  let _dragging = false
  let _mode = 'translate'
  let _scene = null

  function _onKey(e) {
    if (!_tc) return
    // Ignore while typing in a text field (e.g. the PDB-code input).
    const ae = document.activeElement
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)) return
    if (e.key === 't' || e.key === 'T') _setMode('translate')
    else if (e.key === 'r' || e.key === 'R') _setMode('rotate')
    else if (e.key === 'Escape') detach()
  }

  function _setMode(mode) {
    _mode = mode
    _tc?.setMode(mode)
  }

  function attach(attachmentId, scene, camera, canvas, centroid) {
    detach()
    if (!centroid) return
    _attachmentId = attachmentId
    _pivot = [centroid.x, centroid.y, centroid.z]
    _scene = scene

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
        onLiveStart?.(_attachmentId)
      } else {
        _dragging = false
        onLiveEnd?.(_attachmentId)
        _commit()
      }
    })

    // Live preview: move the protein mesh with the gizmo (world delta about pivot).
    _tc.addEventListener('change', () => {
      if (!_dragging || !onLive) return
      const [px, py, pz] = _pivot
      const m = new THREE.Matrix4()
        .makeTranslation(_dummy.position.x, _dummy.position.y, _dummy.position.z)
        .multiply(new THREE.Matrix4().makeRotationFromQuaternion(_dummy.quaternion))
        .multiply(new THREE.Matrix4().makeTranslation(-px, -py, -pz))
      onLive(m)
    })

    document.addEventListener('keydown', _onKey)
  }

  async function _commit() {
    if (!_attachmentId || !_dummy || !_pivot) return
    const p = _dummy.position
    const [px, py, pz] = _pivot
    const q = _dummy.quaternion
    const move = {
      pivot: [px, py, pz],
      translation: [p.x - px, p.y - py, p.z - pz],
      rotation: [q.x, q.y, q.z, q.w],
    }
    const id = _attachmentId
    await patchProteinAttachment(id, { gizmo_move: move })
    // Pose changed server-side; refresh the render and re-anchor the gizmo at
    // the protein's new centroid for the next incremental move.
    if (onCommitted) await onCommitted(id)
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
  }

  return {
    attach,
    detach,
    setMode: _setMode,
    isAttached: () => _tc != null,
    getAttachmentId: () => _attachmentId,
  }
}
