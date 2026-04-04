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
 *
 * Constrained rotation (joint axis mode):
 *   When the active cluster has a ClusterJoint defined, the rotation mode
 *   switches from the default three-ring TC to a single orange torus ring
 *   aligned to the joint's axis_direction.  Dragging the ring rotates the
 *   cluster purely around that axis.
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

const _incrQuat  = new THREE.Quaternion()   // scratch for incremental rotation
const _scratchV  = new THREE.Vector3()
const _scratchQ  = new THREE.Quaternion()
const _Y_HAT     = new THREE.Vector3(0, 1, 0)
const _Z_HAT     = new THREE.Vector3(0, 0, 1)

// ── Axis-constrained rotation ring geometry / drag state ─────────────────────
//
// When a joint is present we show a single torus ring (radius = bounding
// sphere of cluster, tube = 0.22 nm) and handle pointer events manually.
// The ring sits at axis_origin, oriented normal to axis_direction.
//
// Drag math:
//   - On pointerdown: intersect ring plane, record start angle.
//   - On pointermove: intersect ring plane, compute signed angle delta,
//     build incremental quaternion = setFromAxisAngle(axisDir, delta).
//   - On pointerup: commit.
//
const RING_COLOUR    = 0xff8800
const RING_TUBE      = 0.22
const RING_SEGMENTS  = 64
const LINE_HALF_LEN  = 8    // nm — half-length of the axis translation drag handle
const JOINT_RING_RADIUS = 1.25  // nm — gizmo ring radius ≈ 50 % larger than sprite disc (SPRITE_SIZE/2 = 0.835 nm)

function _ringRadius(cluster, currentHelixAxes) {
  // Estimate a radius from the bundle extent so the ring wraps the cluster.
  if (!currentHelixAxes || !cluster?.helix_ids?.length) return 5
  let maxDist = 0
  const cx = new THREE.Vector3()
  let n = 0
  for (const hid of cluster.helix_ids) {
    const ax = currentHelixAxes[hid]
    if (!ax) continue
    _scratchV.set(...ax.start).addScaledVector(_scratchV.clone().set(...ax.end), 0.5)
    cx.add(_scratchV); n++
  }
  if (!n) return 5
  cx.divideScalar(n)
  for (const hid of cluster.helix_ids) {
    const ax = currentHelixAxes[hid]
    if (!ax) continue
    const d = _scratchV.set(...ax.start).distanceTo(cx)
    if (d > maxDist) maxDist = d
  }
  return Math.max(3, maxDist * 1.4 + 1.0)
}

