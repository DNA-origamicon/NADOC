/**
 * Hybrid camera navigation: logarithmic orbit with auto-pivot + WASD fly mode.
 *
 * Orbit mode (default): OrbitControls is active. On pointerdown, controls.target
 * snaps to the world-space center of the nearest "part" — every visible assembly
 * instance in assembly mode, or the selection / design bounding box otherwise.
 * Pan and dolly distances are already proportional to distance-from-target for
 * a perspective camera (Three.js OrbitControls), so log-feel is intrinsic — we
 * just keep the pivot meaningful.
 *
 * Fly mode: triggered when camera-to-nearest-part distance exceeds
 * FLY_TRIGGER_MULT × part radius. OrbitControls is disabled. WASD translates
 * along camera-relative axes (R/F = world up/down, Shift = boost). Right-drag
 * yaws/pitches the camera with the horizon locked to world-Y. Speed scales with
 * distance to the nearest part so you can cross microns and inspect nanometers
 * with the same key.
 *
 * Fly → Orbit return: left-click on a part (snaps pivot there) OR wheel-zoom
 * back inside FLY_EXIT_MULT × part radius. Hysteresis (TRIGGER > EXIT) prevents
 * flapping at the boundary. Escape also exits.
 *
 * We do not intercept canvas pointerdown when controls.enabled is false — that
 * means another system (deform editor, animation playback, cluster gizmo) owns
 * the camera and should not be disturbed.
 */

import * as THREE from 'three'

const FLY_TRIGGER_MULT = 12     // d > radius × this  → enter fly
const FLY_EXIT_MULT    = 6      // d < radius × this  → exit  fly
const MIN_RADIUS_NM    = 5      // floor for tiny parts, so a single bead doesn't pin you in orbit
const BASE_SPEED_FRAC  = 0.6    // fly speed = nearestDist × this (nm/sec at no boost)
const MIN_FLY_SPEED    = 2.0    // nm/sec, ensures motion even when nearest part is at the camera
const BOOST_MULT       = 5
const LOOK_SENS        = 0.004  // radians per pixel
const PITCH_LIMIT      = Math.PI / 2 - 0.05

