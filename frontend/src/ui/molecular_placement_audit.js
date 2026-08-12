/**
 * Help ▸ Molecular Placement Audit — isolated four-panel A/B geometry review.
 *
 * The candidate design comes from a read-only backend route and is rendered only in
 * private mini-scenes. It never enters the app store, persistence, export, or simulation.
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

import { initAtomisticRenderer } from '../scene/atomistic_renderer.js'
import { computeAtomStrandColors } from '../scene/color_util.js'
import { buildCrossoverConnections } from '../scene/crossover_connections.js'
import { buildHelixObjects, buildStapleColorMap } from '../scene/helix_renderer.js'
import { docHeaders } from '../shared/doc_id.js'
import { isNewPositioningOn } from './new_positioning.js'
import './molecular_placement_audit.css'

const PANEL_DEFS = [
  { id: 'current', title: 'Current', note: 'Production geometry', representation: 'full' },
  { id: 'candidate', title: 'Candidate', note: 'Diagnostic baseline — not authorized', representation: 'full' },
  { id: 'difference', title: 'Difference', note: 'Current cyan · affected candidate magenta', representation: 'ballstick' },
  { id: 'defects', title: 'Piercings / clashes', note: 'Exact detector atoms · synchronized camera', representation: 'ballstick' },
]

export function filterAuditAtomData(data, serials) {
  const keep = serials instanceof Set ? serials : new Set(serials ?? [])
  const oldToNew = new Map()
  const atoms = []
  for (let row = 0; row < (data?.atoms ?? []).length; row++) {
    if (!keep.has(row)) continue
    oldToNew.set(row, atoms.length)
    atoms.push({ ...data.atoms[row], serial: atoms.length })
  }
  const bonds = []
  for (const [a, b] of data?.bonds ?? []) {
    if (oldToNew.has(a) && oldToNew.has(b)) bonds.push([oldToNew.get(a), oldToNew.get(b)])
  }
  return { atoms, bonds, element_meta: data?.element_meta ?? {} }
}

export function auditMetricRows(bundle) {
  const cur = bundle.current.diagnostics
  const cand = bundle.candidate.diagnostics
  const arrow = (a, b) => `${a} → ${b}`
  return [
    ['Provider', bundle.provider.label, ''],
    ['Displaced atoms', bundle.displacement.n_displaced, bundle.displacement.n_displaced ? '' : 'good'],
    ['Max displacement', `${bundle.displacement.max_nm.toFixed(3)} nm`, ''],
    ['Ring piercings', arrow(cur.piercing.n_pierced, cand.piercing.n_pierced), cand.piercing.n_pierced ? 'bad' : 'good'],
    ['Clashes', arrow(cur.n_clashes, cand.n_clashes), cand.n_clashes ? 'bad' : 'good'],
    ['Max bond', arrow(cur.bonds.max_length_nm.toFixed(3), `${cand.bonds.max_length_nm.toFixed(3)} nm`), cand.bonds.n_overstretched ? 'bad' : 'good'],
  ]
}

export function auditDefectRows(bundle) {
  const rows = []
  for (const side of ['current', 'candidate']) {
    const label = side === 'current' ? 'Current' : 'Candidate'
    const diagnostics = bundle[side].diagnostics
    for (const hit of diagnostics.piercing?.pierced ?? []) {
      rows.push({
        side,
        kind: 'piercing',
        text: `${label} PIERCING · ${hit.bond} through ${hit.ring}`,
      })
    }
    for (const hit of diagnostics.clashes ?? []) {
      const atoms = hit.serials.map(serial => bundle[side].atoms[serial])
      const names = atoms.map((atom, i) => {
        if (!atom) return `atom #${hit.serials[i]}`
        const residue = atom.chain_id != null && atom.seq_num != null
          ? `${atom.chain_id}${atom.seq_num}`
          : `atom #${hit.serials[i]}`
        return `${residue}:${atom.name}`
      })
      rows.push({
        side,
        kind: 'clash',
        text: `${label} CLASH · ${names.join(' ↔ ')} · ${Number(hit.distance_nm).toFixed(3)} nm`,
      })
    }
  }
  return rows
}

export function auditStrandColorMap(bundle, colorState = {}) {
  const design = bundle.current_design
  const persisted = Object.fromEntries((design.strands ?? [])
    .filter(strand => /^#[0-9a-fA-F]{6}$/.test(strand.color ?? ''))
    .map(strand => [strand.id, strand.color]))
  const staplePalette = buildStapleColorMap(bundle.nucleotides, design)
  return computeAtomStrandColors({
    currentDesign: design,
    coloringMode: 'strand',
    strandColors: { ...persisted, ...(colorState.strandColors ?? {}) },
    strandGroups: colorState.strandGroups ?? [],
    loopStrandIds: colorState.loopStrandIds ?? [],
  }, staplePalette)
}

function _disposeTree(root) {
  root?.traverse?.(obj => {
    if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose?.()
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const mat of mats) mat?.dispose?.()
  })
  root?.removeFromParent?.()
}

function _tint(root, color, opacity) {
  const instanceColor = new THREE.Color(color)
  root.traverse(obj => {
    if (!obj.material) return
    if (obj.isInstancedMesh) {
      for (let i = 0; i < obj.count; i++) obj.setColorAt(i, instanceColor)
      if (obj.instanceColor) obj.instanceColor.needsUpdate = true
    }
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const mat of mats) {
      mat.color?.setHex?.(color)
      mat.opacity = opacity
      mat.transparent = opacity < 1
      mat.depthWrite = opacity >= 0.99
    }
  })
}

function _axesMap(rows) {
  return Object.fromEntries((rows ?? []).map(row => [row.helix_id, row]))
}

function _buildFullLayer(scene, bundle, design, { serials = null } = {}) {
  const geometry = bundle.nucleotides
  const customColors = Object.fromEntries(bundle.strand_colors)
  const affectedIds = new Set((serials ?? [])
    .map(i => bundle.current.atoms[i]?.crossover_id).filter(Boolean))
  if (serials) {
    const filtered = {
      ...design,
      crossovers: (design.crossovers ?? []).filter(xo => affectedIds.has(xo.id)),
      forced_ligations: (design.forced_ligations ?? []).filter(fl => affectedIds.has(fl.id)),
    }
    const colorMap = buildStapleColorMap(geometry, filtered)
    const xovers = buildCrossoverConnections(filtered, geometry, colorMap, customColors)
    if (xovers) scene.add(xovers.group)
    return { root: xovers?.group ?? new THREE.Group(), dispose: () => _disposeTree(xovers?.group) }
  }

  const ctrl = buildHelixObjects(
    geometry, design, scene, customColors, [], _axesMap(bundle.helix_axes), 'full',
  )
  ctrl.setMode('normal')
  const colorMap = buildStapleColorMap(geometry, design)
  const xovers = buildCrossoverConnections(design, geometry, colorMap, customColors)
  if (xovers) ctrl.root.add(xovers.group)
  return { root: ctrl.root, dispose: () => _disposeTree(ctrl.root) }
}

function _buildBallstickLayer(scene, data, strandColors, serials = null) {
  const host = new THREE.Group()
  scene.add(host)
  const renderer = initAtomisticRenderer(host)
  renderer.setMode('ballstick')
  renderer.update(serials ? filterAuditAtomData(data, serials) : data)
  renderer.setColorMode('strand', strandColors)
  return {
    root: host,
    dispose() { renderer.dispose(); host.removeFromParent() },
  }
}

function _cylinderBetween(a, b, radius, material) {
  const start = new THREE.Vector3(...a)
  const end = new THREE.Vector3(...b)
  const delta = end.clone().sub(start)
  const length = delta.length()
  if (length < 1e-10) return null
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, length, 10), material)
  mesh.position.copy(start).add(end).multiplyScalar(0.5)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
  return mesh
}

function _addPiercingMarkers(root, data, diagnostics, color = 0xff3355) {
  const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.82, depthTest: false })
  const lineMat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95, depthTest: false })
  for (const hit of diagnostics?.piercing?.pierced ?? []) {
    const [a, b] = hit.bond_serials.map(i => data.atoms[i]).map(x => [x.x, x.y, x.z])
    const cylinder = _cylinderBetween(a, b, 0.045, mat)
    if (cylinder) { cylinder.renderOrder = 20; root.add(cylinder) }
    const ring = hit.ring_serials.map(i => data.atoms[i]).map(x => new THREE.Vector3(x.x, x.y, x.z))
    const loop = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring), lineMat)
    loop.renderOrder = 21
    root.add(loop)
  }
}

function _addClashMarkers(root, data, diagnostics, color = 0xffd33d) {
  const sphereGeometry = new THREE.SphereGeometry(0.105, 14, 10)
  const sphereMaterial = new THREE.MeshBasicMaterial({
    color, wireframe: true, transparent: true, opacity: 0.98, depthTest: false,
  })
  const linkMaterial = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: 0.9, depthTest: false,
  })
  for (const hit of diagnostics?.clashes ?? []) {
    const atoms = hit.serials.map(serial => data.atoms[serial])
    if (atoms.some(atom => !atom)) continue
    for (const atom of atoms) {
      const marker = new THREE.Mesh(sphereGeometry, sphereMaterial)
      marker.position.set(atom.x, atom.y, atom.z)
      marker.renderOrder = 24
      root.add(marker)
    }
    const a = atoms[0], b = atoms[1]
    const link = _cylinderBetween([a.x, a.y, a.z], [b.x, b.y, b.z], 0.012, linkMaterial)
    if (link) { link.renderOrder = 23; root.add(link) }
  }
}

function _addDisplacements(root, vectors) {
  if (!vectors?.length) return
  const points = []
  for (const row of vectors) points.push(...row.from, ...row.to)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(points, 3))
  const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
    color: 0xffd33d, transparent: true, opacity: 0.95, depthTest: false,
  }))
  lines.renderOrder = 22
  root.add(lines)
}

export function copyAuditCameraState(source, target) {
  target.camera.position.copy(source.camera.position)
  target.camera.quaternion.copy(source.camera.quaternion)
  target.camera.up.copy(source.camera.up)
  target.camera.near = source.camera.near
  target.camera.far = source.camera.far
  target.camera.zoom = source.camera.zoom
  target.controls.target.copy(source.controls.target)
  target.camera.updateProjectionMatrix()
  target.controls.update()
}

function _boundsFromData(data, serials = null) {
  const keep = serials ? new Set(serials) : null
  const box = new THREE.Box3()
  for (let i = 0; i < (data?.atoms ?? []).length; i++) {
    if (keep && !keep.has(i)) continue
    const a = data.atoms[i]
    box.expandByPoint(new THREE.Vector3(a.x, a.y, a.z))
  }
  return box
}

function _panelBounds(bundle, panelId) {
  if (panelId !== 'defects') return _boundsFromData(bundle.current)
  const box = _boundsFromData(bundle.current, bundle.defect_atom_serials.current)
  box.union(_boundsFromData(bundle.candidate, bundle.defect_atom_serials.candidate))
  return box
}

function _fitCamera(camera, controls, box) {
  if (box.isEmpty()) return
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  const radius = Math.max(size.length() * 0.5, 0.8)
  controls.target.copy(center)
  camera.position.copy(center).add(new THREE.Vector3(radius * 1.35, radius * 0.9, radius * 1.8))
  camera.near = Math.max(radius / 1000, 0.001)
  camera.far = Math.max(radius * 50, 100)
  camera.updateProjectionMatrix()
  controls.update()
}

export function createAuditPanelViewer(host, panelId, bundle, initialRepresentation = 'ballstick') {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(0x0d1117, 1)
  renderer.shadowMap.enabled = true
  host.appendChild(renderer.domElement)

  const scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x263241, 1.2))
  const key = new THREE.DirectionalLight(0xffffff, 1.8)
  key.position.set(4, 7, 6)
  key.castShadow = true
  scene.add(key)
  const camera = new THREE.PerspectiveCamera(42, 1, 0.001, 10000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.12

  let representation = initialRepresentation
  let layers = []
  let alive = true
  let raf = null
  const markerRoot = new THREE.Group()
  scene.add(markerRoot)

  function clear() {
    for (const layer of layers) layer.dispose()
    layers = []
    while (markerRoot.children.length) _disposeTree(markerRoot.children[0])
  }

  function addLayer(which, { ghost = false, serials = null } = {}) {
    const design = bundle[`${which}_design`]
    const data = bundle[which]
    const layer = representation === 'full'
      ? _buildFullLayer(scene, bundle, design, { serials })
      : _buildBallstickLayer(scene, data, bundle.strand_colors, serials)
    if (ghost) _tint(layer.root, 0x2f81f7, 0.42)
    else if (panelId === 'difference') _tint(layer.root, 0xff4da6, 0.9)
    else if (panelId === 'defects') {
      _tint(layer.root, which === 'current' ? 0x2f81f7 : 0xff4da6, 0.38)
    }
    layers.push(layer)
  }

  function rebuild(next = representation) {
    representation = next
    clear()
    if (panelId === 'current') {
      addLayer('current')
      _addPiercingMarkers(markerRoot, bundle.current, bundle.current.diagnostics)
      _addClashMarkers(markerRoot, bundle.current, bundle.current.diagnostics)
    } else if (panelId === 'candidate') {
      addLayer('candidate')
      _addPiercingMarkers(markerRoot, bundle.candidate, bundle.candidate.diagnostics)
      _addClashMarkers(markerRoot, bundle.candidate, bundle.candidate.diagnostics)
    } else if (panelId === 'difference') {
      addLayer('current', { ghost: true })
      // The whole-structure Difference panel supplies context from Current and
      // overlays only affected Candidate atoms.
      addLayer('candidate', { serials: bundle.affected_atom_serials })
      _addPiercingMarkers(markerRoot, bundle.current, bundle.current.diagnostics, 0x2f81f7)
      _addPiercingMarkers(markerRoot, bundle.candidate, bundle.candidate.diagnostics, 0xff3355)
      _addClashMarkers(markerRoot, bundle.current, bundle.current.diagnostics, 0x2f81f7)
      _addClashMarkers(markerRoot, bundle.candidate, bundle.candidate.diagnostics, 0xff3355)
      _addDisplacements(markerRoot, bundle.displacement.vectors)
    } else {
      const currentSerials = bundle.defect_atom_serials.current
      const candidateSerials = bundle.defect_atom_serials.candidate
      if (currentSerials.length) addLayer('current', { serials: currentSerials })
      if (candidateSerials.length) addLayer('candidate', { serials: candidateSerials })
      _addPiercingMarkers(markerRoot, bundle.current, bundle.current.diagnostics, 0x2f81f7)
      _addPiercingMarkers(markerRoot, bundle.candidate, bundle.candidate.diagnostics, 0xff3355)
      _addClashMarkers(markerRoot, bundle.current, bundle.current.diagnostics, 0x2f81f7)
      _addClashMarkers(markerRoot, bundle.candidate, bundle.candidate.diagnostics, 0xff3355)
    }
  }

  function resize() {
    const width = Math.max(host.clientWidth, 2)
    const height = Math.max(host.clientHeight, 2)
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(host)
  resize()
  rebuild()
  _fitCamera(camera, controls, _panelBounds(bundle, panelId))

  function loop() {
    if (!alive) return
    controls.update()
    renderer.render(scene, camera)
    raf = requestAnimationFrame(loop)
  }
  loop()

  return {
    camera,
    controls,
    setRepresentation: rebuild,
    fit() {
      _fitCamera(camera, controls, _panelBounds(bundle, panelId))
    },
    dispose() {
      alive = false
      cancelAnimationFrame(raf)
      observer.disconnect()
      clear()
      controls.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}

function _modalMarkup() {
  const modal = document.createElement('div')
  modal.className = 'mpa-modal'
  modal.id = 'molecular-placement-audit'
  modal.innerHTML = `
    <div class="mpa-header">
      <div class="mpa-title">Molecular Placement Audit</div>
      <div class="mpa-subtitle"><span class="mpa-warning">Read-only diagnostic.</span>
        Candidate geometry cannot be saved, exported, or simulated.</div>
      <button class="mpa-reset" type="button">Reset views</button>
      <button class="mpa-close" type="button" aria-label="Close molecular placement audit">Close</button>
    </div>
    <div class="mpa-metrics"></div>
    <div class="mpa-grid"></div>`
  return modal
}

export function initMolecularPlacementAudit({
  setMenuToggle = () => {},
  fetchAudit = async () => {
    const measured = isNewPositioningOn() ? 'true' : 'false'
    const response = await fetch(
      `/api/design/molecular-placement-audit?measured_positioning=${measured}`,
      { headers: docHeaders() },
    )
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      throw new Error(detail?.detail ?? `Audit request failed (${response.status})`)
    }
    return response.json()
  },
  viewerFactory = createAuditPanelViewer,
  getColorState = () => ({}),
} = {}) {
  const menu = document.getElementById('menu-help-molecular-placement-audit')
  const modal = _modalMarkup()
  document.body.appendChild(modal)
  const grid = modal.querySelector('.mpa-grid')
  const metrics = modal.querySelector('.mpa-metrics')
  let viewers = []
  let open = false
  let disposed = false
  let generation = 0
  let syncing = false

  function disposeViewers() {
    for (const viewer of viewers) viewer.dispose?.()
    viewers = []
    grid.innerHTML = ''
  }

  function close() {
    generation++
    open = false
    modal.classList.remove('visible')
    setMenuToggle('menu-help-molecular-placement-audit', false)
    disposeViewers()
  }

  function syncFrom(source) {
    if (syncing) return
    syncing = true
    for (const target of viewers) if (target !== source) copyAuditCameraState(source, target)
    syncing = false
  }

  async function show() {
    if (disposed) return
    if (open) { close(); return }
    open = true
    const mine = ++generation
    modal.classList.add('visible')
    setMenuToggle('menu-help-molecular-placement-audit', true)
    metrics.innerHTML = ''
    grid.innerHTML = '<div class="mpa-loading">Building current and diagnostic candidate structures…</div>'
    try {
      const bundle = await fetchAudit()
      if (!open || mine !== generation) return
      bundle.strand_colors = auditStrandColorMap(bundle, getColorState())
      grid.innerHTML = ''
      for (const def of PANEL_DEFS) {
        const panel = document.createElement('section')
        panel.className = 'mpa-panel'
        panel.dataset.panel = def.id
        panel.innerHTML = `<div class="mpa-panel-head">
          <span class="mpa-panel-title">${def.title}</span>
          <span class="mpa-panel-note">${def.note}</span>
          <select class="mpa-representation" aria-label="${def.title} representation">
            <option value="full" ${def.representation === 'full' ? 'selected' : ''}>Full</option>
            <option value="ballstick" ${def.representation === 'ballstick' ? 'selected' : ''}>Ball and Stick</option>
          </select></div><div class="mpa-canvas-host"></div>`
        grid.appendChild(panel)
        const viewer = viewerFactory(
          panel.querySelector('.mpa-canvas-host'), def.id, bundle, def.representation,
        )
        if (def.id === 'defects') {
          const status = document.createElement('div')
          status.className = 'mpa-defect-status'
          const rows = auditDefectRows(bundle)
          if (!rows.length) {
            status.classList.add('clean')
            status.textContent = 'No ring piercing or heavy-atom clash detected in either model.'
          } else {
            for (const row of rows.slice(0, 4)) {
              const line = document.createElement('div')
              line.className = `mpa-defect-row ${row.kind}`
              line.textContent = row.text
              status.appendChild(line)
            }
            if (rows.length > 4) {
              const more = document.createElement('div')
              more.textContent = `+ ${rows.length - 4} additional detector hits`
              status.appendChild(more)
            }
          }
          panel.appendChild(status)
        }
        panel.querySelector('.mpa-representation').addEventListener('change', event => {
          viewer.setRepresentation(event.target.value)
        })
        viewers.push(viewer)
      }
      for (const viewer of viewers) {
        viewer.controls?.addEventListener?.('change', () => syncFrom(viewer))
      }
      for (const viewer of viewers.slice(1)) copyAuditCameraState(viewers[0], viewer)
      metrics.innerHTML = auditMetricRows(bundle).map(([label, value, cls]) =>
        `<div class="mpa-metric"><div class="mpa-metric-label">${label}</div>` +
        `<div class="mpa-metric-value ${cls}">${value}</div></div>`).join('')
      modal.dataset.provider = bundle.provider.id
      modal.dataset.affectedAtoms = String(bundle.affected_atom_serials.length)
    } catch (error) {
      if (!open || mine !== generation) return
      grid.innerHTML = ''
      const errorNode = document.createElement('div')
      errorNode.className = 'mpa-error'
      errorNode.textContent = error instanceof Error ? error.message : String(error)
      grid.appendChild(errorNode)
    }
  }

  const onReset = () => {
    if (!viewers.length) return
    viewers[0].fit?.()
    for (const viewer of viewers.slice(1)) copyAuditCameraState(viewers[0], viewer)
  }
  const onKeydown = event => { if (open && event.key === 'Escape') close() }
  menu?.addEventListener('click', show)
  modal.querySelector('.mpa-close').addEventListener('click', close)
  modal.querySelector('.mpa-reset').addEventListener('click', onReset)
  window.addEventListener('keydown', onKeydown)

  return {
    show,
    close,
    isOpen: () => open,
    element: modal,
    dispose() {
      if (disposed) return
      close()
      disposed = true
      menu?.removeEventListener('click', show)
      window.removeEventListener('keydown', onKeydown)
      modal.remove()
    },
  }
}
