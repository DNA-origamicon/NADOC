/**
 * Sub-domain Gizmo — Phase 4 of the overhang revamp.
 *
 * Provides a 2-DOF rotation gizmo for sub-domains in the MAIN 3D scene only
 * (not in the Domain Designer popup's embedded preview).
 *
 * Visuals:
 *   * Gold torus (#ffd33d)  → θ ring, rotation around the parent axis
 *                              (range -180° … 180°).
 *   * Cyan torus (#39c5cf)  → φ ring, in the plane containing the parent
 *                              axis (range 0° … 180°).
 *
 * Selection model:
 *   The gizmo subscribes to ``store.domainDesigner.selectedSubDomainId`` and
 *   attaches / detaches itself based on that value. It NEVER mutates
 *   ``store.selectedObject`` (Phase 3 popup-only selection rule).
 *
 * Drag model:
 *   * pointerdown raycasts against either torus (radial tolerance r*0.6).
 *   * pointermove computes the delta angle on the ring's plane via atan2;
 *     Shift snaps to 5°.
 *   * Live preview: local quaternion drives the bead range borrowed via
 *     helix_renderer.borrowSubDomainBeads(...).  PATCH commit:false fires
 *     debounced 50 ms during drag so the server stays in sync.
 *   * pointerup: final PATCH commit:true; reset local quaternion to identity
 *     after the backend response (helix_renderer will rebuild the beads
 *     from the new design state).
 *
 * Public API:
 *   initSubDomainGizmo(store, controls, {
 *     sceneRef, cameraRef, canvasRef, onLiveRotate, onCommitRotate,
 *   }) → {
 *     attach(overhangId, sdId),
 *     detach(),
 *     dispose(),
 *     isActive() → bool,
 *   }
 */

import * as THREE from 'three'

import {
  patchSubDomainRotation,
  getSubDomainFrame,
} from '../api/overhang_endpoints.js'

const DEBUG = false
const _debug = (...a) => { if (DEBUG) console.debug('[SDG]', ...a) }

const THETA_COLOR = 0xffd33d
const PHI_COLOR   = 0x39c5cf
const RING_RADIUS = 1.6        // nm — tunable
const TUBE_RADIUS = 0.22       // nm
const RING_SEGS   = 64
const TUBE_SEGS   = 12
const HIT_TOL     = 0.6        // fraction of ring radius
const SNAP_DEG    = 5          // shift-snap

const _Y_HAT = new THREE.Vector3(0, 1, 0)
const _Z_HAT = new THREE.Vector3(0, 0, 1)

function _defaultPhiRef(parentAxis) {
  const pa = parentAxis.clone().normalize()
  const base = Math.abs(pa.dot(_Y_HAT)) > 0.9 ? _Z_HAT.clone() : _Y_HAT.clone()
  const proj = base.clone().addScaledVector(pa, -base.dot(pa))
  if (proj.lengthSq() < 1e-9) return _Z_HAT.clone()
  return proj.normalize()
}

