/** Help > Connectivity: read-only graph-grammar proposals in the current scene. */
import * as THREE from 'three'
import { discoverConnectivity, graphProjection, nanoparticleSites, sampleEdge } from '../design/connectivity_graph.js'
import { buildOrigamiPathPreview } from '../design/origami_path_preview.js'
import { createOrigamiPathOverlay } from '../scene/origami_path_preview.js'
import './connectivity.css'

const COLORS = ['#5ed9ed', '#a5e075', '#c29bff', '#ffae68', '#ff7faf', '#82b7ff', '#e3da79']
const svgElement = (tag, attrs = {}) => {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag)
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value)
  return el
}

export function createConnectivityOverlay(candidate) {
  const group = new THREE.Group(); group.name = 'Nanoparticle connectivity preview'
  group.userData.connectivityPreview = true
  for (const edge of candidate.edges) {
    const curve = new THREE.CubicBezierCurve3(...edge.controlPoints.map(p => new THREE.Vector3(...p)))
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 32, .23 * Math.sqrt(edge.hb), 6, false),
      new THREE.MeshBasicMaterial({ color: COLORS[edge.depth % COLORS.length], depthTest: false, depthWrite: false, transparent: true, opacity: .88 }))
    mesh.renderOrder = 950; mesh.userData.connectivityEdge = edge.id
    // Diagnostic geometry must not intercept normal scene picking.
    mesh.raycast = () => {}
    group.add(mesh)
  }
  for (const node of candidate.nodes.filter(n => n.kind === 'split')) {
    const incoming = candidate.edges.find(e => e.target === node.id)
    const outgoing = candidate.edges.find(e => e.source === node.id)
    const axis = incoming
      ? new THREE.Vector3(...incoming.controlPoints[3]).sub(new THREE.Vector3(...incoming.controlPoints[2])).normalize()
      : new THREE.Vector3(...outgoing.controlPoints[0]).sub(new THREE.Vector3(...outgoing.controlPoints[1])).normalize()
    const sleeve = new THREE.Mesh(new THREE.CylinderGeometry(.3 * Math.sqrt(node.sectionHB), .3 * Math.sqrt(node.sectionHB), 3, 10),
      new THREE.MeshBasicMaterial({ color: '#ffffff', depthTest: false, depthWrite: false, transparent: true, opacity: .7 }))
    sleeve.position.copy(new THREE.Vector3(...node.position).addScaledVector(axis, -1.5))
    sleeve.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axis)
    sleeve.renderOrder = 951; sleeve.raycast = () => {}; group.add(sleeve)
  }
  return group
}

export function disposeConnectivityOverlay(group) {
  group?.traverse(obj => { obj.geometry?.dispose(); obj.material?.dispose() })
  group?.removeFromParent()
}

export function drawConnectivityDiagram(svg, candidate, sites, preview = null) {
  svg.replaceChildren()
  const project = graphProjection(sites)
  const all = [...sites.map(s => s.center), ...candidate.edges.flatMap(e => sampleEdge(e))].map(project)
  const xs = all.map(p => p[0]), ys = all.map(p => p[1])
  const minX = Math.min(...xs), minY = Math.min(...ys), width = Math.max(...xs) - minX, height = Math.max(...ys) - minY
  const scale = Math.min(290 / Math.max(width, 1), 180 / Math.max(height, 1))
  const pos = p => { const q = project(p); return [175 + (q[0] - minX - width / 2) * scale, 115 - (q[1] - minY - height / 2) * scale] }
  const text = (p, value, cls) => { const t = svgElement('text', { x: p[0], y: p[1], class: cls }); t.textContent = value; svg.append(t) }
  for (const edge of candidate.edges) {
    const ps = edge.controlPoints.map(pos)
    const path = svgElement('path', { d: `M${ps[0]} C${ps[1]} ${ps[2]} ${ps[3]}`, fill: 'none', stroke: COLORS[edge.depth % COLORS.length], 'stroke-width': 1.5 * Math.sqrt(preview?.hb ?? edge.hb) })
    const title = svgElement('title'); title.textContent = `${preview?.hb ?? edge.hb}HB · ${edge.lengthNm.toFixed(1)} nm`; path.append(title); svg.append(path)
  }
  for (const node of candidate.nodes.filter(n => n.kind === 'split')) {
    const p = pos(node.position)
    svg.append(svgElement('rect', { x: p[0] - 4, y: p[1] - 4, width: 8, height: 8, fill: '#ffffff' }))
    text([p[0], p[1] - 10], preview ? `${preview.junctionHB}HB → ${preview.hb}HB + ${preview.hb}HB` : node.label, 'connectivity-split-label')
  }
  for (const site of sites) {
    const p = pos(site.center)
    svg.append(svgElement('circle', { cx: p[0], cy: p[1], r: Math.max(5, Math.min(12, site.radius * scale)), fill: '#d4af37', stroke: '#fff0b8' }))
    text([p[0], p[1] + 23], site.label, 'connectivity-np-label')
  }
}

