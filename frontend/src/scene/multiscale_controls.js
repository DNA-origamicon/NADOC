/**
 * "Multiscale" orbit mode — the DEFAULT navigation mode (View → Orbit mode).
 *
 * Built on **TrackballControls** with `noZoom = true`: we keep its rotate and
 * pan, and replace the dolly, which is the thing this mode exists to fix.
 *
 * Why Trackball and not Orbit: OrbitControls is a *turntable*. It holds a fixed
 * world up-vector and clamps the polar angle to [minPolarAngle, maxPolarAngle]
 * (OrbitControls.js — `_spherical.phi` is clamped every update), so the camera
 * hits a wall at straight-up and straight-down and can never tumble through the
 * poles. That restriction is unacceptable here — you must be able to rotate a
 * bundle freely to any orientation. TrackballControls has no polar clamp and no
 * up-vector constraint, so rotation is unrestricted. Its own wheel handler
 * early-returns when `noZoom` is set (before preventDefault), so it does not
 * fight the dolly below.
 *
 * The navigation law itself is unchanged — see multiscale_nav.js. In short:
 *
 *   • Wheel dollies along the *cursor ray* (zoom to mouse position), by a step
 *     proportional to the distance to the nearest helix axis — not to the orbit
 *     target. Nothing is measured against the target, so the step never decays
 *     to zero and the camera flies straight through the structure and out the
 *     far side at a constant pace.
 *   • Shift multiplies the local scale (precise ↔ travel).
 *   • The pivot is re-parked in front of the camera at the local scale on every
 *     wheel and every drag-start (ChimeraX `cofr frontCenter` semantics). This
 *     stops rotation from swinging you around a pivot left behind 187 nm away in
 *     the middle of the bundle — and, because TrackballControls scales pan speed
 *     by |camera − target|, it also makes panning correctly scaled at every zoom
 *     level for free.
 */

import * as THREE from 'three'
import { TrackballControls } from 'three/addons/controls/TrackballControls.js'
import { clientToNdc } from './ndc.js'
import {
  MULTISCALE_DEFAULTS,
  nearestAxisDistance,
  navScaleAt,
  zoomStep,
  wheelNotches,
} from './multiscale_nav.js'

const _EMPTY = new Float64Array(0)

/**
 * @param {THREE.PerspectiveCamera} camera
 * @param {HTMLElement}             canvas
 * @param {THREE.Vector3|null}      target       — pivot carried over from the previous mode
 * @param {Function}                getSegments  — () → Float64Array of helix axis segments
 */
export function makeMultiscaleControls(camera, canvas, target, getSegments) {
  const c = new TrackballControls(camera, canvas)
  c.noZoom       = true      // the wheel is ours — see _onWheel
  c.rotateSpeed  = 3.0       // match the old Trackball mode's feel
  c.panSpeed     = 0.8
  c.staticMoving = true      // no rotational inertia
  if (target) c.target.copy(target)

  const params = { ...MULTISCALE_DEFAULTS }

  const _dir = new THREE.Vector3()
  const _fwd = new THREE.Vector3()

  function _segments() {
    try { return getSegments?.() ?? _EMPTY } catch { return _EMPTY }
  }

  /** Local nav scale at the camera's current position. */
  function _scaleAt(boosted) {
    const p = camera.position
    const dist = nearestAxisDistance(p.x, p.y, p.z, _segments())
    // Empty workspace (no helices): fall back to the orbit-target distance so
    // the mode still behaves like a sane zoom instead of freezing at the floor.
    const fallback = p.distanceTo(c.target)
    return navScaleAt(dist, fallback, params, boosted)
  }

  /** Unit vector from the camera through the cursor. */
  function _cursorRay(e, out) {
    const rect = canvas.getBoundingClientRect()
    const { x, y } = clientToNdc(e.clientX, e.clientY, rect)
    return out.set(x, y, 0.5).unproject(camera).sub(camera.position).normalize()
  }

  /**
   * Park the pivot on whatever is in front of the camera, one local scale away.
   * Far out that lands it on the structure; up close it sits just ahead of you.
   */
  function _repivot() {
    const dist = Math.max(_scaleAt(false), params.minPivot)
    camera.getWorldDirection(_fwd)
    c.target.copy(camera.position).addScaledVector(_fwd, dist)
  }

  function _onWheel(e) {
    if (!c.enabled) return
    e.preventDefault()

    const notches = wheelNotches(e.deltaY, e.deltaMode, params.maxNotch)
    if (!notches) return

    const step = zoomStep(_scaleAt(e.shiftKey), notches, params.zoomFrac)
    if (!step) return

    camera.position.addScaledVector(_cursorRay(e, _dir), step)
    _repivot()
  }

  // Capture phase: the pivot must be updated *before* OrbitControls' own
  // pointerdown handler runs, since update() seeds the drag from
  // (camera.position − target).
  function _onPointerDown() {
    if (c.enabled) _repivot()
  }

  canvas.addEventListener('wheel', _onWheel, { passive: false })
  canvas.addEventListener('pointerdown', _onPointerDown, { capture: true })

  const _disposeInner = c.dispose.bind(c)
  c.dispose = () => {
    canvas.removeEventListener('wheel', _onWheel)
    canvas.removeEventListener('pointerdown', _onPointerDown, { capture: true })
    _disposeInner()
  }

  // Live tuning — the constants are meant to be dialled in by feel without a
  // reload. Exposed on window.__NADOC_DBG__.msNav by main.js.
  c.setNavParams = p => { Object.assign(params, p); return { ...params } }
  c.getNavParams = () => ({ ...params })
  c.probeNavScale = () => ({
    pos:         camera.position.toArray().map(v => +v.toFixed(3)),
    target:      c.target.toArray().map(v => +v.toFixed(3)),
    nearestAxis: nearestAxisDistance(
      camera.position.x, camera.position.y, camera.position.z, _segments()),
    scale:        _scaleAt(false),
    scaleBoosted: _scaleAt(true),
    stepPerNotch:        zoomStep(_scaleAt(false), 1, params.zoomFrac),
    stepPerNotchBoosted: zoomStep(_scaleAt(true),  1, params.zoomFrac),
    helices: _segments().length / 6,
  })

  return c
}
