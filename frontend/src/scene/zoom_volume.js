import './zoom_volume.css'
import * as THREE from 'three'
import { matchTargetEntries, describeTarget } from './annotation_targets.js'
import { buildZoomExternal } from './zoom_volume_external.js'
import { zoomContextBounds, nearbyZoomEntries, nearbyZoomExternalRefs, setZoomContextOpacity } from './zoom_volume_context.js'
import { buildZoomConnections } from './zoom_volume_connections.js'
import { zoomVolumeConnectors } from './zoom_volume_lines.js'
import { baseKey } from './base_ref.js'
import { initViewVolumeDisplays } from './view_volume_displays.js'
import { VIEW_VOLUME_REPRESENTATIONS, segmentsForKeys, volumeBackboneEntries } from './view_volumes.js'
import { COLORING_LABELS, supportedColoringSet, coloringFallbackMode } from './coloring_modes.js'
import { getSectionCollapsed, setSectionCollapsed } from '../ui/section_collapse_state.js'

/** Tight camera-space fit, independent of the main camera's pan and zoom. */
export function fitZoomCamera(camera, orientation, bounds, aspect) {
  camera.quaternion.copy(orientation)
  camera.aspect = aspect
  const center = bounds.getCenter(new THREE.Vector3())
  const inverse = orientation.clone().invert()
  const tanY = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
  const tanX = tanY * aspect
  let distance = 0, depth = 0
  for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
    const p = new THREE.Vector3(x, y, z).sub(center).applyQuaternion(inverse)
    distance = Math.max(distance, p.z + Math.max(Math.abs(p.x) / tanX, Math.abs(p.y) / tanY) * 1.12)
    depth = Math.max(depth, Math.abs(p.z))
  }
  distance = Math.max(distance, .1)
  camera.position.copy(center).add(new THREE.Vector3(0, 0, distance).applyQuaternion(orientation))
  camera.near = Math.max(.001, (distance - depth) * .1)
  camera.far = Math.max(10, distance + depth * 2)
  camera.updateProjectionMatrix(); camera.updateMatrixWorld()
}

/** Trim topology as well as geometry: cylinder builders consume domain extents. */
export function zoomSelectionSource(design, entries) {
  const geometry = entries.map(e => ({ ...e.nuc, backbone_position: e.pos.toArray() }))
  const selected = new Set(geometry.map(n => baseKey(n, n.copy_k ?? 0)))
  const byDomain = new Map(), remapped = new Map()
  for (const n of geometry) {
    const key = JSON.stringify([n.strand_id, n.domain_index])
    if (!byDomain.has(key)) byDomain.set(key, [])
    byDomain.get(key).push(n)
  }
  const strands = (design.strands ?? []).map(strand => {
    const domains = []
    strand.domains?.forEach((domain, index) => {
      const bases = byDomain.get(JSON.stringify([strand.id, index])) ?? []
      const indices = []
      const reverse = domain.direction === 'REVERSE' || domain.start_bp > domain.end_bp
      const segments = segmentsForKeys(bases.map(n => `${n.helix_id}:${n.bp_index}`))
      // Skips split a domain into occupied runs; retain its 5′→3′ run order.
      if (reverse) segments.reverse()
      for (const segment of segments) {
        const domainIndex = domains.length; indices.push(domainIndex)
        domains.push({ ...domain, start_bp: reverse ? segment.bp_end : segment.bp_start, end_bp: reverse ? segment.bp_start : segment.bp_end })
        for (const n of bases) if (n.bp_index >= segment.bp_start && n.bp_index <= segment.bp_end) n.domain_index = domainIndex
      }
      remapped.set(JSON.stringify([strand.id, index]), indices)
    })
    return { ...strand, domains }
  }).filter(s => s.domains.length)
  const helixIds = new Set(geometry.map(n => n.helix_id))
  return { geometry, keys: [...selected], design: { ...design, strands,
    helices: (design.helices ?? []).filter(h => helixIds.has(h.id)),
    cluster_transforms: (design.cluster_transforms ?? []).map(c => ({ ...c, domain_ids: c.domain_ids?.flatMap(d => (remapped.get(JSON.stringify([d.strand_id, d.domain_index])) ?? []).map(domain_index => ({ ...d, domain_index }))) })),
    crossovers: [], forced_ligations: [], protein_attachments: [], nanoparticles: [],
  } }
}

