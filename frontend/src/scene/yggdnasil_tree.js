import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const palette = { square: 0x72dabb, honeycomb: 0xeebd72 }
const v = p => new THREE.Vector3(...p)
function release(group) {
  const geometries = new Set(), materials = new Set()
  group.traverse(o => { if (o.isInstancedMesh) o.dispose(); if (o.geometry) geometries.add(o.geometry); if (o.material) materials.add(o.material) })
  geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); group.removeFromParent()
}
function tube(points, radius, color) {
  return new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map(v)), 32, radius, 7, false),
    new THREE.MeshStandardMaterial({ color, roughness: 0.72, metalness: 0.16 }))
}
export function createYggTreeViewer(host, onSelect) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.setClearColor(0x0b1616)
  renderer.domElement.tabIndex = 0
  renderer.domElement.setAttribute('aria-label', '3D YggDNAsil tree. Drag to orbit, scroll to zoom. Use the structure selector and neighbor buttons for keyboard navigation. Press F to reset the view.')
  renderer.domElement.setAttribute('role', 'img')
  host.append(renderer.domElement)
  const labels = document.createElement('div'); labels.className = 'ygg-3d-labels'; host.append(labels)
  const tooltip = document.createElement('div'); tooltip.className = 'ygg-hover'; tooltip.hidden = true; host.append(tooltip)
  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xe9fff7, 0x253331, 2.7))
  const light = new THREE.DirectionalLight(0xffffff, 3); light.position.set(-15, 40, 35); scene.add(light)
  const camera = new THREE.PerspectiveCamera(43, 1, 0.1, 500)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true; controls.minDistance = 14; controls.maxDistance = 180
  const permanent = new THREE.Group(); scene.add(permanent)
  permanent.add(tube([[0, -12, 0], [-0.7, -6, 0.5], [0, 0, 0]], 0.65, 0x806f51))
  for (const sign of [-1, 1]) {
    permanent.add(tube([[0, -2, 0], [sign * 2, 0, 0], [sign * 6, 2, 0]], 0.38, 0x9b8c66))
    for (let i = 0; i < 3; i++) permanent.add(tube([[0, -11, 0], [sign * (3 + i), -13, i * 2 - 2], [sign * (7 + i), -13.5, i * 4 - 4]], 0.18, 0x695b43))
  }
  const ground = new THREE.GridHelper(74, 24, 0x29453e, 0x172d29); ground.position.y = -14; permanent.add(ground)
  let root = new THREE.Group(); scene.add(root)
  let model = { nodes: [], edges: [] }, selectedId = null, meshes = [], labelItems = [], frame = null, alive = true
  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2()
  function reset() { camera.position.set(12, 23, 82); controls.target.set(0, 10, 0); controls.update() }
  function update(next, selection) {
    model = next; selectedId = selection
    release(root); root = new THREE.Group(); scene.add(root); meshes = []; labels.replaceChildren(); labelItems = []
    const byId = new Map(model.nodes.map(n => [n.id, n]))
    const curvePositions = [], curveColors = []
    for (const stem of model.stems) {
      const n = byId.get(stem.to), sign = stem.lattice === 'square' ? -1 : 1
      if (stem.shape === 'hollow') {
        curvePositions.push(sign * 6, 2, 16, ...n.position)
        const color = new THREE.Color(palette[n.lattice]); curveColors.push(color.r, color.g, color.b, color.r, color.g, color.b)
        continue
      }
      root.add(tube([[sign * 6, 2, 0], [sign * 6.5, 3, n.position[2] / 2], n.position], 0.16, palette[n.lattice]))
    }
    for (const edge of model.edges) {
      const a = byId.get(edge.from), b = byId.get(edge.to)
      if (edge.parameter === 'curvature-counts' || edge.parameter === 'inner-radius') {
        curvePositions.push(...a.position, ...b.position)
        const color = new THREE.Color(palette[edge.lattice]); curveColors.push(color.r, color.g, color.b, color.r, color.g, color.b)
        continue
      }
      const middle = a.position.map((x, i) => (x + b.position[i]) / 2 + (i === 2 ? 0.15 : 0))
      root.add(tube([a.position, middle, b.position], 0.085, palette[edge.lattice]))
    }
    const lines = new THREE.BufferGeometry()
    lines.setAttribute('position', new THREE.Float32BufferAttribute(curvePositions, 3))
    lines.setAttribute('color', new THREE.Float32BufferAttribute(curveColors, 3))
    root.add(new THREE.LineSegments(lines, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.65 })))
    const sphere = new THREE.SphereGeometry(0.43, 8, 6)
    const materials = {
      square: new THREE.MeshStandardMaterial({ color: palette.square, roughness: 0.32, metalness: 0.25 }),
      honeycomb: new THREE.MeshStandardMaterial({ color: palette.honeycomb, roughness: 0.32, metalness: 0.25 }),
      excluded: new THREE.MeshStandardMaterial({ color: 0xbc6a64, roughness: 0.6 }),
      selected: new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0x719b87, emissiveIntensity: 0.8 }),
    }
    const solids = model.nodes.filter(n => n.shape !== 'hollow'), hollows = model.nodes.filter(n => n.shape === 'hollow')
    const points = new THREE.InstancedMesh(sphere, materials.square, solids.length)
    const rings = new THREE.InstancedMesh(new THREE.TorusGeometry(0.4, 0.09, 6, 12), materials.square, hollows.length)
    points.userData.nodes = solids; rings.userData.nodes = hollows
    let solidIndex = 0, hollowIndex = 0
    // Per-instance colors keep the complete atlas in one draw call.
    points.material.color.set(0xffffff)
    const matrix = new THREE.Matrix4(), rotation = new THREE.Quaternion()
    const neighbors = new Map()
    for (const edge of model.edges) {
      if (edge.from === selectedId) neighbors.set(edge.to, edge)
      if (edge.to === selectedId) neighbors.set(edge.from, edge)
    }
    for (const [i, n] of model.nodes.entries()) {
      const chosen = n.id === selectedId, curved = n.curvature?.angleRad > 0
      const scale = chosen ? 1.65 : curved ? 0.28 : 1
      matrix.compose(v(n.position), rotation, new THREE.Vector3(scale, scale, scale))
      const target = n.shape === 'hollow' ? rings : points, instance = n.shape === 'hollow' ? hollowIndex++ : solidIndex++
      target.setMatrixAt(instance, matrix)
      target.setColorAt(instance, new THREE.Color(chosen ? 0xffffff : n.routing.excluded ? 0xbc6a64 : palette[n.lattice]))
      const neighboring = neighbors.has(n.id)
      if (chosen || neighboring || (n.shape === 'hollow' ? i % Math.max(1, Math.ceil(model.nodes.length / 24)) === 0 : (n.id === n.rootId || !n.rootId) && n.index % 3 === 0)) {
        const label = document.createElement('button'); label.type = 'button'; label.className = `ygg-node-label${chosen ? ' is-selected' : ''}`
        const edge = neighbors.get(n.id)
        const delta = edge ? (edge.label || (edge.to === n.id ? '+' : '−') + edge.deltaHelices) : ''
        label.textContent = `${n.label || `${n.entry.helices}hb`}${delta ? ` (${delta})` : ''}`
        label.title = `${n.shape === 'hollow' ? `Straight hollow · Ro ${n.outerRadiusNm.toFixed(2)} / Ri ${n.innerRadiusNm.toFixed(2)} nm · ` : ''}${n.curvature ? `${n.curvature.angleDeg.toFixed(2)}° · ${n.curvature.loops} inserted / ${n.curvature.skips} deleted · ` : ''}${n.lattice} · ${n.center} center · ${n.entry.helices} helices × ${n.length} bp`
        label.setAttribute('aria-label', label.title); label.tabIndex = -1
        label.addEventListener('click', () => onSelect(n.id)); labels.append(label)
        labelItems.push({ label, position: v(n.position), priority: chosen ? 0 : neighboring ? 1 : 2 })
      }
    }
    root.add(points, rings); meshes.push(points, rings)
    for (const [name, material] of Object.entries(materials)) if (name !== 'square') material.dispose()
    for (const [lattice, x] of [['square', -13], ['honeycomb', 13]]) {
      const label = document.createElement('span'); label.className = `ygg-branch-label ${lattice}`; label.textContent = lattice.toUpperCase(); labels.append(label)
      labelItems.push({ label, position: v([x, -2, 0]), priority: 0 })
    }
    for (const sign of [-1, 1]) if (model.nodes.some(n => n.shape === 'hollow' && (n.lattice === 'square' ? -1 : 1) === sign)) {
      root.add(tube([[0, -2, 0], [sign * 3, 0, 8], [sign * 6, 2, 16]], 0.22, 0x9b8c66))
    }
    tooltip.hidden = true
    host.dataset.nodes = String(model.nodes.length); host.dataset.edges = String(model.edges.length)
    host.dataset.selected = selectedId || ''
  }
  function resize() { const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix() }
  const observer = new ResizeObserver(resize); observer.observe(host)
  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect()
    pointer.set(2 * (event.clientX - rect.left) / rect.width - 1, 1 - 2 * (event.clientY - rect.top) / rect.height)
    ray.setFromCamera(pointer, camera)
    const hit = ray.intersectObjects(meshes)[0]
    return hit ? hit.object.userData.nodes[hit.instanceId] : undefined
  }
  let down = null
  function pointerDown(event) { down = [event.clientX, event.clientY] }
  function pointerUp(event) {
    if (down && Math.hypot(event.clientX - down[0], event.clientY - down[1]) < 5) { const n = pick(event); if (n) onSelect(n.id) }
    down = null
  }
  function hover(event) {
    const n = pick(event); renderer.domElement.style.cursor = n ? 'pointer' : 'grab'; tooltip.hidden = !n
    if (n) tooltip.textContent = `${n.shape === 'hollow' ? `Straight hollow · Ro ${n.outerRadiusNm.toFixed(2)} / Ri ${n.innerRadiusNm.toFixed(2)} nm · ` : ''}${n.curvature ? `${n.curvature.angleDeg.toFixed(2)}° · I${n.curvature.loops}/D${n.curvature.skips} · ` : ''}${n.entry.helices}hb × ${n.length} bp · ${n.lattice} / ${n.center} · ${n.routing.label}`
  }
  function leave() { tooltip.hidden = true }
  function keyboard(event) { if (event.key.toLowerCase() === 'f') { event.preventDefault(); reset() } }
  renderer.domElement.addEventListener('pointerdown', pointerDown)
  renderer.domElement.addEventListener('pointerup', pointerUp)
  renderer.domElement.addEventListener('pointermove', hover)
  renderer.domElement.addEventListener('pointerleave', leave)
  renderer.domElement.addEventListener('keydown', keyboard)
  function draw() {
    if (!alive) return
    controls.update(); renderer.render(scene, camera)
    const occupied = []
    for (const item of [...labelItems].sort((a, b) => a.priority - b.priority)) {
      const p = item.position.clone().project(camera), x = (p.x + 1) * host.clientWidth / 2 + 8, y = (1 - p.y) * host.clientHeight / 2 - 8
      const overlaps = occupied.some(r => Math.abs(r[0] - x) < 65 && Math.abs(r[1] - y) < 22)
      const hidden = p.z < -1 || p.z > 1 || x < 0 || x > host.clientWidth - 25 || y < 0 || y > host.clientHeight - 20 || (overlaps && item.priority > 0)
      item.label.hidden = hidden
      if (!hidden) { item.label.style.transform = `translate(${x}px, ${y}px)`; occupied.push([x, y]) }
    }
    frame = requestAnimationFrame(draw)
  }
  reset(); resize(); draw()
  return { update, reset, dispose() {
    alive = false; cancelAnimationFrame(frame); observer.disconnect(); controls.dispose()
    renderer.domElement.removeEventListener('pointerdown', pointerDown); renderer.domElement.removeEventListener('pointerup', pointerUp)
    renderer.domElement.removeEventListener('pointermove', hover); renderer.domElement.removeEventListener('pointerleave', leave)
    renderer.domElement.removeEventListener('keydown', keyboard)
    release(root); release(permanent); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); labels.remove(); tooltip.remove()
  } }
}
