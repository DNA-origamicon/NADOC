/**
 * Three.js scene bootstrap.
 *
 * Creates the renderer, camera, lights, and OrbitControls.
 * Sizes the renderer to the canvas element's parent container, not window.
 * Returns a context object shared by all other modules.
 */

import * as THREE from 'three'
import { OrbitControls }    from 'three/addons/controls/OrbitControls.js'
import { TrackballControls } from 'three/addons/controls/TrackballControls.js'

function _makeOrbitControls(camera, canvas, target) {
  const c = new OrbitControls(camera, canvas)
  c.enableDamping = false
  if (target) c.target.copy(target)
  return c
}

function _makeTrackballControls(camera, canvas, target) {
  const c = new TrackballControls(camera, canvas)
  c.rotateSpeed = 3.0
  c.zoomSpeed   = 1.2
  c.panSpeed    = 0.8
  c.staticMoving = true
  if (target) c.target.copy(target)
  return c
}

export function initScene(canvas) {
  const container = canvas.parentElement

  function _w() { return container.clientWidth  || window.innerWidth  }
  function _h() { return container.clientHeight || window.innerHeight }

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
  renderer.setSize(_w(), _h())
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0d1117)

  // Camera positioned to see a 42 bp helix (~14 nm long along Z).
  const camera = new THREE.PerspectiveCamera(55, _w() / _h(), 0.01, 500)
  camera.position.set(6, 3, 7)

  // Mutable reference to whichever controls are currently active.
  // A Proxy is returned to callers so that switchOrbitMode() can swap the
  // underlying instance without invalidating any stored references.
  let _inner = _makeOrbitControls(camera, canvas)
  _inner.target.set(0, 0, 7)   // midpoint of 42 bp helix on Z axis

  const controls = new Proxy({}, {
    get(_, prop) {
      const val = _inner[prop]
      return typeof val === 'function' ? val.bind(_inner) : val
    },
    set(_, prop, value) {
      _inner[prop] = value
      return true
    },
  })

  let _currentOrbitMode = 'trackball'

  function switchOrbitMode(mode) {
    _currentOrbitMode = mode
    const savedTarget = _inner.target.clone()
    _inner.dispose()
    _inner = mode === 'trackball'
      ? _makeTrackballControls(camera, canvas, savedTarget)
      : _makeOrbitControls(camera, canvas, savedTarget)
  }

  // ── Camera capture / animation helpers ─────────────────────────────────────

  /** Returns a plain-object snapshot of the current camera state. */
  function captureCurrentCamera() {
    return {
      position: camera.position.toArray(),
      target:   controls.target.toArray(),
      up:       camera.up.toArray(),
      fov:      camera.fov,
      orbitMode: _currentOrbitMode,
    }
  }

  /**
   * Smoothly animate the camera to an exact stored position/target/up/fov.
   * @param {object} opts
   * @param {number[]} opts.position  — [x, y, z] destination camera position
   * @param {number[]} opts.target    — [x, y, z] destination controls.target
   * @param {number[]} opts.up        — [x, y, z] destination camera.up
   * @param {number}   [opts.fov]     — destination FOV (degrees); skipped if not provided
   * @param {number}   [opts.duration=350] — animation duration in ms
   * @returns {Promise<void>}  resolves when the animation is complete
   */
  let _animRaf = null
  function animateCameraTo({ position, target, up, fov, duration = 350 }) {
    if (_animRaf) { cancelAnimationFrame(_animRaf); _animRaf = null }

    const destPos    = new THREE.Vector3(...position)
    const destTarget = new THREE.Vector3(...target)
    const destUp     = new THREE.Vector3(...up)
    const startPos    = camera.position.clone()
    const startTarget = controls.target.clone()
    const startUp     = camera.up.clone()
    const startFov    = camera.fov
    const destFov     = (fov != null) ? fov : startFov
    const startTime   = performance.now()

    return new Promise(resolve => {
      function frame(now) {
        const raw = Math.min((now - startTime) / duration, 1)
        const t = raw < 0.5 ? 2 * raw * raw : -1 + (4 - 2 * raw) * raw // ease-in-out

        camera.position.lerpVectors(startPos, destPos, t)
        controls.target.lerpVectors(startTarget, destTarget, t)
        camera.up.lerpVectors(startUp, destUp, t).normalize()
        if (destFov !== startFov) {
          camera.fov = startFov + (destFov - startFov) * t
          camera.updateProjectionMatrix()
        }
        controls.update()

        if (raw < 1) {
          _animRaf = requestAnimationFrame(frame)
        } else {
          _animRaf = null
          resolve()
        }
      }
      _animRaf = requestAnimationFrame(frame)
    })
  }

  // Shift+wheel → fast zoom: boost zoomSpeed for the duration of the event.
  // Capture phase ensures this runs before the controls' own wheel listener.
  canvas.addEventListener('wheel', e => {
    if (!e.shiftKey) return
    const isTrackball = _inner instanceof TrackballControls
    _inner.zoomSpeed = isTrackball ? 4.8 : 4.0
    requestAnimationFrame(() => { _inner.zoomSpeed = isTrackball ? 1.2 : 1.0 })
  }, { capture: true, passive: true })

  // Shift+drag → fast pan: live-update panSpeed each pointermove while Shift is held.
  canvas.addEventListener('pointermove', e => {
    const isTrackball = _inner instanceof TrackballControls
    _inner.panSpeed = (e.shiftKey && e.buttons !== 0)
      ? (isTrackball ? 3.2 : 4.0)
      : (isTrackball ? 0.8 : 1.0)
  }, { capture: true, passive: true })

  // Lights
  scene.add(new THREE.AmbientLight(0xffffff, 0.45))
  const sun = new THREE.DirectionalLight(0xffffff, 1.1)
  sun.position.set(8, 14, 6)
  scene.add(sun)
  const fill = new THREE.DirectionalLight(0x4488cc, 0.35)
  fill.position.set(-6, -4, -8)
  scene.add(fill)

  // Render loop — use _inner directly to avoid Proxy overhead per frame.
  function animate() {
    requestAnimationFrame(animate)
    _inner.update()
    renderer.render(scene, camera)
  }
  animate()

  // Resize to container
  const resizeObserver = new ResizeObserver(() => {
    const w = _w()
    const h = _h()
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h)
  })
  resizeObserver.observe(container)

  return { scene, camera, renderer, controls, switchOrbitMode, captureCurrentCamera, animateCameraTo }
}