export function initZoomVolume({ document, scene, canvas, store, api, designRenderer, assemblyRenderer, ensureAtoms, getProteinGeometry, getAssemblyCluster = () => null, getRenderCamera, addFrameCallback, removeFrameCallback }) {
  const pane = document.getElementById('right-tab-content-visualization')
  if (!pane) return null
  const section = document.createElement('div'); section.id = 'zoom-volume-section'; section.className = 'panel-section ox-card'
  section.innerHTML = `<h2><button id="zoom-volume-heading" type="button" style="all:unset;cursor:pointer;width:100%"><span class="section-arrow">▼</span> Zoom Volume</button></h2>
    <div id="zoom-volume-body" style="display:grid;gap:8px">
    <div style="display:flex;gap:6px"><button id="zoom-volume-set" class="xover-mode-btn" type="button">Use current selection</button><button id="zoom-volume-clear" class="xover-mode-btn" type="button">Clear</button></div>
    <div id="zoom-volume-status" role="status">Select an element in the 3D view.</div>
    <label>Representation <select id="zoom-volume-representation"></select></label>
    <label>Coloring <select id="zoom-volume-coloring"></select></label>
    <label>Opacity <input id="zoom-volume-opacity" type="range" min="0.1" max="1" step="0.05" value="1"></label>
    <label><input id="zoom-volume-with-structure" type="checkbox"> With structure</label>
    <label id="zoom-volume-structure-controls" hidden>Other elements' transparency
      <span><input id="zoom-volume-structure-transparency" aria-label="Other elements transparency" type="range" min="0" max="100" step="1" value="75"><output id="zoom-volume-structure-value">75%</output></span>
    </label>
    <label>Inset position <select id="zoom-volume-position"><option value="tr">Top right</option><option value="tl">Top left</option><option value="br">Bottom right</option><option value="bl">Bottom left</option></select></label>
    <label>Inset size <input id="zoom-volume-size" type="range" min="160" max="500" value="280"></label>
    <label><input id="zoom-volume-enabled" type="checkbox" checked> Show inset</label>
    <label><input id="zoom-volume-box" type="checkbox" checked> Show selection box</label>
    <label><input id="zoom-volume-lines" type="checkbox" checked> Show zoom lines</label></div>`
  pane.append(section)
  const $ = id => section.querySelector(`#zoom-volume-${id}`)
  let collapsed = getSectionCollapsed('visualization', section.id, false)
  const collapse = () => { $('body').hidden = collapsed; $('body').style.display = collapsed ? 'none' : 'grid'; $('heading').setAttribute('aria-expanded', String(!collapsed)); $('heading').querySelector('span').classList.toggle('is-collapsed', collapsed) }
  $('heading').onclick = () => { collapsed = !collapsed; collapse(); setSectionCollapsed('visualization', section.id, collapsed) }; collapse()
  for (const [label, value] of VIEW_VOLUME_REPRESENTATIONS) $('representation').add(new Option(label, value))
  const colors = () => {
    const current = $('coloring').value || 'strand'
    const mode = coloringFallbackMode($('representation').value, current) ?? current
    $('coloring').replaceChildren()
    for (const value of supportedColoringSet($('representation').value)) $('coloring').add(new Option(COLORING_LABELS[value], value))
    $('coloring').value = mode
  }; colors()
  const host = document.createElement('div'); host.id = 'zoom-volume-inset'
  host.style.cssText = 'position:fixed;z-index:20;border:2px solid #67c5ff;border-radius:6px;overflow:hidden;background:#171e28;display:none;'
  const title = document.createElement('div'); title.textContent = 'Zoom Volume · drag to move'
  title.style.cssText = 'height:26px;line-height:26px;padding:0 8px;cursor:move;color:#e5f4ff;background:#243344;touch-action:none;font-size:12px'
  const frozen = document.createElement('canvas'); frozen.id = 'zoom-volume-frozen'; frozen.hidden = true
  frozen.setAttribute('aria-hidden', 'true')
  const loadingOverlay = document.createElement('div'); loadingOverlay.id = 'zoom-volume-loading'; loadingOverlay.hidden = true
  loadingOverlay.setAttribute('role', 'status'); loadingOverlay.setAttribute('aria-label', 'Loading zoom volume')
  loadingOverlay.innerHTML = '<span class="zoom-volume-spinner" aria-hidden="true"></span><span>Loading…</span>'
  host.setAttribute('aria-busy', 'false')
  host.append(title, frozen, loadingOverlay); document.body.append(host)
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:19;overflow:hidden'
  const lines = [0, 1].map(() => { const line = document.createElementNS(svg.namespaceURI, 'line'); line.setAttribute('stroke', '#67c5ff'); line.setAttribute('stroke-width', '1.5'); svg.append(line); return line })
  document.body.append(svg)
  const insetScene = new THREE.Scene(); insetScene.add(new THREE.AmbientLight(0xffffff, 2))
  const light = new THREE.DirectionalLight(0xffffff, 2); insetScene.add(light)
  const camera = new THREE.PerspectiveCamera(40, 1, .01, 10000)
  const bounds = new THREE.Box3(), displayedBounds = new THREE.Box3(), box = new THREE.Box3Helper(displayedBounds, 0x67c5ff)
  box.name = 'zoom-volume-selection-box'; box.visible = false; box.userData.helper = true; box.userData.setupOnly = true; box.raycast = () => {}; scene.add(box)
  let renderer = null, targets = [], displays = [], revision = 0, disposed = false, ready = false, customPosition = null
  let loading = false, hasFrozenImage = false
  let documentId = null, mode = null, abort = new AbortController()
  let contextRoots = [], contextBaseCount = 0, contextObjectCount = 0, selectionConnectionCount = 0, contextConnectionCount = 0
  const contextOpacity = () => 1 - Number($('structure-transparency').value) / 100
  function updateContextOpacity() {
    $('structure-value').value = `${$('structure-transparency').value}%`
    for (const root of contextRoots) setZoomContextOpacity(root, contextOpacity())
  }
  function freezeInset() {
    // WebGL's default drawing buffer may already be discarded. Redraw the last
    // complete scene before copying it; never capture a partially built scene.
    if (ready && renderer) {
      renderer.render(insetScene, camera)
      frozen.width = renderer.domElement.width; frozen.height = renderer.domElement.height
      frozen.getContext('2d').drawImage(renderer.domElement, 0, 0)
      hasFrozenImage = true; frozen.hidden = false
    }
    loading = true
    loadingOverlay.hidden = false; host.setAttribute('aria-busy', 'true')
  }
  function clear() {
    loading = false; hasFrozenImage = false; frozen.hidden = true; loadingOverlay.hidden = true
    host.setAttribute('aria-busy', 'false'); displayedBounds.makeEmpty()
    abort.abort(); revision++; ready = false; targets = []; bounds.makeEmpty()
    for (const d of displays) d.dispose(); displays = []; contextRoots = []; contextBaseCount = 0; contextObjectCount = 0; contextConnectionCount = 0; selectionConnectionCount = 0
    host.style.display = 'none'; svg.style.display = 'none'; box.visible = false
    $('status').textContent = 'Select an element in the 3D view.'
  }
  function capture() {
    const previousTargets = targets
    const state = store.getState()
    if (state.assemblyActive) {
      const ids = new Set(state.multiSelectedInstanceIds ?? []); if (state.activeInstanceId) ids.add(state.activeInstanceId)
      const seen = new Set(), group = id => { if (seen.has(id)) return; seen.add(id); const g = state.currentAssembly?.groups?.find(g => g.id === id); g?.instance_ids?.forEach(id => ids.add(id)); g?.subgroup_ids?.forEach(group) }
      if (state.activeGroupId) group(state.activeGroupId)
      const cluster = getAssemblyCluster()
      targets = state.assemblyOverhangSelection?.length ? state.assemblyOverhangSelection.map(o => ({ instanceId: o.instanceId, refs: [{ kind: 'overhang', id: o.overhangId }] })) : cluster && ids.has(cluster.instanceId) ? [{ instanceId: cluster.instanceId, refs: [{ kind: 'cluster', id: cluster.clusterId }] }] : [...ids].map(instanceId => ({ instanceId, refs: null }))
    } else targets = state.selection?.items?.length ? [{ refs: structuredClone(state.selection.items) }] : state.activeClusterId ? [{ refs: [{ kind: 'cluster', id: state.activeClusterId }] }] : []
    if (!targets.length) { targets = previousTargets; $('status').textContent = 'Select an element first.'; return }
    documentId = state.assemblyActive ? state.currentAssembly?.id : state.currentDesign?.id; mode = state.assemblyActive
    $('enabled').checked = true
    void rebuild()
  }
  async function rebuild() {
    abort.abort(); abort = new AbortController()
    const signal = abort.signal
    if (!targets.length) return
    freezeInset()
    const current = ++revision; ready = false
    for (const d of displays) d.dispose(); displays = []; contextRoots = []; contextBaseCount = 0; contextObjectCount = 0; contextConnectionCount = 0; selectionConnectionCount = 0; bounds.makeEmpty()
    $('status').textContent = 'Building zoom volume…'
    try {
      frame()
      // Let the browser paint the frozen image and spinner before synchronous
      // mesh construction or a cached atomistic response occupies the main thread.
      await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)))
      if (disposed || current !== revision) return
      const state = store.getState()
      let count = 0, externalCount = 0
      const selectedBySource = new Map()
      async function buildDna(root, design, entries, instanceId, id, opacity) {
        if (!entries.length) return
        const subset = zoomSelectionSource(design, entries)
        const source = { ...state, assemblyActive: false, currentDesign: subset.design, currentGeometry: subset.geometry, currentHelixAxes: null, showReferenceGeometry: true, simulationTabActive: false }
        const display = initViewVolumeDisplays({ scene: root, store: { getState: () => source, subscribe: () => () => {} },
          api: { getRegionSurface: (segments, opts) => instanceId ? api.getInstanceRegionSurface(instanceId, segments, opts) : api.getRegionSurface(segments, opts) },
          ensureAtoms: instanceId ? () => api.getInstanceAtomisticGeometry(instanceId) : ensureAtoms,
          onError: error => { throw error } })
        displays.push({ dispose: () => { display.dispose(); root.removeFromParent() } })
        const keys = [...new Set(subset.geometry.map(n => `${n.helix_id}:${n.bp_index}`))]
        await display.update([{ id, representation: $('representation').value, coloring: $('coloring').value, opacity, keys, baseKeys: subset.keys, segments: segmentsForKeys(keys) }])
      }
      for (const target of targets) {
        const data = target.instanceId ? assemblyRenderer.getInstanceBackboneEntries(target.instanceId) : null
        const design = target.instanceId ? assemblyRenderer.getInstanceDesign(target.instanceId) : state.currentDesign
        if (!design) continue
        const entries = target.instanceId ? volumeBackboneEntries(data?.entries, data?.nucleotides) : volumeBackboneEntries(designRenderer.getBackboneEntries(), state.currentGeometry ?? [])
        const matched = target.refs ? matchTargetEntries(target.refs, design, entries) : entries
        const sourceId = target.instanceId ?? 'design'
        if (!selectedBySource.has(sourceId)) selectedBySource.set(sourceId, { keys: new Set(), refs: [], whole: false })
        const selected = selectedBySource.get(sourceId)
        Object.assign(selected, { entries, design, matrix: data?.matrixWorld ?? new THREE.Matrix4() })
        for (const e of matched) selected.keys.add(baseKey(e.nuc, e.nuc.copy_k ?? 0))
        selected.refs.push(...(target.refs ?? [])); selected.whole ||= target.refs == null
        count += matched.length
        const root = new THREE.Group(); insetScene.add(root)
        if (data?.matrixWorld) { root.matrixAutoUpdate = false; root.matrix.copy(data.matrixWorld) }
        for (const e of matched) bounds.expandByPoint(data?.matrixWorld ? e.pos.clone().applyMatrix4(data.matrixWorld) : e.pos)
        const getSurface = (segments, opts) => target.instanceId ? api.getInstanceRegionSurface(target.instanceId, segments, opts) : api.getRegionSurface(segments, opts)
        // Register the owner before any asynchronous build, so clearing a pending selection removes it.
        const externalOwner = { layer: null, dispose() { this.layer?.dispose(); root.removeFromParent() } }
        displays.push(externalOwner)
        const external = await buildZoomExternal({ root, design, refs: target.refs,
          proteinData: target.instanceId ? () => api.getInstanceProteinGeometry(target.instanceId) : getProteinGeometry,
          representation: $('representation').value, coloring: $('coloring').value, opacity: Number($('opacity').value), getSurface, signal })
        if (disposed || current !== revision) { external?.dispose(); root.removeFromParent(); return }
        externalOwner.layer = external
        externalCount += external?.count ?? 0
        if (external && !external.bounds.isEmpty()) bounds.union(data?.matrixWorld ? external.bounds.clone().applyMatrix4(data.matrixWorld) : external.bounds)
        if (!matched.length) continue
        await buildDna(root, design, matched, target.instanceId, 'zoom', Number($('opacity').value))
        if (disposed || current !== revision) return
      }
      if (!count && !externalCount) { hasFrozenImage = false; frozen.hidden = true; displayedBounds.makeEmpty(); $('status').textContent = 'The selected element is no longer available.'; return }
      // Own selected connections once per source, even when multiple targets share endpoints.
      for (const selected of selectedBySource.values()) {
        const root = new THREE.Group(); root.matrixAutoUpdate = false; root.matrix.copy(selected.matrix); insetScene.add(root)
        const connections = buildZoomConnections({ root, design: selected.design, entries: selected.entries, selectedKeys: selected.keys,
          selectionOnly: true, representation: $('representation').value, coloring: $('coloring').value, state })
        displays.push({ dispose() { connections.dispose(); root.removeFromParent() } })
        selectionConnectionCount += connections.count
        setZoomContextOpacity(connections.group, Number($('opacity').value))
        root.updateWorldMatrix(true, true)
        if (connections.count) bounds.union(new THREE.Box3().setFromObject(root))
      }
      // Build context in a separate pass, after the complete selection bounds are known.
      // Include neighboring assembly instances as well as neighbors in the selected part.
      if ($('with-structure').checked) {
        const neighborhood = zoomContextBounds(bounds)
        const instanceIds = state.assemblyActive ? (state.currentAssembly?.instances ?? []).map(i => i.id) : [null]
        for (const instanceId of instanceIds) {
          const selected = selectedBySource.get(instanceId ?? 'design')
          const data = instanceId ? assemblyRenderer.getInstanceBackboneEntries(instanceId) : null
          const design = instanceId ? assemblyRenderer.getInstanceDesign(instanceId) : state.currentDesign
          if (!design) continue
          const matrix = data?.matrixWorld ?? new THREE.Matrix4()
          const entries = instanceId ? volumeBackboneEntries(data?.entries, data?.nucleotides) : volumeBackboneEntries(designRenderer.getBackboneEntries(), state.currentGeometry ?? [])
          const nearby = nearbyZoomEntries(entries, selected?.keys ?? new Set(), neighborhood, matrix)
          const proteinData = design.protein_attachments?.length
            ? await (instanceId ? api.getInstanceProteinGeometry(instanceId) : getProteinGeometry()) : { atoms: [] }
          if (disposed || current !== revision) return
          const refs = selected?.whole ? [] : nearbyZoomExternalRefs(design, proteinData?.atoms, selected?.refs ?? [], neighborhood, matrix)
          const root = new THREE.Group(); root.name = 'zoom-volume-context'; root.matrixAutoUpdate = false; root.matrix.copy(matrix); insetScene.add(root)
          contextRoots.push(root)
          const connections = buildZoomConnections({ root, design, entries, selectedKeys: selected?.keys ?? new Set(), bounds: neighborhood, matrix,
            representation: $('representation').value, coloring: $('coloring').value, state })
          displays.push(connections); contextConnectionCount += connections.count
          const owner = { layer: null, dispose() { this.layer?.dispose(); root.removeFromParent() } }; displays.push(owner)
          const external = await buildZoomExternal({ root, design, refs, proteinData: () => proteinData,
            representation: $('representation').value, coloring: $('coloring').value, opacity: contextOpacity(),
            getSurface: (segments, opts) => instanceId ? api.getInstanceRegionSurface(instanceId, segments, opts) : api.getRegionSurface(segments, opts), signal })
          if (disposed || current !== revision) { external?.dispose(); root.removeFromParent(); return }
          owner.layer = external; contextObjectCount += external?.count ?? 0
          await buildDna(root, design, nearby, instanceId, 'zoom-context', contextOpacity())
          if (disposed || current !== revision) return
          contextBaseCount += nearby.length
          setZoomContextOpacity(root, contextOpacity())
        }
      }
      bounds.expandByScalar(1.5)
      if (!renderer) {
        renderer = new THREE.WebGLRenderer({ antialias: true }); renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.setClearColor(0x171e28)
        renderer.domElement.setAttribute('aria-label', 'Zoom Volume: selected elements'); renderer.domElement.style.display = 'block'; host.append(renderer.domElement)
      }
      ready = true
      $('status').textContent = `${targets[0]?.instanceId ? 'Assembly selection' : describeTarget(targets[0].refs, state.currentDesign)} · ${count} bases${externalCount ? ` · ${externalCount} attached objects` : ''}`
    } catch (error) { if (current === revision && !disposed) { $('status').textContent = `Zoom Volume failed: ${error.message}`; ready = false } }
    finally {
      // Superseded requests must not hide the spinner for the current build.
      if (current === revision && !disposed) {
        loading = false; loadingOverlay.hidden = true; host.setAttribute('aria-busy', 'false')
        if (ready) { frame(); hasFrozenImage = false; frozen.hidden = true }
      }
    }
  }
  let drag = null
  title.onpointerdown = event => { drag = { x: event.clientX, y: event.clientY, left: host.offsetLeft, top: host.offsetTop }; title.setPointerCapture(event.pointerId); event.preventDefault() }
  title.onpointermove = event => { if (drag) customPosition = { x: drag.left + event.clientX - drag.x, y: drag.top + event.clientY - drag.y } }
  title.onpointerup = title.onpointercancel = () => { drag = null }
  function frame() {
    const visible = (ready || loading || hasFrozenImage) && $('enabled').checked && canvas.getBoundingClientRect().width > 0
    host.style.display = visible ? 'block' : 'none'; box.visible = visible && !displayedBounds.isEmpty() && $('box').checked
    svg.style.display = visible && $('lines').checked ? 'block' : 'none'
    if (!visible) return
    const rect = canvas.getBoundingClientRect(), size = Math.max(80, Math.min(Number($('size').value), rect.width - 24, rect.height - 50))
    const corner = $('position').value
    const left = Math.max(rect.left + 8, Math.min(rect.right - size - 12, customPosition?.x ?? (corner.endsWith('r') ? rect.right - size - 12 : rect.left + 12)))
    const top = Math.max(rect.top + 8, Math.min(rect.bottom - size - 40, customPosition?.y ?? (corner.startsWith('b') ? rect.bottom - size - 40 : rect.top + 12)))
    host.style.left = `${left}px`; host.style.top = `${top}px`
    host.style.width = `${size}px`; host.style.height = `${size + 26}px`
    if (loading || !ready) { svg.style.display = 'none'; return }
    displayedBounds.copy(bounds)
    const viewport = renderer.getSize(new THREE.Vector2()); if (viewport.x !== size) renderer.setSize(size, size)
    const main = getRenderCamera(); fitZoomCamera(camera, main.quaternion, bounds, 1)
    light.position.copy(camera.position); renderer.render(insetScene, camera)
    const connectors = zoomVolumeConnectors(displayedBounds, main, rect, host.getBoundingClientRect())
    if (connectors.length !== 2) { svg.style.display = 'none'; return }
    const overlay = svg.getBoundingClientRect()
    lines.forEach((line, i) => {
      for (const [key, value] of Object.entries(connectors[i])) line.setAttribute(key, value - (key.startsWith('x') ? overlay.left : overlay.top))
    })
  }
  $('set').onclick = capture; $('clear').onclick = clear
  $('representation').onchange = () => { colors(); void rebuild() }
  $('coloring').onchange = $('opacity').onchange = () => { void rebuild() }
  $('with-structure').onchange = () => { $('structure-controls').hidden = !$('with-structure').checked; void rebuild() }
  $('structure-transparency').oninput = updateContextOpacity
  $('position').onchange = () => { customPosition = null }
  const unsubscribe = store.subscribe((n, p) => {
    if (!targets.length) return
    if (n.assemblyActive !== mode || (mode ? n.currentAssembly?.id : n.currentDesign?.id) !== documentId) { clear(); return }
    if (n.currentGeometry !== p.currentGeometry || n.currentDesign !== p.currentDesign || n.currentAssembly !== p.currentAssembly) void rebuild()
  })
  assemblyRenderer?.onRebuildComplete?.(() => { if (!disposed && mode && targets.length) void rebuild() })
  addFrameCallback(frame)
  return { capture, clear, debug: () => ({ ready, loading, hasFrozenImage, targets, contextBaseCount, contextObjectCount, selectionConnectionCount, contextConnectionCount, contextOpacity: contextOpacity(), contextVisible: contextRoots.some(root => root.visible), bounds: { min: bounds.min.toArray(), max: bounds.max.toArray() }, orientation: camera.quaternion.toArray(), triangles: renderer?.info.render.triangles ?? 0 }), dispose() { disposed = true; clear(); unsubscribe(); removeFrameCallback(frame); renderer?.dispose(); host.remove(); svg.remove(); section.remove(); box.removeFromParent(); box.geometry.dispose(); box.material.dispose() } }
}