export function initClusterGizmo(store, controls, onLiveTransform = null, captureBase = null, onTransformUpdate = null) {
  let _tc             = null   // TransformControls instance (translate mode)
  let _dummy          = null   // Object3D TC is attached to
  let _clusterId      = null
  let _pivot          = null   // [x, y, z] — centroid at activation time
  let _startDummyPos  = null   // THREE.Vector3 — dummy position at drag-start
  let _startQuat      = null   // THREE.Quaternion — dummy quaternion at drag-start
  let _isDragging     = false
  let _mode           = 'translate'   // 'translate' | 'rotate'

  // ── Constraint state ─────────────────────────────────────────────────────────
  let _constraintType  = 'centroid'  // 'centroid' | 'joint'
  let _constraintJoint = null        // ClusterJoint object when type = 'joint'

  // ── Axis-ring state ─────────────────────────────────────────────────────────
  let _ringMesh       = null   // THREE.Mesh — the single-axis torus
  let _ringScene      = null
  let _ringCamera     = null
  let _ringCanvas     = null
  let _axisDir        = null   // THREE.Vector3 — normalised joint axis direction
  let _axisOrigin     = null   // THREE.Vector3 — joint axis origin (world-space nm)
  let _ringDragging   = false
  let _ringStartAngle = 0
  let _ringStartQuat  = null   // cluster quaternion at ring drag start
  let _ringRefVec     = null   // reference vector in ring plane for angle computation
  const _ringRaycaster = new THREE.Raycaster()

  // ── Axis-line translation drag state ─────────────────────────────────────────
  let _lineMesh        = null   // THREE.Group — axis drag handle geometry
  let _lineDragging    = false
  let _lineT0          = 0      // axis-t at drag start (scalar offset along axisDir)
  let _lineClickT0     = 0      // axis-t of mouse ray at drag start
  let _linePerpTrans   = new THREE.Vector3()  // fixed perpendicular translation component

  function _hasJoint() {
    const { currentDesign } = store.getState()
    return !!(currentDesign?.cluster_joints?.find(j => j.cluster_id === _clusterId))
  }

  function _activeJoint() {
    const { currentDesign } = store.getState()
    return currentDesign?.cluster_joints?.find(j => j.cluster_id === _clusterId) ?? null
  }

  // ── Key handler (Tab cycles translate/rotate) ───────────────────────────────
  function _onKey(e) {
    if (_isDragging || _ringDragging) return
    if (e.key === 'Tab') {
      e.preventDefault()
      _setMode(_mode === 'translate' ? 'rotate' : 'translate')
    }
  }

  function _setMode(mode) {
    _mode = mode
    if (!_tc) return
    const useJoint = _constraintType === 'joint' && _constraintJoint

    if (mode === 'translate') {
      _hideRing()
      if (useJoint) {
        _tc.enabled = false
        _tc.getHelper().visible = false
        _showLine()
      } else {
        _hideLine()
        _tc.setMode('translate')
        _tc.enabled = true
        _tc.getHelper().visible = true
      }
    } else {
      // Rotate mode: hide TC handles only when joint constraint is explicitly selected
      _hideLine()
      _tc.setMode('rotate')
      if (useJoint) {
        _tc.enabled = false
        _tc.getHelper().visible = false
        _showRing()
      } else {
        _tc.enabled = true
        _tc.getHelper().visible = true
        _hideRing()
      }
    }
  }

  // ── Axis ring creation / removal ────────────────────────────────────────────
  function _showRing() {
    _hideRing()
    if (!_ringScene || !_clusterId) return
    const joint = (_constraintType === 'joint' && _constraintJoint) ? _constraintJoint : _activeJoint()
    if (!joint) return

    _axisDir    = new THREE.Vector3(...joint.axis_direction).normalize()
    _axisOrigin = new THREE.Vector3(...joint.axis_origin)

    const geo = new THREE.TorusGeometry(JOINT_RING_RADIUS, RING_TUBE, 8, RING_SEGMENTS)
    const mat = new THREE.MeshBasicMaterial({ color: RING_COLOUR, depthTest: false, depthWrite: false, transparent: true })
    _ringMesh = new THREE.Mesh(geo, mat)
    _ringMesh.renderOrder = 9999

    // TorusGeometry lies in XY plane with hole axis = +Z.
    // Rotate so the hole aligns with axisDir (ring then lies ⊥ to axisDir).
    const q = new THREE.Quaternion()
    if (Math.abs(_axisDir.dot(_Z_HAT)) < 0.9999) {
      q.setFromUnitVectors(_Z_HAT, _axisDir)
    } else if (_axisDir.z < 0) {   // axisDir ≈ −Z → 180° flip about Y
      q.setFromAxisAngle(_Y_HAT, Math.PI)
    }
    // else axisDir ≈ +Z → identity, torus is already correct
    _ringMesh.quaternion.copy(q)
    _ringMesh.position.copy(_axisOrigin).addScaledVector(_axisDir, 1)  // 1 nm above surface

    _ringScene.add(_ringMesh)

    _ringCanvas.addEventListener('pointerdown', _onRingPointerDown)
  }

  function _hideRing() {
    if (_ringMesh) {
      _ringMesh.geometry.dispose()
      _ringMesh.material.dispose()
      _ringMesh.parent?.remove(_ringMesh)
      _ringMesh = null
    }
    _ringCanvas?.removeEventListener('pointerdown', _onRingPointerDown)
    _ringCanvas?.removeEventListener('pointermove', _onRingPointerMove)
    _ringCanvas?.removeEventListener('pointerup',   _onRingPointerUp)
    _ringDragging = false
  }

  // ── Axis-line translation handle ─────────────────────────────────────────────
  function _showLine() {
    _hideLine()
    if (!_ringScene || !_constraintJoint) return

    _axisDir    = new THREE.Vector3(..._constraintJoint.axis_direction).normalize()
    _axisOrigin = new THREE.Vector3(..._constraintJoint.axis_origin)

    const q = new THREE.Quaternion()
    if (Math.abs(_axisDir.dot(_Y_HAT)) < 0.9999) {
      q.setFromUnitVectors(_Y_HAT, _axisDir)
    } else if (_axisDir.y < 0) {
      q.setFromAxisAngle(_Z_HAT, Math.PI)
    }

    const group = new THREE.Group()
    const mat   = new THREE.MeshBasicMaterial({ color: RING_COLOUR, depthTest: false })

    const shaft = new THREE.Mesh(
      new THREE.CylinderGeometry(0.15, 0.15, LINE_HALF_LEN * 2, 8),
      mat,
    )
    shaft.quaternion.copy(q)
    group.add(shaft)

    for (const sign of [-1, 1]) {
      const coneQ = q.clone()
      if (sign < 0) coneQ.multiply(new THREE.Quaternion().setFromAxisAngle(_Z_HAT, Math.PI))
      const cone = new THREE.Mesh(new THREE.ConeGeometry(0.4, 0.8, 8), mat)
      cone.quaternion.copy(coneQ)
      cone.position.copy(_axisDir).multiplyScalar(sign * (LINE_HALF_LEN + 0.4))
      group.add(cone)
    }

    group.position.copy(_axisOrigin)
    group.renderOrder = 998
    _lineMesh = group
    _ringScene.add(_lineMesh)

    _ringCanvas.addEventListener('pointerdown', _onLinePointerDown)
  }

  function _hideLine() {
    if (_lineMesh) {
      _lineMesh.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
      _lineMesh.parent?.remove(_lineMesh)
      _lineMesh = null
    }
    _ringCanvas?.removeEventListener('pointerdown', _onLinePointerDown)
    _ringCanvas?.removeEventListener('pointermove', _onLinePointerMove)
    _ringCanvas?.removeEventListener('pointerup',   _onLinePointerUp)
    _lineDragging = false
  }

  /**
   * Closest point on the axis line to the mouse ray.
   * Returns the scalar t along axisDir from axisOrigin, or null if degenerate.
   */
  function _closestTOnAxis(e) {
    _ringRaycaster.setFromCamera(_ndcFromEvent(e), _ringCamera)
    const ro    = _ringRaycaster.ray.origin
    const rd    = _ringRaycaster.ray.direction
    const w     = _axisOrigin.clone().sub(ro)
    const b     = _axisDir.dot(rd)
    const d     = _axisDir.dot(w)
    const eComp = rd.dot(w)
    const denom = 1 - b * b
    if (Math.abs(denom) < 1e-8) return null
    return (b * eComp - d) / denom
  }

  function _onLinePointerDown(e) {
    if (e.button !== 0) return
    _ringRaycaster.setFromCamera(_ndcFromEvent(e), _ringCamera)
    const hits = _ringRaycaster.intersectObjects(_lineMesh.children, false)
    if (!hits.length) return

    e.stopPropagation()
    controls.enabled = false
    _lineDragging    = true

    const t = _closestTOnAxis(e)
    if (t === null) { controls.enabled = true; _lineDragging = false; return }
    _lineClickT0 = t

    const [px, py, pz] = _pivot
    const pivotV = new THREE.Vector3(px, py, pz)
    const trans  = _dummy.position.clone().sub(pivotV)
    _lineT0         = trans.dot(_axisDir)
    _linePerpTrans  = trans.clone().addScaledVector(_axisDir, -_lineT0)

    _startDummyPos = _dummy.position.clone()
    _startQuat     = _dummy.quaternion.clone()

    if (captureBase) {
      const { currentDesign } = store.getState()
      const cl = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
      if (cl) captureBase(cl.helix_ids, cl.domain_ids?.length ? cl.domain_ids : null)
    }

    _ringCanvas.addEventListener('pointermove', _onLinePointerMove)
    _ringCanvas.addEventListener('pointerup',   _onLinePointerUp)
    _ringCanvas.setPointerCapture(e.pointerId)
  }

  function _onLinePointerMove(e) {
    if (!_lineDragging) return
    const t = _closestTOnAxis(e)
    if (t === null) return

    const newT   = _lineT0 + (t - _lineClickT0)
    const [px, py, pz] = _pivot
    const newPos = new THREE.Vector3(px, py, pz)
      .addScaledVector(_axisDir, newT)
      .add(_linePerpTrans)

    if (_dummy) _dummy.position.copy(newPos)

    const { currentDesign } = store.getState()
    const cl = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
    if (cl) {
      _incrQuat.set(0, 0, 0, 1)  // pure translation
      if (onLiveTransform) onLiveTransform(cl.helix_ids, _startDummyPos, _dummy.position, _incrQuat, cl.domain_ids?.length ? cl.domain_ids : null)
      if (onTransformUpdate) {
        const p = _dummy.position
        onTransformUpdate([p.x - px, p.y - py, p.z - pz], _dummy.quaternion)
      }
    }
  }

  function _onLinePointerUp(e) {
    if (!_lineDragging) return
    _lineDragging    = false
    controls.enabled = true
    _ringCanvas.removeEventListener('pointermove', _onLinePointerMove)
    _ringCanvas.removeEventListener('pointerup',   _onLinePointerUp)
    _sendTransform()
  }

  // ── Axis ring pointer drag ──────────────────────────────────────────────────
  function _ndcFromEvent(e) {
    const rect = _ringCanvas.getBoundingClientRect()
    return new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
  }

  /** Project pointer onto the ring's plane; return world-space intersection or null. */
  function _ringPlaneHit(e) {
    _ringRaycaster.setFromCamera(_ndcFromEvent(e), _ringCamera)
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(_axisDir, _axisOrigin)
    const hit   = new THREE.Vector3()
    return _ringRaycaster.ray.intersectPlane(plane, hit) ? hit : null
  }

  /** Signed angle of a vector in the ring plane, relative to _ringRefVec. */
  function _angleInRing(worldPt) {
    const v = worldPt.clone().sub(_axisOrigin)
    // Project onto ring plane
    v.addScaledVector(_axisDir, -v.dot(_axisDir))
    if (v.lengthSq() < 1e-12) return 0
    v.normalize()
    // Signed angle: atan2(cross · axis, dot)
    const cross = new THREE.Vector3().crossVectors(_ringRefVec, v)
    return Math.atan2(cross.dot(_axisDir), _ringRefVec.dot(v))
  }

  /** Shared drag-start logic — called from ring pointerdown and beginConstrainedRotation. */
  function _startRingDrag(e, hit) {
    e.stopPropagation()
    controls.enabled = false
    _ringDragging    = true

    const tmp = Math.abs(_axisDir.dot(_Y_HAT)) < 0.9 ? _Y_HAT.clone() : _Z_HAT.clone()
    _ringRefVec = tmp.clone().addScaledVector(_axisDir, -tmp.dot(_axisDir)).normalize()
    _ringStartAngle = _angleInRing(hit)

    const { currentDesign } = store.getState()
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
    _ringStartQuat = cluster ? new THREE.Quaternion(...cluster.rotation) : new THREE.Quaternion()
    if (captureBase && cluster) captureBase(cluster.helix_ids, cluster.domain_ids?.length ? cluster.domain_ids : null)

    _startDummyPos = _dummy?.position.clone() ?? new THREE.Vector3()
    _startQuat     = _ringStartQuat.clone()

    _ringCanvas.addEventListener('pointermove', _onRingPointerMove)
    _ringCanvas.addEventListener('pointerup',   _onRingPointerUp)
    _ringCanvas.setPointerCapture(e.pointerId)
  }

  function _onRingPointerDown(e) {
    if (e.button !== 0) return
    const hit = _ringPlaneHit(e)
    if (!hit) return
    // Check the hit is roughly on the ring (within 60% of radius from circumference)
    const r    = _ringMesh.geometry.parameters.radius
    const dist = hit.clone().sub(_axisOrigin).length()
    if (Math.abs(dist - r) > r * 0.6) return   // miss — let orbit controls take it
    _startRingDrag(e, hit)
  }

  function _onRingPointerMove(e) {
    if (!_ringDragging) return
    const hit = _ringPlaneHit(e)
    if (!hit) return

    const angle  = _angleInRing(hit)
    const delta  = angle - _ringStartAngle

    // Build incremental quaternion = rotation by delta around axisDir
    _scratchQ.setFromAxisAngle(_axisDir, delta)

    // New absolute quaternion = incremental * start
    const newQ = _scratchQ.clone().multiply(_ringStartQuat)

    if (_dummy) {
      _dummy.quaternion.copy(newQ)
    }

    // Live visual update
    _incrQuat.copy(newQ).multiply(_ringStartQuat.clone().invert())
    const { currentDesign } = store.getState()
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === _clusterId)
    if (cluster) {
      // For joint-constrained rotation the pivot is the axis origin, not the cluster centre.
      const center = _axisOrigin ?? _startDummyPos
      if (onLiveTransform) onLiveTransform(cluster.helix_ids, center, center, _incrQuat, cluster.domain_ids?.length ? cluster.domain_ids : null)
      if (onTransformUpdate) {
        const [px, py, pz] = _pivot
        const p = _dummy?.position ?? { x: px, y: py, z: pz }
        onTransformUpdate([p.x - px, p.y - py, p.z - pz], newQ)
      }
    }
  }

  function _onRingPointerUp(e) {
    if (!_ringDragging) return
    _ringDragging = false
    controls.enabled = true
    _ringCanvas.removeEventListener('pointermove', _onRingPointerMove)
    _ringCanvas.removeEventListener('pointerup',   _onRingPointerUp)

    // For joint-constrained rotation the cluster must rotate about J = axis_origin.
    // Derivation: we want every nucleotide to satisfy
    //   new_pos = R_new @ (p_orig − J) + J
    // Given that the backend stores an absolute transform (pivot, rotation, translation)
    // applied to original positions, we need:
    //   pivot = J, rotation = R_new, translation = T_new
    // where T_new accounts for any pre-existing cluster displacement so that J stays fixed:
    //   T_new = R_delta @ [R0 @ (J − P0) + P0 + T0 − J]
    // with P0 = pivot at attach time, R0 / T0 = rotation/translation at drag start,
    // R_delta = R_new @ R0⁻¹ (rotation applied during this drag only).
    const joint = (_constraintType === 'joint' && _constraintJoint) ? _constraintJoint : _activeJoint()
    if (joint && _dummy) {
      const R_new  = _dummy.quaternion.clone()
      const J      = new THREE.Vector3(...joint.axis_origin)
      const [px, py, pz] = _pivot
      const P0     = new THREE.Vector3(px, py, pz)

      // R0 captured at drag-start; T0 still in design state (pre-commit)
      const R0    = _ringStartQuat ? _ringStartQuat.clone() : new THREE.Quaternion()
      const { currentDesign: cd } = store.getState()
      const cl    = cd?.cluster_transforms?.find(c => c.id === _clusterId)
      const T0    = cl ? new THREE.Vector3(...cl.translation) : new THREE.Vector3()

      const R_delta = R_new.clone().multiply(R0.clone().invert())
      const inner   = J.clone().sub(P0).applyQuaternion(R0).add(P0).add(T0).sub(J)
      const T_new   = inner.applyQuaternion(R_delta)

      // Re-express the transform using P0 (centroid) as pivot instead of J,
      // so cluster.pivot always stays at the centroid.  This keeps the
      // "pivot === 0 → not yet initialised" invariant intact and lets the
      // gizmo reattach at the right location on the next activation.
      //
      // Equivalence:  R @ (p − J) + J + T_new_J  =  R @ (p − P0) + P0 + T_new_c
      // Solving:  T_new_c = R @ (P0 − J) − (P0 − J) + T_new_J
      const P0_minus_J = P0.clone().sub(J)
      const T_new_c    = P0_minus_J.clone().applyQuaternion(R_new).sub(P0_minus_J).add(T_new)

      const { patchCluster } = _getClient()
      patchCluster?.(_clusterId, {
        translation: [T_new_c.x, T_new_c.y, T_new_c.z],
        rotation:    [R_new.x, R_new.y, R_new.z, R_new.w],
        pivot:       [px, py, pz],   // keep P0 — never overwrite with J
        commit:      true,
      })

      // _pivot stays as P0 (unchanged).  Dummy sits at P0 + T_new_c, which
      // is the visual centroid position after the rotation.
      if (_dummy) _dummy.position.set(px + T_new_c.x, py + T_new_c.y, pz + T_new_c.z)
    } else {
      _sendTransform()
    }
  }

  let _getClient = () => ({})
  async function _loadClient() {
    const client = await import('../api/client.js')
    _getClient = () => client
    return client
  }
  _loadClient()

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

    _clusterId  = clusterId
    _pivot      = [...cluster.pivot]
    _ringScene  = scene
    _ringCamera = camera
    _ringCanvas = canvas

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
          if (cl) captureBase(cl.helix_ids, cl.domain_ids?.length ? cl.domain_ids : null)
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
      if (onLiveTransform) onLiveTransform(cluster.helix_ids, _startDummyPos, _dummy.position, _incrQuat, cluster.domain_ids?.length ? cluster.domain_ids : null)
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
      const { patchCluster } = _getClient()
      await patchCluster?.(_clusterId, {
        translation: [p.x - px, p.y - py, p.z - pz],
        rotation:    [q.x, q.y, q.z, q.w],
        commit:      true,   // push to undo stack + append to feature_log
      })
    } catch (err) {
      console.error('[cluster_gizmo] patchCluster failed:', err)
    }
  }

  /**
   * Set axis constraint for the active cluster.
   * @param {'centroid'|'joint'} type
   * @param {object|null}        joint  ClusterJoint object (required when type='joint')
   */
  function setConstraint(type, joint) {
    _constraintType  = type
    _constraintJoint = joint ?? null
    if (_clusterId) {
      // Revolute joints constrain rotation — switch to rotate mode when joint is selected
      if (type === 'joint' && _mode === 'translate') _mode = 'rotate'
      _setMode(_mode)
    }
  }

  /**
   * Start a constrained rotation drag directly from a pointerdown event on a
   * joint indicator ring.  Sets the constraint, shows the gizmo ring, and begins
   * the drag without waiting for a separate click.
   *
   * @param {object}       joint  ClusterJoint object
   * @param {PointerEvent} e      the pointerdown event (needed for setPointerCapture)
   */
  function beginConstrainedRotation(joint, e) {
    if (!_clusterId || !_dummy) return

    _constraintType  = 'joint'
    _constraintJoint = joint
    _mode            = 'rotate'

    _axisDir    = new THREE.Vector3(...joint.axis_direction).normalize()
    _axisOrigin = new THREE.Vector3(...joint.axis_origin)

    // Show the ring gizmo (hides TC and line handle)
    _hideLine()
    if (_tc) { _tc.enabled = false; _tc.getHelper().visible = false }
    _showRing()

    // Get the ring-plane hit and immediately start dragging
    const hit = _ringPlaneHit(e)
    if (!hit) return
    _startRingDrag(e, hit)
  }

  // ── Detach ──────────────────────────────────────────────────────────────────
  function detach() {
    _hideRing()
    _hideLine()
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
    _isDragging      = false
    _ringDragging    = false
    _lineDragging    = false
    _clusterId       = null
    _pivot           = null
    _startDummyPos   = null
    _startQuat       = null
    _ringScene       = null
    _ringCamera      = null
    _ringCanvas      = null
    _mode            = 'translate'
    _constraintType  = 'centroid'
    _constraintJoint = null
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

    const domainIds = cluster.domain_ids
    let filter
    if (domainIds?.length) {
      const domainKeySet = new Set(domainIds.map(d => `${d.strand_id}:${d.domain_index}`))
      filter = nuc => domainKeySet.has(`${nuc.strand_id}:${nuc.domain_index}`)
    } else {
      const helixSet = new Set(cluster.helix_ids)
      filter = nuc => helixSet.has(nuc.helix_id)
    }
    let sx = 0, sy = 0, sz = 0, n = 0
    for (const nuc of currentGeometry) {
      if (!filter(nuc)) continue
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
      if (cl) captureBase(cl.helix_ids, cl.domain_ids?.length ? cl.domain_ids : null)
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
      if (cl) onLiveTransform(cl.helix_ids, prevPos, _dummy.position, _incrQuat, cl.domain_ids?.length ? cl.domain_ids : null)
    }

    // Reset drag-start state so the next drag begins from the new position.
    _startDummyPos = _dummy.position.clone()
    _startQuat     = _dummy.quaternion.clone()

    _sendTransform()
  }

  return { attach, detach, computePivot, setTransform, setConstraint, beginConstrainedRotation, isActive: () => _clusterId !== null, getMode: () => _mode }
}