export function frameConnectivity(candidate, sites, camera, controls, preview = null) {
  if (!camera || !controls || !candidate) return
  const points = [...sites.map(p => p.center), ...candidate.edges.flatMap(e => sampleEdge(e)), ...(preview?.paths.flatMap(p => p.points) || [])].map(p => new THREE.Vector3(...p))
  const bounds = new THREE.Box3().setFromPoints(points).expandByScalar(Math.max(...sites.map(p => p.radius)) + 4)
  const center = bounds.getCenter(new THREE.Vector3()), radius = bounds.getSize(new THREE.Vector3()).length() / 2
  let axis = new THREE.Vector3(1, 0, 0), maxDistance = 0
  for (const a of points) {
    const delta = a.clone().sub(center)
    if (delta.lengthSq() > maxDistance) { axis = delta; maxDistance = delta.lengthSq() }
  }
  axis.normalize()
  let normal = new THREE.Vector3(), area = 0
  for (const p of points) {
    const cross = axis.clone().cross(p.clone().sub(center))
    if (cross.lengthSq() > area) { normal = cross; area = cross.lengthSq() }
  }
  if (area < 1e-8) normal = axis.clone().cross(Math.abs(axis.y) < .9 ? new THREE.Vector3(0,1,0) : new THREE.Vector3(0,0,1))
  normal.normalize()
  if (normal.dot(camera.position.clone().sub(center)) < 0) normal.negate()
  const fov = THREE.MathUtils.degToRad(camera.fov || 45)
  const limitingAngle = Math.min(fov / 2, Math.atan(Math.tan(fov / 2) * (camera.aspect || 1)))
  camera.position.copy(center).addScaledVector(normal, radius / Math.sin(limitingAngle) * 1.15)
  // Face the particle plane, keeping the screen upright even if it is horizontal.
  camera.up.copy(axis.clone().cross(normal).normalize())
  camera.near = Math.max(.01, radius / 1000); camera.far = Math.max(1000, radius * 30)
  if (camera.isOrthographicCamera) camera.zoom = Math.min((camera.right-camera.left), (camera.top-camera.bottom)) / (radius * 2.3)
  camera.updateProjectionMatrix(); controls.target.copy(center); camera.lookAt(center); controls.update()
}

