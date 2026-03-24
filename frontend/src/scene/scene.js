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
  c.enableDamping = true
  c.dampingFactor = 0.06
  if (target) c.target.copy(target)
  return c
}

function _makeTrackballControls(camera, canvas, target) {
  const c = new TrackballControls(camera, canvas)
  c.rotateSpeed = 3.0
  c.zoomSpeed   = 1.2
  c.panSpeed    = 0.8
  c.staticMoving = false
  c.dynamicDampingFactor = 0.08
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

  function switchOrbitMode(mode) {
    const savedTarget = _inner.target.clone()
    _inner.dispose()
    _inner = mode === 'trackball'
      ? _makeTrackballControls(camera, canvas, savedTarget)
      : _makeOrbitControls(camera, canvas, savedTarget)
  }

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

  return { scene, camera, renderer, controls, switchOrbitMode }
}
