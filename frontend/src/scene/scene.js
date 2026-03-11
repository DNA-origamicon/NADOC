/**
 * Three.js scene bootstrap.
 *
 * Creates the renderer, camera, lights, and OrbitControls.
 * Sizes the renderer to the canvas element's parent container, not window.
 * Returns a context object shared by all other modules.
 */

import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

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

  const controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.dampingFactor = 0.06
  controls.target.set(0, 0, 7)   // midpoint of 42 bp helix on Z axis

  // Lights
  scene.add(new THREE.AmbientLight(0xffffff, 0.45))
  const sun = new THREE.DirectionalLight(0xffffff, 1.1)
  sun.position.set(8, 14, 6)
  scene.add(sun)
  const fill = new THREE.DirectionalLight(0x4488cc, 0.35)
  fill.position.set(-6, -4, -8)
  scene.add(fill)

  // Render loop
  function animate() {
    requestAnimationFrame(animate)
    controls.update()
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

  return { scene, camera, renderer, controls }
}
