/**
 * Smooth WASD camera pan layered on top of OrbitControls.
 *
 * Previously this module implemented a hybrid "orbit + auto-fly" navigation
 * that switched to a fly camera when zoomed out past a distance threshold.
 * That mode swap was distracting at scale (the user could trip the threshold
 * just by zooming out to fit a polymer chain) — removed entirely.
 *
 * Current behaviour:
 *   • OrbitControls is always active.  Wheel zoom + drag-orbit + middle-pan
 *     work unchanged.
 *   • WASD pans the camera (and OrbitControls.target in lockstep, so orbit
 *     keeps a sane pivot) with an exponential ease-in / ease-out velocity:
 *       W = world  up   (+Y)
 *       S = world  down (-Y)
 *       A = camera left
 *       D = camera right
 *   • Shift = 5× boost.  Speed scales with camera-to-target distance so the
 *     keys feel proportionate at any zoom.
 *   • Keys are inert when typing into inputs / textareas / contenteditable
 *     so menu searches and field editing still work.
 */

import * as THREE from 'three'
import { fovPanScale } from './fov_pan.js'

// Velocity envelope: target speed = SPEED_FRAC * camera_to_target_distance.
// At minDist=10 that's ~6/sec; at maxDist=10000 that's ~6000/sec — keeps the
// key feel constant across scale.  Accel limited so taps don't lurch.
const SPEED_FRAC      = 0.6
const MIN_SPEED       = 2.0       // floor for very-close-up zoom
const ACCEL_TAU       = 0.12      // seconds — velocity reaches ~63 % of target
const DECEL_TAU       = 0.18      // longer release for smoother stop
const BOOST_MULT      = 5

export function initNavController({
  scene, camera, controls, canvas,
  store, assemblyRenderer, designRenderer,
  addFrameCallback,
}) {
  // ── Per-frame velocity envelope.  Each key contributes ±1 to a target
  // direction; the live velocity exponentially eases toward the scaled
  // target.  No mode swap, no HUD, no threshold tests.
  const _keys = new Set()
  let _lastTime = performance.now()
  const _vel = new THREE.Vector3()
  const _tmpFwd = new THREE.Vector3()
  const _tmpRight = new THREE.Vector3()
  const _tmpMove = new THREE.Vector3()
  const _tmpTargetVel = new THREE.Vector3()
  const _worldUp = new THREE.Vector3(0, 1, 0)

  function _onFrame() {
    const now = performance.now()
    const dt = Math.min((now - _lastTime) / 1000, 0.1)
    _lastTime = now

    // Build target direction from currently-held keys.
    let dx = 0, dy = 0
    if (_keys.has('w')) dy += 1   // up
    if (_keys.has('s')) dy -= 1   // down
    if (_keys.has('d')) dx += 1   // right
    if (_keys.has('a')) dx -= 1   // left
    const anyKey = (dx !== 0 || dy !== 0)

    // Compute world-space target velocity.
    _tmpTargetVel.set(0, 0, 0)
    if (anyKey) {
      camera.getWorldDirection(_tmpFwd)
      _tmpRight.crossVectors(_tmpFwd, _worldUp)
      // crossVectors may produce a zero-length vector when the camera looks
      // straight up/down; fall back to world X in that degenerate case.
      if (_tmpRight.lengthSq() < 1e-8) _tmpRight.set(1, 0, 0)
      else _tmpRight.normalize()
      const distToTarget = camera.position.distanceTo(controls.target)
      // Distance alone is the wrong yardstick once the lens moves: photo mode
      // dollies the camera when the FOV changes, so a long lens sits far out
      // and WASD would rocket, a wide one crawls. Scale by the frustum height
      // at the pivot instead — exactly 1× at the default 55° lens.
      const speed = Math.max(distToTarget * SPEED_FRAC * fovPanScale(camera.fov), MIN_SPEED) *
                    (_keys.has('shift') ? BOOST_MULT : 1)
      _tmpTargetVel.addScaledVector(_tmpRight,  dx * speed)
      _tmpTargetVel.addScaledVector(_worldUp,   dy * speed)
    }

    // Ease velocity toward target.  Use shorter time-constant when
    // accelerating (responsive press), longer when decelerating (smooth stop).
    const tau = anyKey ? ACCEL_TAU : DECEL_TAU
    // alpha = 1 - exp(-dt / tau) — exponential ease with stable behaviour
    // even at low frame rates.
    const alpha = 1 - Math.exp(-dt / tau)
    _vel.lerp(_tmpTargetVel, alpha)

    // Integrate; skip negligible motion to avoid jitter when stopped.
    if (_vel.lengthSq() > 1e-6) {
      _tmpMove.copy(_vel).multiplyScalar(dt)
      camera.position.add(_tmpMove)
      // Move the orbit target in lockstep so the pivot stays in front of
      // the camera.  Otherwise OrbitControls would orbit around an old
      // point and feel un-tethered.
      controls.target.add(_tmpMove)
    }
  }

  function _isTextTarget(e) {
    const t = e.target
    return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
  }

  function _onKeyDown(e) {
    if (_isTextTarget(e)) return
    const k = e.key.toLowerCase()
    if (k === 'shift') { _keys.add('shift'); return }
    if (['w', 'a', 's', 'd'].includes(k)) {
      // With a modifier held this is a shortcut (e.g. Ctrl+S = Save), not a
      // movement key.  Don't register it for panning — and drop any in-progress
      // hold so the camera doesn't keep drifting if a modifier is pressed
      // mid-pan — then let the event fall through to the shortcut handler
      // (no preventDefault, so Ctrl+S still saves).
      if (e.ctrlKey || e.metaKey || e.altKey) {
        _keys.delete(k)
        return
      }
      _keys.add(k)
      e.preventDefault()
      e.stopPropagation()
    }
  }

  function _onKeyUp(e) {
    if (_isTextTarget(e)) return
    const k = e.key.toLowerCase()
    if (k === 'shift') { _keys.delete('shift'); return }
    if (['w', 'a', 's', 'd'].includes(k)) _keys.delete(k)
  }

  function _onBlur() {
    _keys.clear()
    _vel.set(0, 0, 0)
  }

  // ── Attach ─────────────────────────────────────────────────────────────
  document.addEventListener('keydown', _onKeyDown, { capture: true })
  document.addEventListener('keyup',   _onKeyUp,   { capture: true })
  window.addEventListener('blur', _onBlur)
  if (typeof addFrameCallback === 'function') addFrameCallback(_onFrame)

  return {
    getMode: () => 'orbit',          // legacy callers expect this getter
    isFlyMode: () => false,          // fly mode removed; always false
    enterFly: () => {},              // no-op for backwards compat
    exitFly: () => {},               // no-op
    snapPivot: () => {},             // no-op (auto-pivot removed earlier)
    dispose() {
      document.removeEventListener('keydown', _onKeyDown, { capture: true })
      document.removeEventListener('keyup',   _onKeyUp,   { capture: true })
      window.removeEventListener('blur', _onBlur)
    },
  }
}
