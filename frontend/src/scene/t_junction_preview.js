/** Isolated Three.js renderer for the T-junction routing concept in Help. */
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const COLORS = { body: 0x89caff, branch: 0xc4a2ff, bridge: 0xffc766, cut: 0xf08080 }
const vector = point => new THREE.Vector3(...point)

/** Arc-length polyline: rendering follows the model's route without spline overshoot. */
class RouteCurve extends THREE.Curve {
  constructor(points, closed = false) {
    super()
    this.points = points.map(vector).filter((p, i, all) => !i || p.distanceTo(all[i - 1]) > 1e-8)
    if (closed && this.points.length > 1 && this.points[0].distanceTo(this.points.at(-1)) > 1e-8) this.points.push(this.points[0].clone())
    this.distances = [0]
    for (let i = 1; i < this.points.length; i++) this.distances.push(this.distances[i - 1] + this.points[i].distanceTo(this.points[i - 1]))
    this.length = this.distances.at(-1) || 0
  }
  getPoint(t, target = new THREE.Vector3()) {
    if (this.points.length < 2 || this.length === 0) return target.copy(this.points[0] || new THREE.Vector3())
    const distance = Math.min(1, Math.max(0, t)) * this.length
    let low = 1, high = this.distances.length - 1
    while (low < high) {
      const middle = (low + high) >> 1
      if (this.distances[middle] < distance) low = middle + 1
      else high = middle
    }
    const span = this.distances[low] - this.distances[low - 1]
    return target.lerpVectors(this.points[low - 1], this.points[low], span ? (distance - this.distances[low - 1]) / span : 0)
  }
}

function tube(points, { radius = 0.21, color = 0x5ee7cb, closed = false } = {}) {
  if (points.length < 2) return null
  const curve = new RouteCurve(points, closed)
  if (!curve.length) return null
  const geometry = new THREE.TubeGeometry(curve, Math.max(32, Math.min(4096, points.length * 3)), radius, 7, closed)
  return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color, roughness: 0.42, metalness: 0.08 }))
}

function directionArrow(points, color, fraction = 0.55, size = 1) {
  if (points.length < 2) return null
  const curve = new RouteCurve(points)
  if (!curve.length) return null
  const at = curve.getPoint(fraction), next = curve.getPoint(Math.min(0.99, fraction + 0.02))
  const tangent = next.sub(at).normalize()
  if (!tangent.lengthSq()) return null
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.55 * size, 1.6 * size, 12), new THREE.MeshBasicMaterial({ color }))
  arrow.position.copy(at)
  arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent)
  return arrow
}

/** The meshes and directed routes are derived exclusively from the preview model. */
export function buildTJunctionPreviewGroup(model, { representation = 'both', highlightBridges = true } = {}) {
  const group = new THREE.Group()
  group.name = 'T-junction routing concept'
  const showBundles = representation !== 'scaffold'
  const showRoutes = representation !== 'bundles'
  for (const helix of model.helices) {
    const start = vector(helix.start), end = vector(helix.end), delta = end.clone().sub(start)
    const mesh = new THREE.Mesh(
      new THREE.CylinderGeometry(helix.radiusNm, helix.radiusNm, delta.length(), 16),
      new THREE.MeshStandardMaterial({
        color: COLORS[helix.bundle] ?? COLORS.body, transparent: showRoutes,
        opacity: showRoutes ? 0.24 : 0.92, depthWrite: !showRoutes, roughness: 0.65,
      }),
    )
    mesh.position.copy(start).add(end).multiplyScalar(0.5)
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
    mesh.visible = showBundles
    mesh.userData = { kind: 'helix', helixId: helix.id, bundle: helix.bundle }
    group.add(mesh)
  }
  if (showRoutes) {
    for (const route of model.routes) {
      const mesh = tube(route.points, { color: route.color, closed: route.closed })
      if (!mesh) continue
      mesh.userData = { kind: 'scaffold', routeId: route.id, closed: route.closed, pointCount: route.points.length }
      group.add(mesh)
      const arrow = directionArrow(route.points, route.color, 0.22)
      if (arrow) { arrow.userData.kind = 'route-direction'; group.add(arrow) }
    }
  }
  if (highlightBridges) {
    for (const bridge of model.bridges) {
      const color = bridge.color ?? COLORS.bridge
      const mesh = tube(bridge.points, { radius: 0.19, color })
      if (!mesh) continue
      mesh.userData = { kind: 'bridge', bridgeId: bridge.id }
      group.add(mesh)
      const arrow = directionArrow(bridge.points, color, 0.55, 0.6)
      if (arrow) { arrow.userData.kind = 'bridge-direction'; group.add(arrow) }
    }
    for (const cut of model.cuts) {
      const geometry = new THREE.BufferGeometry().setFromPoints(cut.points.map(vector))
      const line = new THREE.Line(geometry, new THREE.LineDashedMaterial({ color: COLORS.cut, dashSize: 0.5, gapSize: 0.4, depthTest: false }))
      line.computeLineDistances()
      line.userData = { kind: 'cut', cutId: cut.id }
      group.add(line)
    }
    for (const port of model.ports) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(0.22, 12, 8), new THREE.MeshBasicMaterial({ color: COLORS.bridge }))
      marker.position.copy(vector(port.position))
      marker.userData = { kind: 'port', portId: port.id }
      group.add(marker)
    }
  }
  return group
}