export function initSubDomainGizmo(store, controls, {
  sceneRef, cameraRef, canvasRef, onLiveRotate, onCommitRotate,
} = {}) {
  let _scene  = null
  let _camera = null
  let _canvas = null

  let _attached = false
  let _overhangId = null
  let _sdId       = null

  let _pivot      = new THREE.Vector3()
  let _parentAxis = new THREE.Vector3(0, 0, 1)
  let _phiRef     = new THREE.Vector3(0, 1, 0)

  // Visual root holds both rings; the rings are oriented so that:
  //   thetaRing: normal == parent_axis (i.e. the disc lies in the plane
  //              perpendicular to the parent axis)
  //   phiRing  : normal == cross(parent_axis, phi_ref) (i.e. the disc lies
  //              in the plane CONTAINING parent_axis and phi_ref)
  let _root      = null
  let _thetaMesh = null
  let _phiMesh   = null

  // Drag state.
  let _dragging = null    // 'theta' | 'phi' | null
  let _startAngle = 0
  let _startTheta = 0
  let _startPhi   = 0
  let _liveTheta  = 0
  let _livePhi    = 0
  let _pendingPatch = null

  const _raycaster = new THREE.Raycaster()
  const _pointer   = new THREE.Vector2()

  // ── helpers ────────────────────────────────────────────────────────────

  function _resolveRefs() {
    if (typeof sceneRef  === 'function') _scene  = sceneRef()
    else if (sceneRef)                   _scene  = sceneRef
    if (typeof cameraRef === 'function') _camera = cameraRef()
    else if (cameraRef)                  _camera = cameraRef
    if (typeof canvasRef === 'function') _canvas = canvasRef()
    else if (canvasRef)                  _canvas = canvasRef
  }

  function _buildRings() {
    if (_root) {
      _scene?.remove(_root)
      _root.traverse(o => {
        if (o.geometry) o.geometry.dispose()
        if (o.material) o.material.dispose()
      })
    }
    _root = new THREE.Group()
    _root.name = 'sub_domain_gizmo'
    _root.renderOrder = 999

    // θ ring: torus whose normal == parent_axis
    const thetaGeom = new THREE.TorusGeometry(RING_RADIUS, TUBE_RADIUS, TUBE_SEGS, RING_SEGS)
    const thetaMat  = new THREE.MeshBasicMaterial({
      color: THETA_COLOR, transparent: true, opacity: 0.85,
      depthTest: false, depthWrite: false,
    })
    _thetaMesh = new THREE.Mesh(thetaGeom, thetaMat)
    _thetaMesh.userData.kind = 'theta'
    // Default torus normal is +Z; orient to parent_axis.
    const qTheta = new THREE.Quaternion().setFromUnitVectors(_Z_HAT, _parentAxis.clone().normalize())
    _thetaMesh.quaternion.copy(qTheta)
    _root.add(_thetaMesh)

    // φ ring: lies in the plane containing parent_axis AND phi_ref.  Its
    // normal is parent_axis × phi_ref.
    const phiGeom = new THREE.TorusGeometry(RING_RADIUS, TUBE_RADIUS, TUBE_SEGS, RING_SEGS)
    const phiMat = new THREE.MeshBasicMaterial({
      color: PHI_COLOR, transparent: true, opacity: 0.85,
      depthTest: false, depthWrite: false,
    })
    _phiMesh = new THREE.Mesh(phiGeom, phiMat)
    _phiMesh.userData.kind = 'phi'
    const phiNormal = new THREE.Vector3().crossVectors(_parentAxis, _phiRef).normalize()
    const qPhi = new THREE.Quaternion().setFromUnitVectors(_Z_HAT, phiNormal)
    _phiMesh.quaternion.copy(qPhi)
    _root.add(_phiMesh)

    _root.position.copy(_pivot)
    _scene?.add(_root)
  }

  // ── ray casting ────────────────────────────────────────────────────────

  function _ndcFromEvent(e) {
    if (!_canvas) return _pointer.set(0, 0)
    const rect = _canvas.getBoundingClientRect()
    return _pointer.set(
      ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
  }

  function _hitTest(e) {
    if (!_camera) return null
    _raycaster.setFromCamera(_ndcFromEvent(e), _camera)
    const hits = _raycaster.intersectObjects([_thetaMesh, _phiMesh], false)
    if (!hits.length) return null
    return { kind: hits[0].object.userData.kind, point: hits[0].point.clone() }
  }

  function _planeHitForKind(e, kind) {
    if (!_camera) return null
    _raycaster.setFromCamera(_ndcFromEvent(e), _camera)
    const normal = kind === 'theta'
      ? _parentAxis.clone().normalize()
      : new THREE.Vector3().crossVectors(_parentAxis, _phiRef).normalize()
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, _pivot)
    const hit   = new THREE.Vector3()
    return _raycaster.ray.intersectPlane(plane, hit) ? hit : null
  }

  function _angleInPlane(worldPt, kind) {
    const v = worldPt.clone().sub(_pivot)
    let refX, refY, axis
    if (kind === 'theta') {
      // Plane ⊥ parent_axis. Reference = phi_ref. atan2 around parent_axis.
      axis = _parentAxis.clone().normalize()
      refX = _phiRef.clone()
    } else {
      // Plane contains parent_axis. Reference = parent_axis (so φ=0 ⇔ along
      // parent_axis). atan2 around the plane normal = parent_axis × phi_ref.
      axis = new THREE.Vector3().crossVectors(_parentAxis, _phiRef).normalize()
      refX = _parentAxis.clone().normalize()
    }
    // Project v onto plane.
    v.addScaledVector(axis, -v.dot(axis))
    if (v.lengthSq() < 1e-12) return 0
    v.normalize()
    refY = new THREE.Vector3().crossVectors(axis, refX)
    return Math.atan2(v.dot(refY), v.dot(refX))
  }

  // ── pointer handlers ──────────────────────────────────────────────────

  function _onPointerDown(e) {
    if (!_attached || e.button !== 0) return
    const hit = _hitTest(e)
    if (!hit) return
    e.stopPropagation()
    if (controls) controls.enabled = false
    _dragging = hit.kind
    const planeHit = _planeHitForKind(e, hit.kind)
    if (planeHit) _startAngle = _angleInPlane(planeHit, hit.kind)
    // Read current (theta, phi) from store.
    const { currentDesign } = store.getState()
    const ovhg = currentDesign?.overhangs?.find(o => o.id === _overhangId)
    const sd = ovhg?.sub_domains?.find(s => s.id === _sdId)
    _startTheta = sd?.rotation_theta_deg ?? 0
    _startPhi   = sd?.rotation_phi_deg ?? 0
    _liveTheta  = _startTheta
    _livePhi    = _startPhi
    _canvas?.addEventListener('pointermove', _onPointerMove)
    _canvas?.addEventListener('pointerup',   _onPointerUp)
    try { _canvas?.setPointerCapture?.(e.pointerId) } catch (_) {}
  }

  function _onPointerMove(e) {
    if (!_dragging) return
    const planeHit = _planeHitForKind(e, _dragging)
    if (!planeHit) return
    let angle = _angleInPlane(planeHit, _dragging)
    let deltaDeg = (angle - _startAngle) * 180 / Math.PI
    if (e.shiftKey) deltaDeg = Math.round(deltaDeg / SNAP_DEG) * SNAP_DEG

    if (_dragging === 'theta') {
      let t = _startTheta + deltaDeg
      while (t >  180) t -= 360
      while (t < -180) t += 360
      _liveTheta = t
    } else {
      let p = _startPhi + deltaDeg
      // Clamp φ to [0, 180].
      if (p < 0)   p = 0
      if (p > 180) p = 180
      _livePhi = p
    }

    if (typeof onLiveRotate === 'function') {
      try { onLiveRotate(_overhangId, _sdId, _liveTheta, _livePhi) }
      catch (err) { _debug('onLiveRotate threw', err) }
    }
    _schedulePatch(false)
  }

  function _onPointerUp(e) {
    if (!_dragging) return
    _canvas?.removeEventListener('pointermove', _onPointerMove)
    _canvas?.removeEventListener('pointerup',   _onPointerUp)
    if (controls) controls.enabled = true
    _dragging = null
    if (_pendingPatch) {
      clearTimeout(_pendingPatch)
      _pendingPatch = null
    }
    _commitPatch()
  }

  function _schedulePatch(_isCommit) {
    if (_pendingPatch) clearTimeout(_pendingPatch)
    _pendingPatch = setTimeout(async () => {
      _pendingPatch = null
      try {
        await patchSubDomainRotation(_overhangId, _sdId, {
          theta_deg: _liveTheta, phi_deg: _livePhi, commit: false,
        })
      } catch (err) { _debug('live PATCH failed', err) }
    }, 50)
  }

  async function _commitPatch() {
    try {
      await patchSubDomainRotation(_overhangId, _sdId, {
        theta_deg: _liveTheta, phi_deg: _livePhi, commit: true,
      })
      if (typeof onCommitRotate === 'function') {
        try { onCommitRotate(_overhangId, _sdId, _liveTheta, _livePhi) }
        catch (err) { _debug('onCommitRotate threw', err) }
      }
    } catch (err) { _debug('commit PATCH failed', err) }
  }

  // ── attach / detach ────────────────────────────────────────────────────

  async function attach(overhangId, sdId) {
    if (!overhangId || !sdId) return
    if (_attached && _overhangId === overhangId && _sdId === sdId) return
    detach()
    _resolveRefs()
    if (!_scene) {
      _debug('attach skipped: no scene ref')
      return
    }
    _overhangId = overhangId
    _sdId       = sdId
    try {
      const frame = await getSubDomainFrame(overhangId, sdId)
      _pivot.fromArray(frame.pivot ?? [0, 0, 0])
      _parentAxis.fromArray(frame.parent_axis ?? [0, 0, 1]).normalize()
      _phiRef.fromArray(frame.phi_ref ?? [0, 1, 0]).normalize()
    } catch (err) {
      _debug('frame fetch failed', err)
      // Fall back to a sensible default so the gizmo still renders.
      _pivot.set(0, 0, 0)
      _parentAxis.copy(_Z_HAT)
      _phiRef.copy(_defaultPhiRef(_parentAxis))
    }
    _buildRings()
    _attached = true
    _canvas?.addEventListener('pointerdown', _onPointerDown)
    _debug('attached', overhangId, sdId, 'pivot', _pivot.toArray())
  }

  function detach() {
    if (!_attached) return
    _attached = false
    _overhangId = null
    _sdId = null
    _canvas?.removeEventListener('pointerdown', _onPointerDown)
    _canvas?.removeEventListener('pointermove', _onPointerMove)
    _canvas?.removeEventListener('pointerup',   _onPointerUp)
    if (_pendingPatch) {
      clearTimeout(_pendingPatch)
      _pendingPatch = null
    }
    if (_root) {
      _scene?.remove(_root)
      _root.traverse(o => {
        if (o.geometry) o.geometry.dispose()
        if (o.material) o.material.dispose()
      })
    }
    _root = null
    _thetaMesh = null
    _phiMesh = null
    _debug('detached')
  }

  function dispose() {
    detach()
  }

  function isActive() { return _attached }

  // ── store subscription ─────────────────────────────────────────────────

  let _lastSelected = null
  if (store?.subscribe) {
    store.subscribe(state => {
      const dd = state?.domainDesigner
      const sel = dd?.selectedSubDomainId ?? null
      const ovhgSel = dd?.selectedOverhangId ?? null
      if (sel === _lastSelected) return
      _lastSelected = sel
      if (sel && ovhgSel) {
        attach(ovhgSel, sel).catch(err => _debug('attach failed', err))
      } else {
        detach()
      }
    })
  }

  return { attach, detach, dispose, isActive }
}
