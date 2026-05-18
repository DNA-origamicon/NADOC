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
 *   TransformControls is attached to the dummy.  On drag-end the final
 *   matrix is either handed to the caller or sent to the backend.
 *   No intermediate sends during drag — the caller owns the live preview.
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
  let _scene      = null

  // ── Key handler (Tab cycles translate/rotate) ────────────────────────────
  function _onKey(e) {
    if (_isDragging) return
    if (e.key === 'Tab') {
      e.preventDefault()
      _mode = _mode === 'translate' ? 'rotate' : 'translate'
      if (_tc) _tc.setMode(_mode)
    }
  }

  // Centroid offset (in instance-LOCAL coordinates). When non-null, the gizmo
  // is anchored at the world-space centroid of the instance rather than at the
  // instance's part-local origin. The instance's transform matrix is then
  // recovered from the dummy's matrix by post-multiplying with T(-centroid_local).
  //
  //   instance_world_matrix = dummy_world_matrix · T(-centroid_local)
  //
  // This makes the gizmo land in the middle of the part's visible geometry,
  // which is much easier to find than the part's local origin (which can be
  // anywhere — the polymerize-from-mate seed often puts it well outside the
  // visible structure).
  let _centroidLocal = null   // THREE.Vector3 | null

  /** Compose dummy → instance-world matrix, accounting for centroid offset. */
  function _instanceMatrixFromDummy() {
    if (!_dummy) return null
    _dummy.updateMatrix()
    if (!_centroidLocal) return _dummy.matrix.clone()
    const inv = new THREE.Matrix4().makeTranslation(
      -_centroidLocal.x, -_centroidLocal.y, -_centroidLocal.z,
    )
    return new THREE.Matrix4().multiplyMatrices(_dummy.matrix, inv)
  }

  // ── Send matrix to backend on drag-end ───────────────────────────────────
  async function _sendTransform() {
    if (!_instanceId || !_dummy) return
    const m = _instanceMatrixFromDummy()
    if (!m) return
    // Three.js matrix is column-major; transpose to NADOC row-major.
    const values = m.clone().transpose().toArray()
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
   * @param {string}        instanceId
   * @param {THREE.Scene}   scene
   * @param {THREE.Camera}  camera
   * @param {HTMLElement}   canvas             renderer.domElement
   * @param {Function|null} onLiveTransform    called every drag frame with (THREE.Matrix4 — instance world matrix)
   * @param {Function|null} onCommit           called at drag-end with (THREE.Matrix4 — instance world matrix);
   *                                           when provided, the gizmo does NOT call patchInstance
   *                                           — the caller handles all patching (e.g. groups)
   * @param {THREE.Matrix4|null} initialMatrix override starting instance matrix (otherwise pulled from store)
   * @param {THREE.Vector3|null} centroidWorld optional world-space centroid to anchor the gizmo at.
   *                                           When provided, the gizmo sits at this point rather than at the
   *                                           instance's part-local origin (which may be far from visible geometry).
   */
  function attach(instanceId, scene, camera, canvas, onLiveTransform = null, onCommit = null, initialMatrix = null, centroidWorld = null) {
    detach()   // clean up previous if any

    const { currentAssembly } = store.getState()
    const inst = currentAssembly?.instances?.find(i => i.id === instanceId)
    if (!inst) return

    _instanceId = instanceId

    // Build Three.js matrix from NADOC row-major values.
    const raw = inst.transform?.values ?? [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    const m   = initialMatrix?.clone?.() ?? new THREE.Matrix4()
    if (!initialMatrix) {
      m.fromArray(raw)
      m.transpose()   // reinterpret as row-major
    }

    // Decompose to set dummy quaternion (scale is always [1,1,1]).
    const pos  = new THREE.Vector3()
    const quat = new THREE.Quaternion()
    const scl  = new THREE.Vector3(1, 1, 1)
    m.decompose(pos, quat, scl)

    // Centroid handling: when a world-space centroid is supplied, anchor the
    // dummy there instead of at the instance origin. Stash the centroid in
    // instance-LOCAL coords so we can recover the instance matrix from the
    // dummy on every drag frame:
    //
    //   centroid_local = inverse(instance_matrix) · centroid_world
    //   dummy_world    = instance_world · T(centroid_local)
    //   instance_world = dummy_world · T(-centroid_local)
    if (centroidWorld) {
      const inv = new THREE.Matrix4().copy(m).invert()
      _centroidLocal = centroidWorld.clone().applyMatrix4(inv)
      _dummy = new THREE.Object3D()
      _dummy.position.copy(centroidWorld)
      _dummy.quaternion.copy(quat)
    } else {
      _centroidLocal = null
      _dummy = new THREE.Object3D()
      _dummy.position.copy(pos)
      _dummy.quaternion.copy(quat)
    }
    scene.add(_dummy)
    _scene = scene

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
        if (onCommit) {
          const im = _instanceMatrixFromDummy()
          if (im) onCommit(im)   // caller handles all patching
        } else {
          _sendTransform()   // default: patch only this instance
        }
      }
    })

    // Live per-frame update: push the instance world matrix (centroid-corrected) to the renderer.
    if (onLiveTransform) {
      _tc.addEventListener('change', () => {
        if (!_isDragging) return
        const im = _instanceMatrixFromDummy()
        if (im) onLiveTransform(im)
      })
    }

    document.addEventListener('keydown', _onKey)
  }

  /** Update the gizmo's dummy from a new instance world matrix, preserving the centroid anchor. */
  function setMatrix(matrix4) {
    if (!_dummy || !matrix4) return
    // Compose the dummy world matrix: dummy = instance · T(centroid_local)
    let dummyWorld
    if (_centroidLocal) {
      const t = new THREE.Matrix4().makeTranslation(
        _centroidLocal.x, _centroidLocal.y, _centroidLocal.z,
      )
      dummyWorld = new THREE.Matrix4().multiplyMatrices(matrix4, t)
    } else {
      dummyWorld = matrix4
    }
    const pos  = new THREE.Vector3()
    const quat = new THREE.Quaternion()
    const scl  = new THREE.Vector3(1, 1, 1)
    dummyWorld.decompose(pos, quat, scl)
    _dummy.position.copy(pos)
    _dummy.quaternion.copy(quat)
    _dummy.updateMatrix()
    _tc?.updateMatrixWorld?.()
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
    _isDragging    = false
    _instanceId    = null
    _scene         = null
    _mode          = 'translate'
    _centroidLocal = null
    document.removeEventListener('keydown', _onKey)
  }

  return {
    attach,
    detach,
    setMatrix,
    isActive: () => _instanceId !== null,
    getMode:  () => _mode,
  }
}
