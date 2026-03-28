/**
 * Cluster Gizmo — wraps Three.js TransformControls for cluster rigid transforms.
 *
 * Usage:
 *   const gizmo = initClusterGizmo(store, controls)
 *   gizmo.attach(clusterId, scene, camera, canvas)
 *   gizmo.detach()
 *   gizmo.computePivot(clusterId)   → [x, y, z]
 *   gizmo.isActive()                → bool
 *
 * Transform model:
 *   A dummy Object3D is placed at (pivot + stored_translation) with stored
 *   quaternion. Dragging changes its position/quaternion. On each change:
 *     translation = dummy.position − pivot
 *     rotation    = dummy.quaternion [x, y, z, w]
 *   The backend applies: R @ (p − pivot) + pivot + translation.
 *
 * Keyboard: Tab cycles between translate and rotate modes (while gizmo is active).
 * Undo: managed externally by the Translate/Rotate tool (single snapshot per session).
 * Debounce: PATCH calls are debounced 80ms during drag; a final call is made
 *   on drag-end to ensure the last position is persisted.
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

const _incrQuat = new THREE.Quaternion()   // scratch for incremental rotation

export function initClusterGizmo(store, controls, onLiveTransform = null, captureBase = null, onTransformUpdate = null) {
  let _tc             = null   // TransformControls instance
  let _dummy          = null   // Object3D TC is attached to
  let _clusterId      = null
  let _pivot          = null   // [x, y, z] — centroid at activation time
  let _startDummyPos  = null   // THREE.Vector3 — dummy position at drag-start (= visual centroid)
  let _startQuat      = null   // THREE.Quaternion — dummy quaternion at drag-start
  let _isDragging     = false

  // ── Key handler (Tab cycles translate/rotate) ───────────────────────────────
  function _onKey(e) {
    if (!_tc || _isDragging) return
    if (e.key === 'Tab') {
      e.preventDefault()
      _tc.setMode(_tc.mode === 'translate' ? 'rotate' : 'translate')
    }
  }

  // ── Attach ──────────────────────────────────────────────────────────────────
  /**
   * Activate the gizmo for a cluster.
   *
   * @param {string}        clusterId
   * @param {THREE.Scene}   scene
   * @param {THREE.Camera}  camera
   * @param {HTMLElement}   canvas   — renderer.domElement (for TC event binding)
   */
  function attach(clusterId, scene, camera, canvas) {
    detach()   // always clean up first

    const { currentDesign } = store.getState()
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === clusterId)
    if (!cluster) return

    _clusterId = clusterId
    _pivot     = [...cluster.pivot]

    // Dummy starts at pivot displaced by any stored translation, with stored rotation.
    _dummy = new THREE.Object3D()
    const [tx, ty, tz] = cluster.translation
    const [px, py, pz] = cluster.pivot
    _dummy.position.set(px + tx, py + ty, pz + tz)
    _dummy.quaternion.set(...cluster.rotation)   // [x,y,z,w]
    scene.add(_dummy)

    _tc = new TransformControls(camera, canvas)
    _tc.attach(_dummy)
    _tc.setMode('translate')
    _tc.setSpace('world')
    // In Three.js r158+, TransformControls is not an Object3D.
    // The visible gizmo is accessed via getHelper() which returns the _root Object3D.
    scene.add(_tc.getHelper())

    _tc.addEventListener('dragging-changed', e => {
      // Disable orbit/trackball controls while dragging so they don't fight.
      controls.enabled = !e.value

      if (e.value) {
        _isDragging = true
        // Capture base positions and start-state at drag start, not at attach time.
        // This guarantees the snapshot is taken on the current helixCtrl after any
        // geometry rebuild (e.g. from the initial pivot-setting patchCluster) is done.
        _startDummyPos = _dummy.position.clone()
        _startQuat     = _dummy.quaternion.clone()
        if (captureBase) {
          const { currentDesign } = store.getState()
          const cl = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
          if (cl) captureBase(cl.helix_ids)
        }
      } else {
        // Drag ended — persist final transform to backend once.
        _isDragging = false
        _sendTransform()
      }
    })

    _tc.addEventListener('change', () => {
      if (!_isDragging) return
      _incrQuat.copy(_dummy.quaternion).multiply(_startQuat.clone().invert())
      const { currentDesign } = store.getState()
      const cluster = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
      if (!cluster) return
      if (onLiveTransform) onLiveTransform(cluster.helix_ids, _startDummyPos, _dummy.position, _incrQuat)
      if (onTransformUpdate) {
        const [px, py, pz] = _pivot
        const p = _dummy.position
        onTransformUpdate([p.x - px, p.y - py, p.z - pz], _dummy.quaternion)
      }
    })

    document.addEventListener('keydown', _onKey)
    store.setState({ activeClusterId: clusterId })
  }

  // ── Send transform to backend ────────────────────────────────────────────────
  async function _sendTransform() {
    if (!_clusterId || !_dummy || !_pivot) return
    const [px, py, pz] = _pivot
    const p = _dummy.position
    const q = _dummy.quaternion
    try {
      const { patchCluster } = await import('../api/client.js')
      await patchCluster(_clusterId, {
        translation: [p.x - px, p.y - py, p.z - pz],
        rotation:    [q.x, q.y, q.z, q.w],
      })
    } catch (err) {
      console.error('[cluster_gizmo] patchCluster failed:', err)
    }
  }

  // ── Detach ──────────────────────────────────────────────────────────────────
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
    _clusterId     = null
    _pivot         = null
    _startDummyPos = null
    _startQuat     = null
    document.removeEventListener('keydown', _onKey)
    store.setState({ activeClusterId: null })
  }

  // ── Compute pivot from live deformed geometry ────────────────────────────────
  /**
   * Compute the centroid of all backbone positions belonging to the cluster's
   * helix IDs in the current deformed geometry.
   *
   * @param {string} clusterId
   * @returns {[number, number, number]}
   */
  function computePivot(clusterId) {
    const { currentDesign, currentGeometry } = store.getState()
    if (!currentDesign || !currentGeometry?.length) return [0, 0, 0]

    const cluster = currentDesign.cluster_transforms?.find(c => c.id === clusterId)
    if (!cluster?.helix_ids?.length) return [0, 0, 0]

    const helixSet = new Set(cluster.helix_ids)
    let sx = 0, sy = 0, sz = 0, n = 0
    for (const nuc of currentGeometry) {
      if (!helixSet.has(nuc.helix_id)) continue
      const [x, y, z] = nuc.backbone_position
      sx += x; sy += y; sz += z; n++
    }
    return n > 0 ? [sx / n, sy / n, sz / n] : [0, 0, 0]
  }

  /**
   * Programmatically set the cluster transform (e.g. from manual UI input).
   * Captures current positions as base, applies the transform locally for
   * instant preview, then persists to backend.
   *
   * @param {number[]} translation  [tx, ty, tz] in nm, relative to pivot
   * @param {number[]} rotation     [qx, qy, qz, qw] quaternion
   */
  function setTransform(translation, rotation) {
    if (!_dummy || !_pivot) return
    const [px, py, pz] = _pivot

    // Snapshot current rendered positions as base for the incremental transform.
    if (captureBase) {
      const { currentDesign } = store.getState()
      const cl = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
      if (cl) captureBase(cl.helix_ids)
    }

    const prevPos  = _dummy.position.clone()
    const prevQuat = _dummy.quaternion.clone()

    _dummy.position.set(px + translation[0], py + translation[1], pz + translation[2])
    _dummy.quaternion.set(rotation[0], rotation[1], rotation[2], rotation[3])

    // Live preview using incremental transform from old → new position.
    if (onLiveTransform) {
      _incrQuat.copy(_dummy.quaternion).multiply(prevQuat.clone().invert())
      const { currentDesign } = store.getState()
      const cl = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
      if (cl) onLiveTransform(cl.helix_ids, prevPos, _dummy.position, _incrQuat)
    }

    // Reset drag-start state so the next drag begins from the new position.
    _startDummyPos = _dummy.position.clone()
    _startQuat     = _dummy.quaternion.clone()

    _sendTransform()
  }

  return { attach, detach, computePivot, setTransform, isActive: () => _clusterId !== null }
}
