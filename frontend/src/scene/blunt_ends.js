/**
 * Blunt end indicators — rings at free helix endpoints, visible only on hover.
 *
 * A helix endpoint is "free" when no other helix in the design starts or ends
 * at the same 3-D position (within 1 pm tolerance).
 *
 * Each blunt end has:
 *  - an invisible hit disk (CircleGeometry) that absorbs raycasts for hover detection
 *  - a visible ring (RingGeometry) that fades in when the cursor is over the hit disk
 *
 * Clicking a ring (pointerdown+up without drag) opens the slice plane at that
 * exact offset in continuation mode.  The pointerdown is intercepted in the
 * CAPTURE phase so OrbitControls never sees it, preventing unwanted rotation.
 */

import * as THREE from 'three'
import { store }  from '../state/store.js'

const RING_INNER    = 0.35
const RING_OUTER    = 1.15
const HIT_RADIUS    = RING_OUTER * 1.25   // slightly larger than ring for comfortable clicking
const RING_SEGS     = 32
const RING_COLOR    = 0x58a6ff
const RING_OPACITY  = 0.45
const TOL           = 0.001               // nm — two endpoints at the same position

export function initBluntEnds(scene, camera, canvas, { onBluntEndClick, isDisabled } = {}) {

  const _group   = new THREE.Group()
  scene.add(_group)

  const _ringGeo = new THREE.RingGeometry(RING_INNER, RING_OUTER, RING_SEGS)
  const _hitGeo  = new THREE.CircleGeometry(HIT_RADIUS, RING_SEGS)

  // Each entry: { ringMesh, hitMesh, plane, offsetNm }
  let _ends = []
  let _hoveredIdx = -1   // index into _ends, -1 = none

  const _raycaster = new THREE.Raycaster()
  const _ndc       = new THREE.Vector2()

  // pending click: set on pointerdown when hovering a ring
  let _pendingIdx = -1
  let _pendingPos = null

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _dist3(a, b) {
    const dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z
    return Math.sqrt(dx * dx + dy * dy + dz * dz)
  }

  function _isEndFree(helices, h, endpoint) {
    for (const other of helices) {
      if (other === h) continue
      if (_dist3(other.axis_start, endpoint) < TOL) return false
      if (_dist3(other.axis_end,   endpoint) < TOL) return false
    }
    return true
  }

  function _planeFromHelixId(helixId) {
    const m = helixId.match(/^h_(XY|XZ|YZ)_/)
    return m ? m[1] : 'XY'
  }

  function _offsetFromEndpoint(endpoint, plane) {
    if (plane === 'XY') return endpoint.z
    if (plane === 'XZ') return endpoint.y
    return endpoint.x
  }

  function _setNDC(e) {
    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  *  2 - 1,
      -((e.clientY - rect.top) / rect.height) *  2 + 1,
    )
    _raycaster.setFromCamera(_ndc, camera)
  }

  // ── Rebuild ────────────────────────────────────────────────────────────────

  function _rebuild(design) {
    for (const { ringMesh, hitMesh } of _ends) {
      ringMesh.material.dispose()
      hitMesh.material.dispose()
      _group.remove(ringMesh)
      _group.remove(hitMesh)
    }
    _ends       = []
    _hoveredIdx = -1
    _pendingIdx = -1
    _pendingPos = null

    if (!design?.helices?.length) return

    const helices = design.helices

    for (const h of helices) {
      const ax = h.axis_end.x - h.axis_start.x
      const ay = h.axis_end.y - h.axis_start.y
      const az = h.axis_end.z - h.axis_start.z
      const len = Math.sqrt(ax * ax + ay * ay + az * az)
      if (len < 1e-9) continue
      const axisDir = new THREE.Vector3(ax / len, ay / len, az / len)
      const quat = new THREE.Quaternion().setFromUnitVectors(
        new THREE.Vector3(0, 0, 1),
        axisDir,
      )

      const plane = _planeFromHelixId(h.id)

      for (const endpoint of [h.axis_start, h.axis_end]) {
        if (!_isEndFree(helices, h, endpoint)) continue

        const offsetNm = _offsetFromEndpoint(endpoint, plane)

        // Visual ring — starts invisible, shown on hover
        const ringMat = new THREE.MeshBasicMaterial({
          color:       RING_COLOR,
          transparent: true,
          opacity:     0,
          side:        THREE.DoubleSide,
          depthWrite:  false,
        })
        const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
        ringMesh.position.set(endpoint.x, endpoint.y, endpoint.z)
        ringMesh.quaternion.copy(quat)

        // Hit disk — always invisible but raycasted for hover detection
        const hitMat = new THREE.MeshBasicMaterial({
          transparent: true,
          opacity:     0,
          side:        THREE.DoubleSide,
          depthWrite:  false,
        })
        const hitMesh = new THREE.Mesh(_hitGeo, hitMat)
        hitMesh.position.set(endpoint.x, endpoint.y, endpoint.z)
        hitMesh.quaternion.copy(quat)

        _group.add(ringMesh)
        _group.add(hitMesh)
        _ends.push({ ringMesh, hitMesh, plane, offsetNm })
      }
    }
  }

  function _getHitIndex(e) {
    if (!_ends.length) return -1
    _setNDC(e)
    const hitMeshes = _ends.map(r => r.hitMesh)
    const hits      = _raycaster.intersectObjects(hitMeshes)
    if (!hits.length) return -1
    return hitMeshes.indexOf(hits[0].object)
  }

  function _setHovered(idx) {
    if (idx === _hoveredIdx) return
    // Hide previous
    if (_hoveredIdx >= 0) {
      _ends[_hoveredIdx].ringMesh.material.opacity = 0
    }
    _hoveredIdx = idx
    if (_hoveredIdx >= 0) {
      _ends[_hoveredIdx].ringMesh.material.opacity = RING_OPACITY
    }
  }

  // ── Store subscription ────────────────────────────────────────────────────

  store.subscribe((newState, prevState) => {
    if (newState.currentDesign !== prevState.currentDesign) {
      _rebuild(newState.currentDesign)
    }
  })

  // ── Event handlers ────────────────────────────────────────────────────────

  function _onPointerMove(e) {
    if (isDisabled?.()) { _setHovered(-1); return }
    _setHovered(_getHitIndex(e))
  }

  function _onPointerDown(e) {
    if (e.button !== 0 || isDisabled?.()) return
    const idx = _hoveredIdx  // use already-computed hover rather than re-raycasting
    if (idx < 0) return
    // Intercept: prevent OrbitControls from starting a drag
    e.stopImmediatePropagation()
    _pendingIdx = idx
    _pendingPos = { x: e.clientX, y: e.clientY }
  }

  function _onPointerUp(e) {
    if (e.button !== 0) return
    if (_pendingIdx < 0) return
    const idx = _pendingIdx
    _pendingIdx = -1
    const moved = _pendingPos
      ? Math.hypot(e.clientX - _pendingPos.x, e.clientY - _pendingPos.y)
      : 999
    _pendingPos = null
    if (moved > 4) return
    // Confirmed click — intercept and fire callback
    e.stopImmediatePropagation()
    const { plane, offsetNm } = _ends[idx]
    onBluntEndClick?.({ plane, offsetNm })
  }

  // Hover uses normal bubble phase (needs to fire even when nothing intercepts)
  canvas.addEventListener('pointermove',  _onPointerMove)
  // Down/up must be capture phase so we can preventDefault orbit before it registers
  canvas.addEventListener('pointerdown',  _onPointerDown, { capture: true })
  canvas.addEventListener('pointerup',    _onPointerUp,   { capture: true })

  return {
    dispose() {
      canvas.removeEventListener('pointermove',  _onPointerMove)
      canvas.removeEventListener('pointerdown',  _onPointerDown, { capture: true })
      canvas.removeEventListener('pointerup',    _onPointerUp,   { capture: true })
      for (const { ringMesh, hitMesh } of _ends) {
        ringMesh.material.dispose()
        hitMesh.material.dispose()
        _group.remove(ringMesh)
        _group.remove(hitMesh)
      }
      _ends = []
      _ringGeo.dispose()
      _hitGeo.dispose()
      scene.remove(_group)
    },
  }
}
