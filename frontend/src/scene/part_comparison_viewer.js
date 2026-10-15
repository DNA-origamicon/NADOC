/** Independently owned static display; no live Design/store/export/simulation API. */
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { validatePartComparisonEnvelope, validatePartComparisonPane } from '../features/part_comparison_model.js'
import { createNanoparticleMaterial, createNanoparticleMesh } from './nanoparticle_display.js'
import { initProteinTraceRenderer } from './protein_trace_renderer.js'

export function buildPartComparisonScene(pane) {
  validatePartComparisonPane(pane)
  const scene = new THREE.Scene(), particles = [], materials = new Set(), proteinLayers = []
  let disposed = false
  function dispose() {
    if (disposed) return
    disposed = true
    for (const layer of proteinLayers) layer.dispose()
    for (const mesh of particles) { mesh.geometry.dispose(); scene.remove(mesh) }
    for (const material of materials) material.dispose()
    particles.length = 0; proteinLayers.length = 0; materials.clear()
    scene.clear()
  }
  try {
    scene.add(new THREE.AmbientLight(0xffffff, 1.4))
    const key = new THREE.DirectionalLight(0xffffff, 2.4)
    key.position.set(5, 8, 10); scene.add(key)
    const fill = new THREE.DirectionalLight(0xa9c8ff, 1)
    fill.position.set(-6, -2, 4); scene.add(fill)
    for (const particle of pane.particles) {
      // Native renderer expects the model's Transform wrapper. A raw array has
      // its own .values() iterator and must not be mistaken for that field.
      const native = { ...particle, pose: { values: particle.pose },
        quantum_dot: { display_color: particle.display_color } }
      const material = createNanoparticleMaterial(native); materials.add(material)
      const mesh = createNanoparticleMesh(native, material)
      mesh.userData.authoredVisible = particle.authored_visible
      particles.push(mesh); scene.add(mesh)
    }
    for (const representation of ['trace', 'ovoid']) {
      const proteins = pane.proteins.filter(protein => protein.representation === representation)
      if (!proteins.length) continue
      const layer = initProteinTraceRenderer(scene); proteinLayers.push(layer)
      layer.setMode(representation)
      layer.update({ atoms: proteins.flatMap(protein => protein.atoms) })
    }
    return { scene, dispose }
  } catch (error) { dispose(); throw error }
}

/** One context, two scissored scenes, one camera; redraw on orbit/resize/fit only. */
export function initPartComparisonViewer(host, projection, binding) {
  validatePartComparisonEnvelope(projection, binding)
  let renderer = null, controls = null, observer = null, alive = true, adjusting = false
  const panes = [], camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1000)
  let width = 800, height = 400, leftWidth = 400
  const bounds = new THREE.Box3()
  for (const pane of [projection.published, projection.proposed]) if (pane.bounds_nm) {
    bounds.expandByPoint(new THREE.Vector3(...pane.bounds_nm.minimum))
    bounds.expandByPoint(new THREE.Vector3(...pane.bounds_nm.maximum))
  }
  if (bounds.isEmpty()) bounds.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1))
  // Existing protein trace/ovoid padding is <=0.18nm; add a display margin.
  bounds.expandByScalar(0.5)
  function draw() {
    if (!alive || adjusting || !renderer || panes.length !== 2) return
    renderer.setScissorTest(true)
    for (let index = 0; index < 2; index++) {
      const start = index ? leftWidth : 0, paneWidth = index ? width - leftWidth : leftWidth
      camera.aspect = paneWidth / height; camera.updateProjectionMatrix()
      renderer.setViewport(start, 0, paneWidth, height)
      renderer.setScissor(start, 0, paneWidth, height)
      renderer.render(panes[index].scene, camera)
    }
  }
  function measure() {
    width = Math.max(4, host.clientWidth || 800); height = Math.max(2, host.clientHeight || 400)
    leftWidth = Math.floor(width / 2)
    renderer.setSize(width, height, false)
    camera.aspect = leftWidth / height; camera.updateProjectionMatrix()
  }
  function resize() { if (alive && renderer) { measure(); draw() } }
  function updateControls() {
    adjusting = true
    try { controls.update() } finally { adjusting = false }
  }
  function resetView() {
    if (!alive || !controls) return
    const center = bounds.getCenter(new THREE.Vector3())
    const radius = Math.max(0.5, bounds.getSize(new THREE.Vector3()).length() / 2)
    const vertical = THREE.MathUtils.degToRad(camera.fov / 2)
    const angle = Math.min(vertical, Math.atan(Math.tan(vertical) * leftWidth / height))
    const distance = radius / Math.sin(angle) * 1.08
    if (![...center.toArray(), radius, distance].every(Number.isFinite)) throw new Error('Comparison bounds cannot be displayed')
    camera.position.copy(center).add(new THREE.Vector3(0.25, 0.3, 1).normalize().multiplyScalar(distance))
    controls.target.copy(center)
    controls.minDistance = Math.max(0.05, radius * 0.05); controls.maxDistance = distance * 10
    camera.near = Math.max(0.001, distance / 10000); camera.far = Math.max(100, distance * 100)
    camera.updateProjectionMatrix(); updateControls(); draw()
  }
  function keyboard(event) {
    if (!alive) return
    if (event.key.toLowerCase() === 'f') { event.preventDefault(); event.stopPropagation(); resetView(); return }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
    event.preventDefault(); event.stopPropagation()
    const offset = camera.position.clone().sub(controls.target)
    const horizontal = event.key === 'ArrowLeft' || event.key === 'ArrowRight'
    const axis = horizontal ? camera.up.clone() : new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion)
    offset.applyAxisAngle(axis, (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? 1 : -1) * Math.PI / 24)
    camera.position.copy(controls.target).add(offset); updateControls(); draw()
  }
  function dispose() {
    if (!alive) return
    alive = false
    observer?.disconnect(); window.removeEventListener('resize', resize)
    controls?.removeEventListener('change', draw); controls?.dispose()
    renderer?.domElement.removeEventListener('keydown', keyboard)
    for (const pane of panes) pane.dispose()
    panes.length = 0
    renderer?.dispose(); renderer?.forceContextLoss?.(); renderer?.domElement.remove()
  }
  try {
    panes.push(buildPartComparisonScene(projection.published))
    panes.push(buildPartComparisonScene(projection.proposed))
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 2))
    renderer.setClearColor(0x171e28, 1)
    renderer.domElement.tabIndex = 0
    renderer.domElement.setAttribute('aria-label', 'Private authored geometry comparison. Drag to orbit; arrow keys rotate; F fits both panes.')
    host.append(renderer.domElement)
    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = false
    controls.addEventListener('change', draw)
    renderer.domElement.addEventListener('keydown', keyboard)
    observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
    observer?.observe(host)
    if (!observer) window.addEventListener('resize', resize)
    measure(); resetView()
    return { resetView, dispose }
  } catch (error) { dispose(); throw error }
}
