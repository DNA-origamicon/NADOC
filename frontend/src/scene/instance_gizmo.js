/**
 * Instance Gizmo — TransformControls for assembly instance placement.
 *
 * Simpler than cluster_gizmo.js:
 *   - No per-frame live transform (assembly renderer responds to store changes)
 *   - No joint-ring or axis constraint
 *   - No captureBase / computePivot
 *   - Stores full 4×4 matrix directly (row-major, NADOC convention)
 *
 * Matrix convention:
 *   NADOC Mat4x4.values is row-major.
 *   Three.js Matrix4.elements is column-major.
 *   Load:  fromArray(nadoc_values) → transpose() → Three.js matrix
 *   Save:  Three.js matrix → clone().transpose() → toArray() → nadoc row-major
 *
 * Drag model:
 *   A dummy Object3D is placed at the instance's world-space transform.
 *   TransformControls is attached to the dummy.  On drag-end the dummy's
 *   current matrix is sent to the backend via api.patchInstance().
 *   No intermediate sends during drag — the TC helper is the live preview.
 *
 * Keyboard: Tab cycles translate / rotate while gizmo is active.
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

let _api = null
async function _getApi() {
  if (!_api) _api = await import('../api/client.js')
  return _api
}
_getApi()   // pre-warm

export function initInstanceGizmo(store, controls) {
  let _tc         = null   // TransformControls
  let _dummy      = null   // Object3D TC is attached to
  let _instanceId = null
  let _mode       = 'translate'   // 'translate' | 'rotate'
  let _isDragging = false

  // ── Key handler (Tab cycles translate/rotate) ────────────────────────────
  function _onKey(e) {
    if (_isDragging) return
    if (e.key === 'Tab') {
      e.preventDefault()
      _mode = _mode === 'translate' ? 'rotate' : 'translate'
      if (_tc) _tc.setMode(_mode)
    }
  }

  // ── Send matrix to backend on drag-end ───────────────────────────────────
  async function _sendTransform() {
    if (!_instanceId || !_dummy) return
    _dummy.updateMatrix()
    // Three.js matrix is column-major; transpose to NADOC row-major.
    const values = _dummy.matrix.clone().transpose().toArray()
    try {
      const client = await _getApi()
      await client.patchInstance(_instanceId, { transform: { values } })
    } catch (err) {
      console.error('[instance_gizmo] patchInstance failed:', err)
    }
  }

  // ── Attach ───────────────────────────────────────────────────────────────
  /**
   * Activate the gizmo for an instance.
   *
   * @param {string}       instanceId
   * @param {THREE.Scene}  scene
   * @param {THREE.Camera} camera
   * @param {HTMLElement}  canvas   renderer.domElement
   */
  function attach(instanceId, scene, camera, canvas) {
    detach()   // clean up previous if any

    const { currentAssembly } = store.getState()
    const inst = currentAssembly?.instances?.find(i => i.id === instanceId)
    if (!inst) return

    _instanceId = instanceId

    // Build Three.js matrix from NADOC row-major values.
    const raw = inst.transform?.values ?? [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    const m   = new THREE.Matrix4()
    m.fromArray(raw)
    m.transpose()   // reinterpret as row-major

    // Decompose to set dummy position/quaternion (scale is always [1,1,1]).
    const pos  = new THREE.Vector3()
    const quat = new THREE.Quaternion()
    const scl  = new THREE.Vector3(1, 1, 1)
    m.decompose(pos, quat, scl)

    _dummy = new THREE.Object3D()
    _dummy.position.copy(pos)
    _dummy.quaternion.copy(quat)
    scene.add(_dummy)

    _tc = new TransformControls(camera, canvas)
    _tc.attach(_dummy)
    _tc.setMode(_mode)
    _tc.setSpace('world')
    scene.add(_tc.getHelper())

    _tc.addEventListener('dragging-changed', e => {
      controls.enabled = !e.value
      if (e.value) {
        _isDragging = true
      } else {
        _isDragging = false
        _sendTransform()   // persist final transform on drag-end
      }
    })

    document.addEventListener('keydown', _onKey)
  }

  // ── Detach ───────────────────────────────────────────────────────────────
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
    _isDragging = false
    _instanceId = null
    _mode       = 'translate'
    document.removeEventListener('keydown', _onKey)
  }

  return {
    attach,
    detach,
    isActive: () => _instanceId !== null,
    getMode:  () => _mode,
  }
}
