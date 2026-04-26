/**
 * Overhang orientation gizmo.
 *
 * Wraps Three.js TransformControls in rotate-only mode. A dummy Object3D is
 * placed at the right-clicked overhang's pivot. Dragging the rings applies a
 * client-side preview rotation (via onPreview); Apply/Reset/Cancel are handled
 * by the caller (main.js).
 *
 * Usage:
 *   const gizmo = initOverhangGizmo(scene, camera, canvas, controls)
 *   gizmo.attach(rightClickedId, allIds, design)   // show rotation rings
 *   gizmo.detach()                                 // hide and clean up
 *   gizmo.setCallbacks({ onDragStart, onPreview, onDragEnd })
 *   gizmo.getCurrentRDelta()   → THREE.Quaternion accumulated since last attach
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { BDNA_RISE_PER_BP } from '../constants.js'

export function initOverhangGizmo(scene, camera, canvas, controls) {
  let _tc         = null   // TransformControls
  let _dummy      = null   // Object3D TC is attached to (positioned at anchor pivot)
  let _allIds     = []     // all selected overhang IDs
  let _design     = null   // design snapshot at attach time
  let _isDragging = false
  let _startQuat  = new THREE.Quaternion()   // dummy quaternion at drag-start

  let _onDragStart = null   // (helixIds: string[]) => void
  let _onPreview   = null   // (R_delta: THREE.Quaternion) => void
  let _onDragEnd   = null   // () => void

  function setCallbacks({ onDragStart, onPreview, onDragEnd }) {
    _onDragStart = onDragStart ?? null
    _onPreview   = onPreview   ?? null
    _onDragEnd   = onDragEnd   ?? null
  }

  function setCamera(cam) { camera = cam }

  /**
   * Activate the gizmo.
   * @param {string}   rightClickedId  The overhang whose pivot centres the rings.
   * @param {string[]} allIds          All selected overhang IDs (edited together).
   * @param {object}   design          currentDesign from store.
   */
  function attach(rightClickedId, allIds, design, pivotOverride = null) {
    detach()

    const anchor = design?.overhangs?.find(o => o.id === rightClickedId)
    if (!anchor) return

    _allIds = allIds
    _design = design

    // Centre dummy on the crossover junction bead.  Caller passes the actual
    // rendered bead position (pivotOverride) so inline overhangs work correctly —
    // their OverhangSpec.pivot defaults to [0,0,0] and cannot be trusted.
    const pivotVec = pivotOverride
      ?? new THREE.Vector3(anchor.pivot[0], anchor.pivot[1], anchor.pivot[2])
    _dummy = new THREE.Object3D()
    _dummy.position.copy(pivotVec)
    scene.add(_dummy)

    _tc = new TransformControls(camera, canvas)
    _tc.attach(_dummy)
    _tc.setMode('rotate')
    _tc.setSpace('world')
    scene.add(_tc.getHelper())

    // Size rings to ~150% of overhang length in world space.
    // TC scales handles as: scale = factor * size / 4, where
    //   factor = eyeLen * min(1.9 * tan(fov/2) / zoom, 7)
    // Ring torus has base radius 0.5, so ring_world_radius ≈ 0.5 * factor * size / 4.
    // Solving for size: size = targetRadius * 8 / factor
    const strand = design?.strands?.find(s => s.id === anchor.strand_id)
    const ovhgDomain = strand?.domains?.find(d => d.helix_id === anchor.helix_id)
    const domainLengthBp = ovhgDomain
      ? Math.abs(ovhgDomain.end_bp - ovhgDomain.start_bp)
      : (design?.helices?.find(h => h.id === anchor.helix_id)?.length_bp ?? 10)
    const ovhgLengthNm = domainLengthBp * BDNA_RISE_PER_BP
    const targetRadius = ovhgLengthNm * 1.5
    const eyeLen = camera.position.distanceTo(pivotVec)
    const halfFovRad = Math.PI * ((camera.fov ?? 60) / 360)
    const factor = eyeLen * Math.min(1.9 * Math.tan(halfFovRad) / (camera.zoom ?? 1), 7)
    _tc.size = (targetRadius * 8) / Math.max(factor, 0.001)

    _tc.addEventListener('dragging-changed', e => {
      controls.enabled = !e.value
      if (e.value) {
        _isDragging = true
        _startQuat.copy(_dummy.quaternion)
        const helixIds = _allIds
          .map(id => _design?.overhangs?.find(o => o.id === id)?.helix_id)
          .filter(Boolean)
        _onDragStart?.(helixIds)
      } else {
        _isDragging = false
        _onDragEnd?.()
      }
    })

    _tc.addEventListener('change', () => {
      if (!_isDragging) return
      const R_delta = _dummy.quaternion.clone().multiply(_startQuat.clone().invert())
      _onPreview?.(R_delta)
    })
  }

  function detach() {
    if (_tc) {
      _tc.detach()
      const helper = _tc.getHelper()
      helper.parent?.remove(helper)
      _tc.dispose()
      _tc = null
    }
    if (_dummy) {
      _dummy.parent?.remove(_dummy)
      _dummy = null
    }
    _allIds     = []
    _design     = null
    _isDragging = false
  }

  /** Returns the accumulated rotation quaternion since the last attach(). */
  function getCurrentRDelta() {
    if (!_dummy) return new THREE.Quaternion()
    return _dummy.quaternion.clone()
  }

  /**
   * Compose q onto the accumulated delta without dragging.
   * q is applied in world space (premultiply: new = q × existing).
   * Used by the ±45° buttons and manual field input for instant preview.
   */
  function accumulateDelta(q) {
    if (!_dummy) return
    _dummy.quaternion.premultiply(q)
  }

  function dispose() { detach() }

  return {
    attach,
    detach,
    setCallbacks,
    setCamera,
    getCurrentRDelta,
    accumulateDelta,
    dispose,
    get isActive() { return _tc !== null },
  }
}
