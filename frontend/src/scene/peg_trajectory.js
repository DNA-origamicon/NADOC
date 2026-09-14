import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

/** Isolated rendering of recorded coordinates; never updates the design store. */
export function createPegTrajectoryView(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
  renderer.setClearColor('#0b1420')
  container.append(renderer.domElement)
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 2000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  let geometry, lines, points, lineMaterial, pointMaterial
  const resize = () => {
    const width = Math.max(1, container.clientWidth), height = Math.max(1, container.clientHeight)
    renderer.setSize(width, height)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()
  function clear() {
    if (lines) scene.remove(lines)
    if (points) scene.remove(points)
    geometry?.dispose(); lines?.geometry.dispose()
    lineMaterial?.dispose(); pointMaterial?.dispose()
  }
  return {
    load(entry) {
      clear()
      geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(entry.particles * 3), 3))
      const colors = new Float32Array(entry.particles * 3), indices = []
      const color = new THREE.Color()
      for (let i = 0; i < entry.particles; i++) {
        color.setHSL((Math.floor(i / entry.n) * 0.618 + 0.43) % 1, 0.65, 0.62)
        if (i % entry.n === 0 || i % entry.n === entry.n - 1) color.set('#ffc078')
        color.toArray(colors, i * 3)
        if (i % entry.n) indices.push(i - 1, i)
      }
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      const lineGeometry = new THREE.BufferGeometry()
      lineGeometry.setAttribute('position', geometry.attributes.position)
      lineGeometry.setAttribute('color', geometry.attributes.color)
      lineGeometry.setIndex(indices)
      lineMaterial = new THREE.LineBasicMaterial({ vertexColors: true })
      pointMaterial = new THREE.PointsMaterial({ vertexColors: true, size: entry.chains > 1 ? 2 : 5, sizeAttenuation: false })
      lines = new THREE.LineSegments(lineGeometry, lineMaterial)
      points = new THREE.Points(geometry, pointMaterial)
      lines.frustumCulled = false; points.frustumCulled = false
      scene.add(lines, points)
      const radius = Math.max(1, entry.radiusNm)
      camera.position.set(radius * 1.5, radius * 1.1, radius * 2.6)
      camera.far = radius * 30; camera.updateProjectionMatrix()
      controls.target.set(0, 0, 0); controls.update()
    },
    setFrame(coordinates) {
      geometry.attributes.position.array.set(coordinates)
      geometry.attributes.position.needsUpdate = true
    },
    render() { controls.update(); renderer.render(scene, camera) },
    dispose() {
      observer.disconnect(); controls.dispose(); clear()
      renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove()
    },
  }
}