export function initConnectivity({ store, scene, camera, controls, setMenuToggle, api }) {
  const menu = document.getElementById('menu-help-connectivity')
  const panel = document.createElement('section')
  panel.id = 'connectivity-panel'; panel.hidden = true; panel.setAttribute('aria-label', 'Nanoparticle connectivity')
  panel.innerHTML = `<div class="connectivity-heading"><strong>Connectivity</strong><button type="button" aria-label="Close connectivity">×</button></div>
    <p class="connectivity-status" role="status" aria-live="polite"></p>
    <label>Bundle-tree candidate <select aria-label="Connectivity candidate"></select></label>
    <label class="connectivity-path-toggle"><input type="checkbox" aria-label="Origami pathing preview"> Origami pathing preview</label>
    <div class="connectivity-path-controls" hidden><label>Uniform bundle size <select aria-label="Uniform bundle size"><option value="6">6HB · 12HB junctions</option><option value="12">12HB · 24HB junctions</option><option value="18">18HB · 36HB junctions</option><option value="24">24HB · 48HB junctions</option></select></label>
    <p class="connectivity-path-stats" role="status"></p>
    <p class="connectivity-note">Honeycomb duplex paths: teal / violet. Amber helices thicken the shared section before each split. No overhangs, scaffold crossovers or staples are included.</p><button type="button" class="connectivity-generate">Generate this origami…</button></div>
    <button type="button" class="connectivity-frame">Frame graph in 3D</button>
    <svg viewBox="0 0 350 255" role="img" aria-label="Proposed nanoparticle connectivity graph"></svg>
    <p class="connectivity-stats"></p><ul class="connectivity-warnings"></ul>
    <p class="connectivity-note">Gold: nanoparticles · white: shared-section splits. Colors show branch depth. The diagram is a 2D projection; the overlay follows 3D positions.</p>
    <p class="connectivity-note">Preview only: no DNA is added. HB counts describe bundle partitions, not routed junctions. Scaffold estimates exclude crossover, junction and attachment overhead. Routing, curvature and stability remain unvalidated.</p>`
  document.body.append(panel)
  const status = panel.querySelector('.connectivity-status'), select = panel.querySelector('select'), svg = panel.querySelector('svg')
  const pathToggle = panel.querySelector('[aria-label="Origami pathing preview"]'), bundleSize = panel.querySelector('[aria-label="Uniform bundle size"]')
  let enabled = false, overlay = null, pathOverlay = null, pathPreview = null, sites = [], result = null, signature = null, timer = null
  const clear = () => { disposeConnectivityOverlay(overlay); disposeConnectivityOverlay(pathOverlay); overlay = null; pathOverlay = null; pathPreview = null }
  function showCandidate() {
    clear()
    const candidate = result?.candidates[Number(select.value)]
    svg.hidden = !candidate
    panel.querySelector('.connectivity-stats').textContent = ''
    panel.querySelector('.connectivity-stats').hidden = pathToggle.checked
    for (let i=0; i<select.options.length; i++) {
      const c=result.candidates[i]
      select.options[i].textContent = `${i + 1} · Stem at ${c.rootLabel}${pathToggle.checked ? '' : ` · ~${c.estimatedNt} nt`}${c.warnings.length ? ' · check geometry' : ''}`
    }
    panel.querySelector('.connectivity-warnings').replaceChildren()
    panel.querySelector('.connectivity-generate').disabled = !candidate || !api
    pathToggle.disabled = !candidate
    panel.querySelector('.connectivity-path-controls').hidden = !pathToggle.checked
    panel.querySelector('.connectivity-path-stats').textContent = ''
    if (!candidate) { svg.replaceChildren(); return }
    overlay = createConnectivityOverlay(candidate); scene.add(overlay)
    panel.querySelector('.connectivity-stats').textContent = `${candidate.nodes.filter(n => n.kind === 'split').length} shared-section splits · ${Math.round(candidate.contourNm)} nm bundle paths · ~${candidate.estimatedNt.toLocaleString()} scaffold nt${candidate.budget ? ` (${candidate.budget} nt candidate budget)` : ''}`
    const warnings = [...candidate.warnings]
    if (pathToggle.checked) {
      pathPreview = buildOrigamiPathPreview(candidate, { hb: Number(bundleSize.value) })
      pathOverlay = createOrigamiPathOverlay(pathPreview); scene.add(pathOverlay)
      // Keep the graph in the diagram; its thick x-ray strokes would obscure
      // the individual helices at exactly the locations we want to inspect.
      overlay.visible = false
      panel.querySelector('.connectivity-path-stats').textContent = `${pathPreview.hb}HB on all arms and stems · ${pathPreview.junctionHB}HB at ${pathPreview.junctions.length} shared sections · ~${pathPreview.estimatedNt.toLocaleString()} nt in displayed helix paths.`
      warnings.push(...pathPreview.warnings)
    }
    drawConnectivityDiagram(svg, candidate, sites, pathPreview)
    for (const warning of [...new Set(warnings)]) { const li = document.createElement('li'); li.textContent = warning; panel.querySelector('.connectivity-warnings').append(li) }
  }
  panel.querySelector('.connectivity-generate').addEventListener('click', async () => {
    const candidate = result?.candidates[Number(select.value)]
    if (!candidate || !api) return
    const connectivityPlan = {
      nodes: candidate.nodes.map(({ id, kind, position, particleId }) => ({ id, kind, position, particleId })),
      edges: candidate.edges.map(({ id, source, target, controlPoints }) => ({ id, source, target, controlPoints })),
      uniform_hb: Number(bundleSize.value),
    }
    setEnabled(false)
    const { showGenerateDesign } = await import('./generate_design.js')
    showGenerateDesign({ api, store, connectivityPlan })
  })
  function refresh() {
    if (!enabled) return
    const state = store.getState()
    sites = nanoparticleSites(state.currentDesign)
    signature = JSON.stringify([state.currentDesign?.id, state.assemblyActive, sites])
    result = state.assemblyActive ? { candidates: [], message: 'Open a part to preview its nanoparticle connectivity.' } : discoverConnectivity(sites)
    status.textContent = result.message + (result.evaluated ? ` · ${result.evaluated} proposals evaluated` : '')
    select.replaceChildren()
    result.candidates.forEach((c, i) => {
      const option = document.createElement('option'); option.value = String(i)
      option.textContent = `${i + 1} · Stem at ${c.rootLabel} · ~${c.estimatedNt} nt${c.warnings.length ? ' · check geometry' : ''}`
      select.append(option)
    })
    select.disabled = !result.candidates.length
    panel.querySelector('.connectivity-frame').disabled = !result.candidates.length || !camera
    showCandidate()
  }
  function setEnabled(value) {
    enabled = value; panel.hidden = !value
    setMenuToggle?.('menu-help-connectivity', value)
    menu?.setAttribute('aria-pressed', String(value))
    if (value) refresh()
    else { clearTimeout(timer); clear() }
  }
  const toggle = () => setEnabled(!enabled)
  menu?.addEventListener('click', toggle)
  panel.querySelector('button').addEventListener('click', () => setEnabled(false))
  select.addEventListener('change', showCandidate)
  pathToggle.addEventListener('change', showCandidate)
  bundleSize.addEventListener('change', showCandidate)
  panel.querySelector('.connectivity-frame').addEventListener('click', () => frameConnectivity(result?.candidates[Number(select.value)], sites, camera, controls, pathPreview))
  const unsubscribe = store.subscribe(() => {
    if (!enabled) return
    const state = store.getState()
    const next = JSON.stringify([state.currentDesign?.id, state.assemblyActive, nanoparticleSites(state.currentDesign)])
    if (next === signature) return
    // Remove stale geometry immediately; debounce the bounded topology search while dragging.
    clear(); clearTimeout(timer); timer = setTimeout(refresh, 100)
  })
  setEnabled(false)
  return { setEnabled, dispose() { clearTimeout(timer); clear(); unsubscribe?.(); menu?.removeEventListener('click', toggle); panel.remove() } }
}
