/**
 * Seam plane UI — interactive slice plane for scaffold seam placement.
 *
 * An amber translucent plane perpendicular to the Z axis (helix axis) that
 * the user can drag with the mouse to choose where scaffold crossovers land.
 * Orbit controls remain active when the cursor is not over the plane.
 * Snaps to multiples of SNAP_BP base pairs.
 *
 * Drag mechanics:
 *   - pointerdown on plane (capture phase, runs before OrbitControls): starts drag.
 *   - stopPropagation() prevents OrbitControls from seeing the event.
 *   - pointermove on window: intersects mouse ray with a shadow plane (perpendicular
 *     to camera, coplanar with the seam position) and extracts the Z component.
 *   - pointerup on window: ends drag, restores controls.
 *
 * Public API:
 *   show(initialBp, maxBp, onConfirm, onCancel)
 *   hide()
 *   isActive() → bool
 *   tick()      — call each animation frame to keep the label position current
 *   dispose()
 */

import * as THREE from 'three'
import { BDNA_RISE_PER_BP } from '../constants.js'

const RISE     = BDNA_RISE_PER_BP  // nm per bp
const SNAP_BP  = 7                 // snap interval in bp
const PLANE_HALF = 12              // half-size of the amber plane in nm

export function initSeamPlane(scene, camera, controls, canvas) {
  let _active    = false
  let _dragging  = false
  let _hovering  = false
  let _seamBp    = 0
  let _maxBp     = 84
  let _onConfirm = null
  let _onCancel  = null

  const _raycaster = new THREE.Raycaster()
  const _dragPlane = new THREE.Plane()   // shadow plane used during drag

  // ── Three.js objects ────────────────────────────────────────────────────────

  const planeGeo = new THREE.PlaneGeometry(PLANE_HALF * 2, PLANE_HALF * 2)
  const planeMat = new THREE.MeshBasicMaterial({
    color: 0xffa726,
    transparent: true,
    opacity: 0.12,
    side: THREE.DoubleSide,
    depthWrite: false,
  })
  const planeMesh = new THREE.Mesh(planeGeo, planeMat)
  planeMesh.visible = false
  scene.add(planeMesh)

  // Border
  const borderGeo = new THREE.EdgesGeometry(planeGeo)
  const borderMat = new THREE.LineBasicMaterial({
    color: 0xffa726,
    transparent: true,
    opacity: 0.7,
  })
  const border = new THREE.LineSegments(borderGeo, borderMat)
  planeMesh.add(border)

  // ── HTML overlay elements ───────────────────────────────────────────────────

  const container = document.getElementById('viewport-container')

  const label = document.createElement('div')
  label.style.cssText = [
    'position:absolute',
    'pointer-events:none',
    'background:rgba(20,24,32,0.9)',
    'color:#ffa726',
    'font:11px "Courier New",monospace',
    'padding:3px 8px',
    'border-radius:3px',
    'border:1px solid rgba(255,167,38,0.6)',
    'white-space:nowrap',
    'display:none',
    'transform:translateX(-50%)',
  ].join(';')
  container?.appendChild(label)

  const bar = document.createElement('div')
  bar.style.cssText = [
    'position:absolute',
    'bottom:52px',
    'left:50%',
    'transform:translateX(-50%)',
    'background:rgba(20,24,32,0.88)',
    'color:#c9d1d9',
    'font:11px "Courier New",monospace',
    'padding:6px 16px',
    'border-radius:4px',
    'border:1px solid #30363d',
    'pointer-events:none',
    'display:none',
    'text-align:center',
    'z-index:10',
  ].join(';')
  bar.innerHTML = [
    'Drag seam plane to reposition',
    '&nbsp;&nbsp;&nbsp;&nbsp;',
    '<span style="color:#ffa726">Enter</span>&nbsp;Confirm',
    '&nbsp;&nbsp;',
    '<span style="color:#8b949e">Esc</span>&nbsp;Cancel',
  ].join(' ')
  container?.appendChild(bar)

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function _snap(bp) {
    return Math.round(bp / SNAP_BP) * SNAP_BP
  }

  function _ndcFromEvent(e) {
    const rect = canvas.getBoundingClientRect()
    return new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width)  *  2 - 1,
      ((e.clientY - rect.top)  / rect.height) * -2 + 1,
    )
  }

  function _updateVisuals() {
    const z = _seamBp * RISE
    planeMesh.position.set(0, 0, z)

    label.textContent = `seam  bp ${_seamBp}  (${z.toFixed(2)} nm)`

    // Project the top-centre of the plane to screen space for label placement.
    if (camera && canvas && container) {
      const worldPt = new THREE.Vector3(0, PLANE_HALF * 0.6, z)
      worldPt.project(camera)
      const rect  = canvas.getBoundingClientRect()
      const cRect = container.getBoundingClientRect()
      const sx = ((worldPt.x + 1) / 2) * rect.width  + rect.left - cRect.left
      const sy = ((-worldPt.y + 1) / 2) * rect.height + rect.top  - cRect.top
      label.style.left = sx + 'px'
      label.style.top  = (sy - 6) + 'px'
    }
  }

  // ── Pointer handlers ────────────────────────────────────────────────────────

  function _onPointerDown(e) {
    if (!_active || e.button !== 0) return

    _raycaster.setFromCamera(_ndcFromEvent(e), camera)
    const hits = _raycaster.intersectObject(planeMesh)
    if (hits.length === 0) return

    // Hit — take over this event before OrbitControls sees it.
    e.stopPropagation()
    _dragging = true
    if (controls) controls.enabled = false
    canvas.style.cursor = 'grabbing'

    // Shadow plane: perpendicular to camera view, passes through seam position.
    const camDir = new THREE.Vector3()
    camera.getWorldDirection(camDir)
    _dragPlane.setFromNormalAndCoplanarPoint(camDir, planeMesh.position.clone())

    window.addEventListener('pointermove', _onWindowMove)
    window.addEventListener('pointerup',   _onWindowUp)
  }

  function _onWindowMove(e) {
    _raycaster.setFromCamera(_ndcFromEvent(e), camera)
    const hit = new THREE.Vector3()
    if (_raycaster.ray.intersectPlane(_dragPlane, hit)) {
      const snapped = _snap(Math.round(hit.z / RISE))
      _seamBp = Math.max(0, Math.min(_maxBp, snapped))
      _updateVisuals()
    }
  }

  function _onWindowUp(e) {
    _dragging = false
    if (controls) controls.enabled = true
    canvas.style.cursor = _hovering ? 'grab' : ''
    window.removeEventListener('pointermove', _onWindowMove)
    window.removeEventListener('pointerup',   _onWindowUp)
  }

  // Hover: update cursor when over the plane (but not dragging).
  function _onCanvasMove(e) {
    if (!_active || _dragging) return
    _raycaster.setFromCamera(_ndcFromEvent(e), camera)
    const nowHovering = _raycaster.intersectObject(planeMesh).length > 0
    if (nowHovering !== _hovering) {
      _hovering = nowHovering
      canvas.style.cursor = _hovering ? 'grab' : ''
    }
  }

  function _onCanvasLeave() {
    if (_hovering) { _hovering = false; canvas.style.cursor = '' }
  }

  // ── Keyboard handler (confirm / cancel only) ─────────────────────────────────

  function _onKeyDown(e) {
    if (!_active) return
    if (e.key === 'Enter') { e.preventDefault(); _confirm() }
    else if (e.key === 'Escape') { e.preventDefault(); _cancel() }
  }

  function _confirm() { const bp = _seamBp; hide(); _onConfirm?.(bp) }
  function _cancel()  { hide(); _onCancel?.() }

  // ── Public API ───────────────────────────────────────────────────────────────

  /**
   * Show the seam plane.
   * @param {number}   initialBp  Starting bp position (snapped to SNAP_BP).
   * @param {number}   maxBp      Maximum bp value.
   * @param {Function} onConfirm  Called with (seamBp: int) on Enter.
   * @param {Function} onCancel   Called on Escape.
   */
  function show(initialBp, maxBp, onConfirm, onCancel) {
    _maxBp     = maxBp ?? 84
    _seamBp    = _snap(initialBp ?? Math.round(_maxBp / 2))
    _onConfirm = onConfirm
    _onCancel  = onCancel
    _active    = true

    planeMesh.visible   = true
    label.style.display = 'block'
    bar.style.display   = 'block'

    _updateVisuals()

    // Capture phase: runs before OrbitControls pointerdown handler.
    canvas.addEventListener('pointerdown', _onPointerDown, { capture: true })
    canvas.addEventListener('pointermove', _onCanvasMove)
    canvas.addEventListener('pointerleave', _onCanvasLeave)
    window.addEventListener('keydown', _onKeyDown)
  }

  function hide() {
    if (_dragging) {
      _dragging = false
      if (controls) controls.enabled = true
      window.removeEventListener('pointermove', _onWindowMove)
      window.removeEventListener('pointerup',   _onWindowUp)
    }
    _active   = false
    _hovering = false
    canvas.style.cursor = ''

    planeMesh.visible   = false
    label.style.display = 'none'
    bar.style.display   = 'none'

    canvas.removeEventListener('pointerdown',  _onPointerDown, { capture: true })
    canvas.removeEventListener('pointermove',  _onCanvasMove)
    canvas.removeEventListener('pointerleave', _onCanvasLeave)
    window.removeEventListener('keydown', _onKeyDown)
  }

  function isActive() { return _active }

  /** Call each animation frame to keep the projected label position current. */
  function tick() {
    if (_active) _updateVisuals()
  }

  function dispose() {
    hide()
    scene.remove(planeMesh)
    planeGeo.dispose()
    planeMat.dispose()
    borderGeo.dispose()
    borderMat.dispose()
    label.remove()
    bar.remove()
  }

  return { show, hide, isActive, tick, dispose }
}