export function initNavController({
  scene, camera, controls, canvas,
  store, assemblyRenderer, designRenderer,
  addFrameCallback,
}) {
  // ── State ──────────────────────────────────────────────────────────────
  let _mode           = 'orbit'   // 'orbit' | 'fly'
  let _yaw            = 0          // around world Y
  let _pitch          = 0          // around camera right
  let _rightDragging  = false
  let _lastX          = 0
  let _lastY          = 0
  let _activePointer  = null
  const _keys         = new Set()
  let _lastTime       = performance.now()

  // ── HUD ────────────────────────────────────────────────────────────────
  const hud = document.createElement('div')
  hud.id = 'nav-mode-indicator'
  Object.assign(hud.style, {
    position:    'absolute',
    top:         '12px',
    left:        '50%',
    transform:   'translateX(-50%)',
    padding:     '4px 10px',
    background:  'rgba(20, 80, 160, 0.85)',
    color:       '#fff',
    font:        '12px/1 system-ui, sans-serif',
    borderRadius:'4px',
    pointerEvents:'none',
    zIndex:      '50',
    display:     'none',
  })
  hud.textContent = 'FLY · WASD move · R/F up·down · Shift boost · right-drag look · click part to exit'
  document.body.appendChild(hud)

  function _updateHud() {
    hud.style.display = (_mode === 'fly') ? 'block' : 'none'
  }

  // ── Parts enumeration ──────────────────────────────────────────────────
  const _tmpBox = new THREE.Box3()
  const _tmpV3  = new THREE.Vector3()

  function _getParts() {
    const state = store.getState?.() ?? {}
    if (state.assemblyActive && state.currentAssembly) {
      const list = assemblyRenderer?.getInstanceCenters?.() ?? []
      if (list.length) return list
    }
    // Single-design fallback: selection center if available, else design bbox.
    const root = designRenderer?.getHelixCtrl?.()?.root
    if (!root) return []
    _tmpBox.makeEmpty()
    _tmpBox.expandByObject(root)
    if (_tmpBox.isEmpty()) return []
    const center = _tmpBox.getCenter(new THREE.Vector3())
    const size   = _tmpBox.getSize(_tmpV3)
    const radius = Math.max(MIN_RADIUS_NM, Math.max(size.x, size.y, size.z) * 0.5)
    // If something is selected and has a Vector3 position, prefer that as pivot.
    const sel = state.selectedObject
    const selPos = sel?.position
    if (selPos && Number.isFinite(selPos.x)) {
      return [{ id: 'sel', center: new THREE.Vector3(selPos.x, selPos.y, selPos.z), radius }]
    }
    return [{ id: 'design', center, radius }]
  }

  function _nearestPart() {
    const parts = _getParts()
    if (!parts.length) return null
    let best = null
    let bestDist = Infinity
    for (const p of parts) {
      const d = camera.position.distanceTo(p.center)
      if (d < bestDist) { bestDist = d; best = p }
    }
    return best
  }

  function _snapPivotToNearest() {
    const p = _nearestPart()
    if (!p) return
    controls.target.copy(p.center)
  }

  // ── Mode transitions ───────────────────────────────────────────────────
  function _enterFly() {
    if (_mode === 'fly') return
    _mode = 'fly'
    controls.enabled = false
    // Initialize yaw/pitch from current camera forward so look-around is continuous.
    const fwd = new THREE.Vector3()
    camera.getWorldDirection(fwd)
    _yaw   = Math.atan2(fwd.x, fwd.z)
    _pitch = Math.asin(THREE.MathUtils.clamp(fwd.y, -1, 1))
    _updateHud()
  }

  function _exitFly() {
    if (_mode === 'orbit') return
    _mode = 'orbit'
    _keys.clear()
    _rightDragging = false
    controls.enabled = true
    // Don't auto-snap pivot — fly mode keeps controls.target in front of the
    // camera, which is a reasonable orbit pivot. Click-on-part during fly sets
    // its own target explicitly before calling here.
    _updateHud()
  }

  function _checkThreshold() {
    const p = _nearestPart()
    if (!p) return
    const r = Math.max(p.radius, MIN_RADIUS_NM)
    const d = camera.position.distanceTo(p.center)
    if (_mode === 'orbit' && d > r * FLY_TRIGGER_MULT) _enterFly()
    else if (_mode === 'fly' && d < r * FLY_EXIT_MULT) _exitFly()
  }

  // ── Per-frame: WASD integration + threshold check ──────────────────────
  // _pendingCheck is set by user-initiated camera changes (wheel, fly movement).
  // We never check the threshold from a resting state, so initial scene layout
  // never auto-enters fly mode — only an actual zoom-out can trigger it.
  let _pendingCheck = false
  function _onFrame() {
    const now = performance.now()
    const dt = Math.min((now - _lastTime) / 1000, 0.1)
    _lastTime = now

    if (_mode === 'fly') {
      _updateFly(dt)
      _pendingCheck = true  // fly motion may cross threshold every frame
    }
    if (_pendingCheck) {
      _checkThreshold()
      _pendingCheck = false
    }
  }

  function _updateFly(dt) {
    const part = _nearestPart()
    const distToPart = part ? camera.position.distanceTo(part.center) : 100
    const baseSpeed  = Math.max(distToPart * BASE_SPEED_FRAC, MIN_FLY_SPEED)
    const boost      = _keys.has('shift') ? BOOST_MULT : 1
    const step       = baseSpeed * boost * dt

    const fwd = new THREE.Vector3()
    camera.getWorldDirection(fwd)
    const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize()
    const upWorld = new THREE.Vector3(0, 1, 0)

    const move = new THREE.Vector3()
    if (_keys.has('w')) move.addScaledVector(fwd,     step)
    if (_keys.has('s')) move.addScaledVector(fwd,    -step)
    if (_keys.has('d')) move.addScaledVector(right,   step)
    if (_keys.has('a')) move.addScaledVector(right,  -step)
    if (_keys.has('r')) move.addScaledVector(upWorld, step)
    if (_keys.has('f')) move.addScaledVector(upWorld,-step)

    if (move.lengthSq() > 0) {
      camera.position.add(move)
      // Slide target along with the camera so re-entering orbit doesn't yank.
      controls.target.add(move)
    }
  }

  // ── Pointer / wheel handlers ───────────────────────────────────────────
  function _isOurEvent() {
    // If something else has disabled controls (deform tool, gizmo, animation),
    // we cede — only act when controls would normally be in charge.
    return _mode === 'fly' || controls.enabled !== false
  }

  function _onPointerDown(e) {
    if (!_isOurEvent()) return

    if (_mode === 'orbit') {
      // Pivot snap disabled — was too jerky during part-mating. Re-enable here
      // if/when we want auto-pivot back. Click-on-part-in-fly still retargets.
      return
    }

    // Fly mode
    if (e.button === 2) {
      _rightDragging = true
      _lastX = e.clientX
      _lastY = e.clientY
      _activePointer = e.pointerId
      try { canvas.setPointerCapture?.(e.pointerId) } catch {}
      e.preventDefault()
      e.stopPropagation()
    } else if (e.button === 0) {
      // Left-click in fly: if it hits a part, snap pivot and return to orbit.
      const state = store.getState?.() ?? {}
      if (state.assemblyActive && assemblyRenderer?.pickInstance) {
        const rect = canvas.getBoundingClientRect()
        const ndc = new THREE.Vector2(
          ((e.clientX - rect.left) / rect.width)  * 2 - 1,
          -((e.clientY - rect.top) / rect.height) * 2 + 1,
        )
        const inst = assemblyRenderer.pickInstance(ndc, camera)
        if (inst) {
          // Snap pivot to that instance's center via getInstanceCenters lookup.
          const centers = assemblyRenderer.getInstanceCenters?.() ?? []
          const match = centers.find(c => c.id === inst.id)
          if (match) controls.target.copy(match.center)
          _exitFly()
          return
        }
      }
    }
  }

  function _onPointerMove(e) {
    if (_mode !== 'fly' || !_rightDragging) return
    if (_activePointer != null && e.pointerId !== _activePointer) return
    const dx = e.clientX - _lastX
    const dy = e.clientY - _lastY
    _lastX = e.clientX
    _lastY = e.clientY
    _yaw   -= dx * LOOK_SENS
    _pitch -= dy * LOOK_SENS
    _pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, _pitch))
    _applyLookAt()
    e.preventDefault()
    e.stopPropagation()
  }

  function _onPointerUp(e) {
    if (_mode === 'fly' && _rightDragging && e.button === 2) {
      _rightDragging = false
      try { canvas.releasePointerCapture?.(e.pointerId) } catch {}
      _activePointer = null
      e.preventDefault()
    }
    // Pan/orbit gestures can change distance to nearest part — re-evaluate.
    if (_mode === 'orbit') _pendingCheck = true
  }

  function _applyLookAt() {
    const cosP = Math.cos(_pitch)
    const dir = new THREE.Vector3(
      Math.sin(_yaw) * cosP,
      Math.sin(_pitch),
      Math.cos(_yaw) * cosP,
    )
    const lookTarget = camera.position.clone().add(dir)
    camera.up.set(0, 1, 0)
    camera.lookAt(lookTarget)
    // Keep controls.target a small step in front of the camera so OrbitControls
    // has a sane pivot if we re-enter orbit mid-look. It will be re-snapped on
    // _exitFly() anyway.
    controls.target.copy(lookTarget)
  }

  function _onContextMenu(e) {
    if (_mode === 'fly') e.preventDefault()
  }

  function _onWheel(_e) {
    // Mark the threshold check for the next frame. OrbitControls processes the
    // wheel event during its update(); checking before that runs would compare
    // stale positions, so we just request a check.
    _pendingCheck = true
  }

  // ── Keyboard ───────────────────────────────────────────────────────────
  function _isTextTarget(e) {
    const t = e.target
    return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
  }

  function _onKeyDown(e) {
    if (_isTextTarget(e)) return
    if (_mode !== 'fly') {
      // Allow Escape to exit fly if somehow stuck — also future hotkey: F to frame.
      return
    }
    if (e.key === 'Escape') { _exitFly(); return }
    const k = e.key.toLowerCase()
    if (k === 'shift') { _keys.add('shift'); return }
    if (['w','a','s','d','r','f'].includes(k)) {
      _keys.add(k)
      // Prevent registered global shortcuts (e.g. 'r', 'f' may bind elsewhere later) from firing.
      e.preventDefault()
      e.stopPropagation()
    }
  }

  function _onKeyUp(e) {
    if (_isTextTarget(e)) return
    const k = e.key.toLowerCase()
    if (k === 'shift') { _keys.delete('shift'); return }
    if (['w','a','s','d','r','f'].includes(k)) _keys.delete(k)
  }

  function _onBlur() {
    _keys.clear()
    _rightDragging = false
  }

  // ── Attach ─────────────────────────────────────────────────────────────
  // Bubble phase: OrbitControls' own pointerdown listener fires alongside, and
  // our _snapPivotToNearest() mutates controls.target which OrbitControls reads
  // during the subsequent pointermove — order within the same phase doesn't
  // matter because the value is read on move, not down.
  canvas.addEventListener('pointerdown', _onPointerDown)
  canvas.addEventListener('pointermove', _onPointerMove)
  canvas.addEventListener('pointerup',   _onPointerUp)
  canvas.addEventListener('contextmenu', _onContextMenu)
  canvas.addEventListener('wheel',       _onWheel, { passive: true })
  document.addEventListener('keydown', _onKeyDown, { capture: true })
  document.addEventListener('keyup',   _onKeyUp,   { capture: true })
  window.addEventListener('blur', _onBlur)

  if (typeof addFrameCallback === 'function') addFrameCallback(_onFrame)

  _updateHud()

  return {
    getMode:    () => _mode,
    isFlyMode:  () => _mode === 'fly',
    enterFly:   _enterFly,
    exitFly:    _exitFly,
    snapPivot:  _snapPivotToNearest,
    dispose() {
      canvas.removeEventListener('pointerdown', _onPointerDown)
      canvas.removeEventListener('pointermove', _onPointerMove)
      canvas.removeEventListener('pointerup',   _onPointerUp)
      canvas.removeEventListener('contextmenu', _onContextMenu)
      canvas.removeEventListener('wheel',       _onWheel)
      document.removeEventListener('keydown', _onKeyDown, { capture: true })
      document.removeEventListener('keyup',   _onKeyUp,   { capture: true })
      window.removeEventListener('blur', _onBlur)
      hud.remove()
    },
  }
}