export function disposeTJunctionPreviewGroup(group) {
  const geometries = new Set(), materials = new Set()
  group?.traverse(object => {
    if (object.geometry) geometries.add(object.geometry)
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) if (material) materials.add(material)
  })
  geometries.forEach(geometry => geometry.dispose())
  materials.forEach(material => material.dispose())
  group?.removeFromParent()
}

export function createTJunctionPreviewViewer(host, initialModel, initialOptions = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x0b1220, 1)
  renderer.domElement.setAttribute('aria-label', 'Interactive three-dimensional T-junction. Drag to orbit, scroll to zoom. Arrow keys rotate; F resets the view.')
  renderer.domElement.setAttribute('role', 'img')
  renderer.domElement.tabIndex = 0
  host.appendChild(renderer.domElement)
  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x17243d, 2.0))
  const light = new THREE.DirectionalLight(0xffffff, 2.0)
  light.position.set(30, 55, 70)
  scene.add(light)
  const camera = new THREE.PerspectiveCamera(36, 1, 0.05, 2000)
  camera.up.set(0, 1, 0)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.1
  let model = initialModel, options = initialOptions
  let root = buildTJunctionPreviewGroup(model, options)
  scene.add(root)
  let alive = true, raf = null
  let labels = []
  const labelLayer = document.createElement('div')
  labelLayer.className = 'tjh-port-labels'
  labelLayer.setAttribute('aria-hidden', 'true')
  host.appendChild(labelLayer)

  function rebuildLabels() {
    labelLayer.replaceChildren()
    labels = options.highlightBridges === false ? [] : model.ports.map((port, index) => {
      const node = document.createElement('span')
      node.className = 'tjh-port-label'
      node.textContent = port.label
      labelLayer.appendChild(node)
      return { node, position: vector(port.position), index }
    })
  }
  function resetView() {
    const bounds = new THREE.Box3()
    for (const helix of model.helices) { bounds.expandByPoint(vector(helix.start)); bounds.expandByPoint(vector(helix.end)) }
    for (const route of model.routes) for (const point of route.points) bounds.expandByPoint(vector(point))
    bounds.expandByScalar(2.5)
    const center = bounds.getCenter(new THREE.Vector3())
    const radius = Math.max(3, bounds.getSize(new THREE.Vector3()).length() / 2)
    const direction = new THREE.Vector3(0.25, 0.3, 1).normalize()
    const right = new THREE.Vector3().crossVectors(camera.up, direction).normalize()
    const up = new THREE.Vector3().crossVectors(direction, right).normalize()
    const tanVertical = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
    let distance = 1
    for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
      const point = new THREE.Vector3(x, y, z).sub(center)
      distance = Math.max(distance, point.dot(direction) + Math.max(Math.abs(point.dot(up)) / tanVertical, Math.abs(point.dot(right)) / (tanVertical * camera.aspect)))
    }
    distance *= 1.08
    camera.position.copy(center).add(direction.multiplyScalar(distance))
    controls.target.copy(center)
    camera.near = Math.max(0.01, distance / 1000)
    camera.far = Math.max(1000, distance * 10)
    controls.minDistance = radius * 0.35
    controls.maxDistance = distance * 4
    camera.updateProjectionMatrix()
    controls.update()
  }
  function resize() {
    const width = Math.max(2, host.clientWidth || 640), height = Math.max(2, host.clientHeight || 440)
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
  observer?.observe(host)
  if (!observer) window.addEventListener('resize', resize)
  resize()
  resetView()
  rebuildLabels()

  function keyboard(event) {
    if (event.key.toLowerCase() === 'f') { event.preventDefault(); resetView(); return }
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
    event.preventDefault()
    event.stopPropagation()
    const offset = camera.position.clone().sub(controls.target)
    const horizontal = event.key === 'ArrowLeft' || event.key === 'ArrowRight'
    const axis = horizontal ? camera.up.clone() : new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion)
    const angle = (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? 1 : -1) * Math.PI / 24
    offset.applyAxisAngle(axis, angle)
    camera.position.copy(controls.target).add(offset)
    controls.update()
  }
  renderer.domElement.addEventListener('keydown', keyboard)

  function draw() {
    if (!alive) return
    controls.update()
    renderer.render(scene, camera)
    for (const label of labels) {
      const point = label.position.clone().project(camera)
      const visible = point.z > -1 && point.z < 1 && Math.abs(point.x) < 1 && Math.abs(point.y) < 1
      label.node.hidden = !visible
      if (visible) {
        label.node.style.left = `${(point.x + 1) * 50}%`
        label.node.style.top = `${(1 - point.y) * 50}%`
        label.node.style.transform = `translate(${label.index % 2 ? '6px' : 'calc(-100% - 6px)'}, ${label.index < 2 ? '-190%' : '95%'})`
      }
    }
    raf = requestAnimationFrame(draw)
  }
  draw()
  return {
    update(nextModel, nextOptions = options) {
      if (!alive) return
      model = nextModel; options = nextOptions
      disposeTJunctionPreviewGroup(root)
      root = buildTJunctionPreviewGroup(model, options)
      scene.add(root)
      rebuildLabels()
    },
    resetView,
    dispose() {
      if (!alive) return
      alive = false
      if (raf !== null) cancelAnimationFrame(raf)
      observer?.disconnect()
      if (!observer) window.removeEventListener('resize', resize)
      renderer.domElement.removeEventListener('keydown', keyboard)
      controls.dispose()
      disposeTJunctionPreviewGroup(root)
      renderer.dispose()
      renderer.forceContextLoss?.()
      renderer.domElement.remove()
      labelLayer.remove()
    },
  }
}
