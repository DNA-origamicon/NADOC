import { ANNOTATION_FONT_SIZES, ANNOTATION_FONTS } from './annotation_model.js'
import { zoomBaseEntries, buildZoomBaseExtras, zoomBackbonePairs } from './zoom_volume_bases.js'
import { copyZoomBox, zoomBoxBounds, entriesInZoomBox } from './zoom_volume_box.js'
import { createZoomLayerMotion, zoomMotionFrame, zoomLiveAtoms, zoomExactAtoms } from './zoom_volume_motion.js'
import { mdInsetAtoms } from './md_inset_atoms.js'
import './zoom_volume.css'
import * as THREE from 'three'
import { matchTargetEntries, describeTarget } from './annotation_targets.js'
import { buildZoomExternal } from './zoom_volume_external.js'
import { zoomContextBounds, nearbyZoomEntries, nearbyZoomExternalRefs, setZoomContextOpacity } from './zoom_volume_context.js'
import { buildZoomConnections } from './zoom_volume_connections.js'
import { zoomVolumeConnectors } from './zoom_volume_lines.js'
import { baseKey } from './base_ref.js'
import { initViewVolumeDisplays } from './view_volume_displays.js'
import { VIEW_VOLUME_REPRESENTATIONS, segmentsForKeys } from './view_volumes.js'
import { COLORING_LABELS, supportedColoringSet, coloringFallbackMode } from './coloring_modes.js'
import { eyeIcon, powerIcon } from './volume_panel.js'

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
  const byDomain = new Map(), remapped = new Map(), strandIds = new Set(geometry.map(n => n.strand_id))
  for (const n of geometry) {
    if (n.crossover_id != null || n.extension_id != null) continue
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
  }).filter(s => s.domains.length || strandIds.has(s.id))
  const helixIds = new Set(geometry.map(n => n.helix_id))
  return { geometry, keys: [...selected], design: { ...design, strands,
    helices: (design.helices ?? []).filter(h => helixIds.has(h.id)),
    cluster_transforms: (design.cluster_transforms ?? []).map(c => ({ ...c, domain_ids: c.domain_ids?.flatMap(d => (remapped.get(JSON.stringify([d.strand_id, d.domain_index])) ?? []).map(domain_index => ({ ...d, domain_index }))) })),
    crossovers: [], forced_ligations: [], protein_attachments: [], nanoparticles: [],
  } }
}

export function initZoomVolumeEntry({ getInsetRenderer, parent, id, name, position = 'tr', onDelete, onVisibilityChange = () => {}, onChange = () => {}, document, scene, canvas, store, api, designRenderer, assemblyRenderer, ensureAtoms, getAtomisticRenderer, getProteinGeometry, resolveBasePosition, getAssemblyCluster = () => null, getRenderCamera, addFrameCallback, removeFrameCallback }) {
  const section = document.createElement('div'); section.className = 'zoom-volume-row volume-entry'; section.dataset.zoomId = id
  section.innerHTML = `<div class="volume-entry-top">
      <input data-control="name" aria-label="Rename zoom volume" title="Inset title" placeholder="Inset title">
      <button data-control="enabled" type="button">${powerIcon}</button>
      <button data-control="box" type="button">${eyeIcon}</button>
      <button data-control="delete" type="button" title="Delete volume" aria-label="Delete zoom volume">×</button>
    </div>
    <div class="volume-entry-controls">
      <select data-control="representation" aria-label="Representation" title="Representation"></select>
      <input data-control="opacity" aria-label="Opacity" title="Opacity" type="range" min="0" max="1" step="0.05" value="1">
    </div>
    <select data-control="coloring" aria-label="Volume coloring scheme" title="Volume coloring scheme"></select>
    <button data-control="set" class="xover-mode-btn" type="button" title="Replace this volume's entities with the current selection">Use current selection</button>
    <div data-control="status" role="status">Select an element in the 3D view.</div>
    <details class="zoom-volume-options"><summary>Inset options</summary><div>
    <label>Font size <select data-control="title-size" aria-label="Title font size"></select></label>
    <label>Font style <select data-control="title-font" aria-label="Title font style"></select></label>
    <label><input data-control="with-structure" type="checkbox"> With structure</label>
    <label data-control="structure-controls" hidden>Other elements' transparency
      <span><input data-control="structure-transparency" aria-label="Other elements transparency" type="range" min="0" max="100" step="1" value="75"><output data-control="structure-value">75%</output></span>
    </label>
    <label>Inset position <select data-control="position"><option value="tr">Top right</option><option value="tl">Top left</option><option value="br">Bottom right</option><option value="bl">Bottom left</option></select></label>
    <label>Inset size <input data-control="size" type="range" min="160" max="500" value="280"></label>
    <label><input data-control="lines" type="checkbox" checked> Show zoom lines</label></div></details>`
  parent.append(section)
  const $ = key => section.querySelector(`[data-control="${key}"]`)
  $('name').value = name
  $('position').value = position
  for (const px of ANNOTATION_FONT_SIZES) $('title-size').add(new Option(`${px} px`, String(px)))
  $('title-size').value = '12'
  for (const family of ANNOTATION_FONTS) $('title-font').add(new Option(family === 'system-ui' ? 'System sans-serif' : family, family))
  let presentationVisible = null
  function setVisibility(key, visible) {
    const button = $(key); button.checked = visible
    button.setAttribute('aria-pressed', String(visible))
    button.title = key === 'enabled' ? (visible ? 'Hide inset' : 'Show inset') : (visible ? 'Hide volume outline' : 'Show volume outline')
    button.setAttribute('aria-label', button.title)
    onVisibilityChange()
  }
  for (const key of ['enabled', 'box']) {
    setVisibility(key, true)
    $(key).onclick = () => { setVisibility(key, !$(key).checked); onChange() }
  }
  $('delete').onclick = onDelete
  for (const [label, value] of VIEW_VOLUME_REPRESENTATIONS) $('representation').add(new Option(label, value))
  const colors = () => {
    const current = $('coloring').value || 'strand'
    const mode = coloringFallbackMode($('representation').value, current) ?? current
    $('coloring').replaceChildren()
    for (const value of supportedColoringSet($('representation').value)) $('coloring').add(new Option(COLORING_LABELS[value], value))
    $('coloring').value = mode
  }; colors()
  const host = document.createElement('div'); host.className = 'zoom-volume-inset'; host.dataset.zoomId = id
  host.style.cssText = 'position:fixed;z-index:20;border:2px solid #67c5ff;border-radius:6px;overflow:hidden;background:#171e28;display:none;'
  const title = document.createElement('div'); title.className = 'zoom-volume-title'; title.title = 'Drag to move inset'
  function updateTitle() {
    title.textContent = $('name').value
    title.style.fontSize = `${$('title-size').value || 12}px`
    title.style.fontFamily = $('title-font').value || 'system-ui'
    host.style.setProperty('--zoom-title-height', `${titleHeight()}px`)
  }
  function titleHeight() { return Math.max(26, Math.ceil(Number($('title-size').value || 12) * 1.25 + 8)) }
  $('title-size').onchange = $('title-font').onchange = updateTitle
  updateTitle()
  const image = document.createElement('canvas'); image.style.display = 'block'; image.setAttribute('aria-label', 'Zoom Volume: selected elements')
  const frozen = document.createElement('canvas'); frozen.className = 'zoom-volume-frozen'; frozen.hidden = true
  frozen.setAttribute('aria-hidden', 'true')
  const loadingOverlay = document.createElement('div'); loadingOverlay.className = 'zoom-volume-loading'; loadingOverlay.hidden = true
  loadingOverlay.setAttribute('role', 'status'); loadingOverlay.setAttribute('aria-label', 'Loading zoom volume')
  loadingOverlay.innerHTML = '<span class="zoom-volume-spinner" aria-hidden="true"></span><span>Loading…</span>'
  $('name').onchange = () => { $('name').value = $('name').value.trim() || 'Zoom Volume'; updateTitle() }
  host.setAttribute('aria-busy', 'false')
  host.append(title, image, frozen, loadingOverlay); (canvas.parentElement ?? document.body).append(host)
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:19;overflow:hidden'
  const lines = [0, 1].map(() => { const line = document.createElementNS(svg.namespaceURI, 'line'); line.setAttribute('stroke', '#67c5ff'); line.setAttribute('stroke-width', '1.5'); svg.append(line); return line })
  ;(canvas.parentElement ?? document.body).append(svg)
  const insetScene = new THREE.Scene(); insetScene.add(new THREE.AmbientLight(0xffffff, 2))
  const light = new THREE.DirectionalLight(0xffffff, 2); insetScene.add(light)
  const camera = new THREE.PerspectiveCamera(40, 1, .01, 10000)
  const zoomControls = document.createElement('div'); zoomControls.className = 'zoom-volume-zoom-controls'; zoomControls.dataset.zoomId = id
  zoomControls.setAttribute('role', 'group'); zoomControls.setAttribute('aria-label', 'Inset zoom')
  zoomControls.hidden = true
  let zoomStep = 0, pendingBuild = Promise.resolve()
  const zoomButtons = [1, -1].map(direction => {
    const button = document.createElement('button'); button.type = 'button'
    button.textContent = direction > 0 ? '+' : '−'
    button.setAttribute('aria-label', direction > 0 ? 'Zoom in inset' : 'Zoom out inset')
    button.title = button.getAttribute('aria-label')
    button.onclick = () => { zoomStep = Math.max(-8, Math.min(8, zoomStep + direction)); camera.zoom = 1.25 ** zoomStep; frame(); onChange() }
    zoomControls.append(button)
    return button
  })
  ;(canvas.parentElement ?? document.body).append(zoomControls)
  const bounds = new THREE.Box3(), externalBounds = new THREE.Box3(), displayedBounds = new THREE.Box3(), box = new THREE.Box3Helper(displayedBounds, 0x67c5ff)
  box.name = 'zoom-volume-selection-box'; box.visible = false; box.userData.helper = true; box.userData.setupOnly = true; box.raycast = () => {}; scene.add(box)
  let renderer = null, targets = [], displays = [], revision = 0, disposed = false, ready = false, customPosition = null
  let loading = false, hasFrozenImage = false, triangles = 0
  let volume = null
  let motionLayers = [], motionConnections = [], motionRevision = 0, appliedMotionRevision = -1
  let atomVersion = null
  let simulationActive = !!designRenderer.hasFemPositions?.()
  function syncPlaybackRepresentation() {
    // Axis cylinders describe the reference design, not bent trajectory poses.
    const cylinders = [...$('representation').options].find(o => o.value === 'cylinders')
    cylinders.disabled = simulationActive
    if (simulationActive && $('representation').value === 'cylinders') {
      $('representation').value = 'full'; colors()
      return true
    }
    return false
  }
  $('representation').title = 'Trajectory playback uses live nucleotide poses. For exact atom coordinates, use an atomistic main viewport; otherwise inset atoms follow rigid nucleotide poses. Surfaces use playback skinning. Reference-axis cylinders switch to Full during playback.'
  syncPlaybackRepresentation()
  const unsubscribeMotion = designRenderer.subscribeSimulation?.(() => {
    motionRevision++
    const next = !!designRenderer.hasFemPositions?.()
    const stopped = simulationActive && !next
    simulationActive = next
    const switched = syncPlaybackRepresentation()
    if ((stopped || switched) && targets.length) void rebuild()
  })
  let documentId = null, mode = null, abort = new AbortController()
  let motionExtraEntries = []
  let contextRoots = [], contextBaseCount = 0, contextObjectCount = 0, selectionConnectionCount = 0, contextConnectionCount = 0
  const contextOpacity = () => 1 - Number($('structure-transparency').value) / 100
  function updateContextOpacity() {
    $('structure-value').value = `${$('structure-transparency').value}%`
    for (const root of contextRoots) setZoomContextOpacity(root, contextOpacity())
  }
  function freezeInset() {
    // Retain this entry's last complete image while the shared renderer serves
    // other entries and the replacement representation builds.
    if (ready && renderer) {
      frozen.width = image.width; frozen.height = image.height
      frozen.getContext('2d').drawImage(image, 0, 0)
      hasFrozenImage = true; frozen.hidden = false
    }
    loading = true
    loadingOverlay.hidden = false; host.setAttribute('aria-busy', 'true')
  }
  // Atomistic insets ask Display MD for their residues' exact atoms.
  const insetOwner = Symbol(id)
  function registerInsetResidues() {
    const atomistic = ['ballstick', 'vdw', 'stick'].includes($('representation').value)
    mdInsetAtoms.setResidues(insetOwner, atomistic && !mode
      ? motionLayers.flatMap(layer => layer.geometry.map(n => baseKey(n, n.copy_k ?? 0))).filter(Boolean) : null)
  }
  function clear() {
    motionLayers = []; motionConnections = []; motionExtraEntries = []
    mdInsetAtoms.setResidues(insetOwner, null)
    loading = false; hasFrozenImage = false; frozen.hidden = true; loadingOverlay.hidden = true
    host.setAttribute('aria-busy', 'false'); displayedBounds.makeEmpty()
    abort.abort(); revision++; ready = false; targets = []; volume = null; bounds.makeEmpty()
    for (const d of displays) d.dispose(); displays = []; contextRoots = []; contextBaseCount = 0; contextObjectCount = 0; contextConnectionCount = 0; selectionConnectionCount = 0
    zoomStep = 0; camera.zoom = 1; zoomControls.hidden = true
    host.style.display = 'none'; svg.style.display = 'none'; box.visible = false
    $('status').textContent = 'Select an element in the 3D view.'
  }
  function setBox(value) {
    const next = copyZoomBox(value)
    if (!next) return false
    const state = store.getState()
    volume = next
    targets = state.assemblyActive
      ? (state.currentAssembly?.instances ?? []).map(i => ({ instanceId: i.id, refs: [] }))
      : [{ refs: [] }]
    documentId = state.assemblyActive ? state.currentAssembly?.id : state.currentDesign?.id
    mode = state.assemblyActive
    setVisibility('enabled', true)
    void rebuild(); onChange()
    return true
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
    if (!targets.length) { targets = previousTargets; $('status').textContent = 'Select an element first.'; return false }
    volume = null
    documentId = state.assemblyActive ? state.currentAssembly?.id : state.currentDesign?.id; mode = state.assemblyActive
    setVisibility('enabled', true)
    void rebuild(); onChange()
    return true
  }
  function rebuild() { pendingBuild = build(); return pendingBuild }
  async function settle() { let pending; do { pending = pendingBuild; await pending } while (pending !== pendingBuild); return !(presentationVisible ?? $('enabled').checked) || !targets.length || ready }
  async function build() {
    motionLayers = []; motionConnections = []; motionExtraEntries = []
    externalBounds.makeEmpty()
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
      async function buildDna(root, design, entries, instanceId, id, opacity, sourceEntries = entries) {
        if (!entries.length) return
        if (!instanceId) motionExtraEntries.push(...entries.filter(e => e.zoomExtra).map(e => ({ ...e, context: id === 'zoom-context' })))
        const extraDisplay = buildZoomBaseExtras(root, entries, $('representation').value, $('coloring').value, opacity, instanceId ? null : designRenderer, { ...state, currentDesign: design },
          id === 'zoom-context' ? sourceEntries.filter(e => selectedBySource.get(instanceId ?? 'design')?.keys.has(baseKey(e.nuc, e.nuc.copy_k ?? 0))) : [])
        if (extraDisplay) { displays.push(extraDisplay); if (!instanceId) motionConnections.push(extraDisplay) }
        const coarse = ['full', 'beads', 'cylinders'].includes($('representation').value)
        const subset = zoomSelectionSource(design, coarse ? entries.filter(e => !e.zoomExtra) : entries)
        if (!subset.geometry.length) return
        // Keep reference coordinates for reversible physical display updates.
        if (!instanceId) {
          const original = new Map(entries.map(e => [baseKey(e.nuc, e.nuc.copy_k ?? 0), e.nuc]))
          subset.geometry = subset.geometry.map(n => ({ ...n, backbone_position: n.is_flexible_segment || n.helix_id?.startsWith('__lnk__') ? n.backbone_position : original.get(baseKey(n, n.copy_k ?? 0)).backbone_position }))
        }
        const source = { ...state, assemblyActive: false, currentDesign: subset.design, currentGeometry: subset.geometry, currentHelixAxes: null, showReferenceGeometry: true, simulationTabActive: false }
        const display = initViewVolumeDisplays({ scene: root, store: { getState: () => source, subscribe: () => () => {} },
          api: { getRegionSurface: (segments, opts) => instanceId ? api.getInstanceRegionSurface(instanceId, segments, opts) : api.getRegionSurface(segments, opts) },
          ensureAtoms: instanceId ? () => api.getInstanceAtomisticGeometry(instanceId) : ensureAtoms,
          onError: error => { throw error } })
        displays.push({ dispose: () => { display.dispose(); root.removeFromParent() } })
        const keys = [...new Set(subset.geometry.map(n => `${n.helix_id}:${n.bp_index}`))]
        await display.update([{ id, representation: $('representation').value, coloring: $('coloring').value, opacity, keys, baseKeys: subset.keys, backbonePairs: zoomBackbonePairs(sourceEntries), segments: segmentsForKeys(keys) }])
        if (!instanceId && current === revision && !disposed) {
          motionLayers.push({ motion: createZoomLayerMotion(display, subset.geometry), geometry: subset.geometry, display, context: id === 'zoom-context' })
          appliedMotionRevision = -1
        }
      }
      for (const target of targets) {
        const data = target.instanceId ? assemblyRenderer.getInstanceBackboneEntries(target.instanceId) : null
        const design = target.instanceId ? assemblyRenderer.getInstanceDesign(target.instanceId) : state.currentDesign
        if (!design) continue
        const entries = target.instanceId ? zoomBaseEntries(design, data?.entries, data?.nucleotides) : zoomBaseEntries(design, designRenderer.getBackboneEntries(), state.currentGeometry ?? [], designRenderer, resolveBasePosition)
        const matched = volume ? entriesInZoomBox(entries, volume, data?.matrixWorld) : target.refs ? matchTargetEntries(target.refs, design, entries) : entries
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
        if (external && !external.bounds.isEmpty()) {
          externalBounds.union(data?.matrixWorld ? external.bounds.clone().applyMatrix4(data.matrixWorld) : external.bounds)
          bounds.union(externalBounds)
        }
        if (!matched.length) continue
        await buildDna(root, design, matched, target.instanceId, 'zoom', Number($('opacity').value), entries)
        if (disposed || current !== revision) return
      }
      if (!count && !externalCount) { hasFrozenImage = false; frozen.hidden = true; displayedBounds.makeEmpty(); $('status').textContent = 'The selected element is no longer available.'; return }
      // Own selected connections once per source, even when multiple targets share endpoints.
      for (const selected of selectedBySource.values()) {
        const root = new THREE.Group(); root.matrixAutoUpdate = false; root.matrix.copy(selected.matrix); insetScene.add(root)
        const connections = buildZoomConnections({ root, design: selected.design, entries: selected.entries.filter(e => !e.zoomExtra), selectedKeys: selected.keys,
          selectionOnly: true, separateExtraBases: true, representation: $('representation').value, coloring: $('coloring').value, state })
        displays.push({ dispose() { connections.dispose(); root.removeFromParent() } })
        if (!mode) motionConnections.push(connections)
        selectionConnectionCount += connections.count
        setZoomContextOpacity(connections.group, Number($('opacity').value))
        root.updateWorldMatrix(true, true)
        if (connections.count) bounds.union(new THREE.Box3().setFromObject(root))
      }
      if (volume) bounds.copy(zoomBoxBounds(volume))
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
          const entries = instanceId ? zoomBaseEntries(design, data?.entries, data?.nucleotides) : zoomBaseEntries(design, designRenderer.getBackboneEntries(), state.currentGeometry ?? [], designRenderer, resolveBasePosition)
          const nearby = nearbyZoomEntries(entries, selected?.keys ?? new Set(), neighborhood, matrix)
          const proteinData = design.protein_attachments?.length
            ? await (instanceId ? api.getInstanceProteinGeometry(instanceId) : getProteinGeometry()) : { atoms: [] }
          if (disposed || current !== revision) return
          const refs = selected?.whole ? [] : nearbyZoomExternalRefs(design, proteinData?.atoms, selected?.refs ?? [], neighborhood, matrix)
          const root = new THREE.Group(); root.name = 'zoom-volume-context'; root.matrixAutoUpdate = false; root.matrix.copy(matrix); insetScene.add(root)
          contextRoots.push(root)
          const connections = buildZoomConnections({ root, design, entries: entries.filter(e => !e.zoomExtra), selectedKeys: selected?.keys ?? new Set(), bounds: neighborhood, matrix,
            separateExtraBases: true, representation: $('representation').value, coloring: $('coloring').value, state })
          displays.push(connections); if (!mode) motionConnections.push(connections); contextConnectionCount += connections.count
          const owner = { layer: null, dispose() { this.layer?.dispose(); root.removeFromParent() } }; displays.push(owner)
          const external = await buildZoomExternal({ root, design, refs, proteinData: () => proteinData,
            representation: $('representation').value, coloring: $('coloring').value, opacity: contextOpacity(),
            getSurface: (segments, opts) => instanceId ? api.getInstanceRegionSurface(instanceId, segments, opts) : api.getRegionSurface(segments, opts), signal })
          if (disposed || current !== revision) { external?.dispose(); root.removeFromParent(); return }
          owner.layer = external; contextObjectCount += external?.count ?? 0
          await buildDna(root, design, nearby, instanceId, 'zoom-context', contextOpacity(), entries)
          if (disposed || current !== revision) return
          contextBaseCount += nearby.length
          setZoomContextOpacity(root, contextOpacity())
        }
      }
      if (volume) bounds.copy(zoomBoxBounds(volume))
      else bounds.expandByScalar(1.5)
      renderer ??= getInsetRenderer()
      ready = true
      registerInsetResidues()
      $('status').textContent = `${volume ? 'Submodel box' : targets[0]?.instanceId ? 'Assembly selection' : describeTarget(targets[0].refs, state.currentDesign)} · ${count} bases${externalCount ? ` · ${externalCount} attached objects` : ''}`
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
  title.onpointerup = title.onpointercancel = () => { drag = null; onChange() }
  function frame() {
    const visible = (ready || loading || hasFrozenImage) && (presentationVisible ?? $('enabled').checked) && canvas.getBoundingClientRect().width > 0
    host.style.display = visible ? 'block' : 'none'; box.visible = visible && !displayedBounds.isEmpty() && $('box').checked
    svg.style.display = visible && $('lines').checked ? 'block' : 'none'
    zoomControls.hidden = !visible
    if (!visible) return
    const rect = canvas.getBoundingClientRect(), size = Math.max(80, Math.min(Number($('size').value), rect.width - 64, rect.height - titleHeight() - 24))
    const corner = $('position').value
    const left = Math.max(rect.left + 8, Math.min(rect.right - size - 12, customPosition?.x ?? (corner.endsWith('r') ? rect.right - size - 12 : rect.left + 12)))
    const top = Math.max(rect.top + 8, Math.min(rect.bottom - size - titleHeight() - 14, customPosition?.y ?? (corner.startsWith('b') ? rect.bottom - size - titleHeight() - 14 : rect.top + 12)))
    host.style.left = `${left}px`; host.style.top = `${top}px`
    host.style.width = `${size}px`; host.style.height = `${size + titleHeight()}px`
    // Keep the pair outside the inset, on the side with more viewport room.
    const controlsLeft = left + size / 2 > rect.left + rect.width / 2 ? left - 40 : left + size + 10
    zoomControls.style.left = `${controlsLeft}px`; zoomControls.style.top = `${top + titleHeight() + 4}px`
    zoomButtons[0].disabled = zoomStep === 8
    zoomButtons[1].disabled = zoomStep === -8
    if (loading || !ready) { svg.style.display = 'none'; return }
    const currentAtomVersion = `${getAtomisticRenderer?.()?.positionVersion?.()}|${mdInsetAtoms.version()}`
    if ((motionLayers.length || motionExtraEntries.length) && (appliedMotionRevision !== motionRevision || currentAtomVersion !== atomVersion)) {
      const updates = designRenderer.getFemPositions?.()
      const live = [...designRenderer.getBackboneEntries(), ...motionExtraEntries.map(e => ({ ...e,
        pos: designRenderer.xoverResidueInfo?.(e.zoomExtra.target)?.centroid ?? e.pos }))]
      const atoms = updates?.length ? zoomExactAtoms(getAtomisticRenderer?.(), mdInsetAtoms.atoms()) : null
      if (!volume) bounds.copy(externalBounds)
      for (const layer of motionLayers) {
        const positions = zoomMotionFrame(layer.geometry, updates, live)
        layer.motion.apply(positions, atoms, !!updates?.length)
        if (!volume && !layer.context) for (const n of positions) bounds.expandByPoint(new THREE.Vector3(...n.backbone_position))
      }
      if (!volume) {
        for (const e of live) if (e.zoomExtra && !e.context) bounds.expandByPoint(e.pos)
        bounds.expandByScalar(1.5)
      }
      for (const connections of motionConnections) connections.update?.(live, updates)
      appliedMotionRevision = motionRevision
      atomVersion = currentAtomVersion
    }
    displayedBounds.copy(bounds)
    box.box = volume ? new THREE.Box3(new THREE.Vector3(...volume.min_corner), new THREE.Vector3(...volume.max_corner)) : displayedBounds
    box.quaternion.fromArray(volume?.rotation ?? [0, 0, 0, 1])
    const viewport = renderer.getSize(new THREE.Vector2()); if (viewport.x !== size) renderer.setSize(size, size)
    const main = getRenderCamera(); fitZoomCamera(camera, main.quaternion, bounds, 1)
    light.position.copy(camera.position); renderer.render(insetScene, camera)
    triangles = renderer.info.render.triangles
    if (image.width !== renderer.domElement.width || image.height !== renderer.domElement.height) {
      image.width = renderer.domElement.width; image.height = renderer.domElement.height
    }
    image.style.width = `${size}px`; image.style.height = `${size}px`
    image.getContext('2d').drawImage(renderer.domElement, 0, 0)
    const connectors = zoomVolumeConnectors(displayedBounds, main, rect, host.getBoundingClientRect())
    if (connectors.length !== 2) { svg.style.display = 'none'; return }
    const overlay = svg.getBoundingClientRect()
    lines.forEach((line, i) => {
      for (const [key, value] of Object.entries(connectors[i])) line.setAttribute(key, value - (key.startsWith('x') ? overlay.left : overlay.top))
    })
  }
  $('set').onclick = capture
  $('representation').onchange = () => { colors(); void rebuild() }
  $('coloring').onchange = $('opacity').onchange = () => { void rebuild() }
  $('with-structure').onchange = () => { $('structure-controls').hidden = !$('with-structure').checked; void rebuild() }
  $('structure-transparency').oninput = updateContextOpacity
  $('position').onchange = () => { customPosition = null }
  section.addEventListener('change', onChange)
  const unsubscribe = store.subscribe((n, p) => {
    if (!targets.length) return
    if (n.assemblyActive !== mode || (mode ? n.currentAssembly?.id : n.currentDesign?.id) !== documentId) { clear(); return }
    const changed = key => { const a = n[key], b = p[key]; return a !== b && Object.keys({ ...a, ...b }).some(k => k !== 'zoom_volumes' && a?.[k] !== b?.[k]) }
    if (n.currentGeometry !== p.currentGeometry || changed('currentDesign') || changed('currentAssembly')) void rebuild()
  })

  const settingKeys = ['enabled', 'box', 'representation', 'opacity', 'coloring', 'with-structure', 'structure-transparency', 'position', 'size', 'lines', 'title-size', 'title-font']
  const booleanKeys = new Set(['enabled', 'box', 'with-structure', 'lines'])
  function snapshot() {
    return { id, name: $('name').value, zoom_step: zoomStep, targets: structuredClone(targets), volume: volume ? structuredClone(volume) : null,
      settings: Object.fromEntries(settingKeys.map(key => [key, booleanKeys.has(key) ? $(key).checked : $(key).value])), custom_position: customPosition }
  }
  function restore(value) {
    targets = structuredClone(value.targets ?? []); volume = copyZoomBox(value.volume)
    const state = store.getState(); mode = state.assemblyActive; documentId = state[mode ? 'currentAssembly' : 'currentDesign']?.id
    $('name').value = value.name
    for (const key of settingKeys) {
      if (value.settings?.[key] === undefined) continue
      if (key === 'enabled' || key === 'box') setVisibility(key, value.settings[key])
      else { if (key === 'coloring') colors(); $(key)[booleanKeys.has(key) ? 'checked' : 'value'] = value.settings[key] }
    }
    updateTitle()
    zoomStep = Math.max(-8, Math.min(8, Math.round(Number(value.zoom_step) || 0))); camera.zoom = 1.25 ** zoomStep
    customPosition = value.custom_position ?? null
    $('structure-controls').hidden = !$('with-structure').checked; updateContextOpacity()
    void rebuild()
    return true
  }
  function draw(ctx, width, height, main = getRenderCamera()) {
    frame()
    if (!ready || !(presentationVisible ?? $('enabled').checked)) return
    const rect = canvas.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const scale = Math.min(width / rect.width, height / rect.height)
    const size = parseFloat(host.style.width) * scale, headerHeight = titleHeight() * scale
    const corner = $('position').value
    const x = customPosition ? (parseFloat(host.style.left) - rect.left) / rect.width * width : corner.endsWith('r') ? width - size - 12 * scale : 12 * scale
    const y = customPosition ? (parseFloat(host.style.top) - rect.top) / rect.height * height : corner.startsWith('b') ? height - size - headerHeight - 14 * scale : 12 * scale
    if ($('lines').checked) {
      const links = zoomVolumeConnectors(displayedBounds, main, { left: 0, top: 0, width, height, right: width, bottom: height }, { left: x, top: y, right: x + size, bottom: y + size + headerHeight, width: size, height: size + headerHeight })
      ctx.save(); ctx.strokeStyle = '#67c5ff'; ctx.lineWidth = 1.5 * scale
      for (const line of links) { ctx.beginPath(); ctx.moveTo(line.x1, line.y1); ctx.lineTo(line.x2, line.y2); ctx.stroke() }
      ctx.restore()
    }
    renderer.setSize(Math.max(1, Math.ceil(size)), Math.max(1, Math.ceil(size)))
    fitZoomCamera(camera, main.quaternion, bounds, 1); light.position.copy(camera.position); renderer.render(insetScene, camera)
    ctx.save(); ctx.fillStyle = '#243344'; ctx.fillRect(x, y, size, headerHeight)
    ctx.drawImage(renderer.domElement, x, y + headerHeight, size, size)
    ctx.strokeStyle = '#67c5ff'; ctx.lineWidth = 2 * scale; ctx.strokeRect(x, y, size, size + headerHeight)
    ctx.fillStyle = '#e5f4ff'; ctx.font = `${Number($('title-size').value || 12) * scale}px ${$('title-font').value || 'system-ui'}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText($('name').value, x + size / 2, y + headerHeight / 2, size - 16 * scale); ctx.restore()
  }
  addFrameCallback(frame)
  return { visible: () => host.style.display !== 'none', snapshot, restore, settle, draw, capture, setBox, clear, name: () => $('name').value, setPresentationVisible(value) { presentationVisible = value; frame() }, refreshAssembly() { if (!disposed && mode && targets.length) void rebuild() }, setVisibility, visibility: key => $(key).checked, debugAtoms: () => motionLayers.flatMap(l => [...l.display.entries.values()].flatMap(e => e.kind === 'atom' ? [...zoomLiveAtoms(e.renderer)] : [])), debug: () => ({ zoom: camera.zoom, ready, loading, hasFrozenImage, targets, volume: volume ? structuredClone(volume) : null, motionRevision, appliedMotionRevision, motionPositions: motionLayers.flatMap(l => [...l.display.entries.values()].flatMap(e => (e.cg?.backboneEntries ?? []).map(b => ({ key: baseKey(b.nuc, b.nuc.copy_k ?? 0), position: b.pos.toArray() })))), contextBaseCount, contextObjectCount, selectionConnectionCount, contextConnectionCount, contextOpacity: contextOpacity(), contextVisible: contextRoots.some(root => root.visible), bounds: { min: bounds.min.toArray(), max: bounds.max.toArray() }, orientation: camera.quaternion.toArray(), triangles }), dispose() { disposed = true; clear(); unsubscribe(); unsubscribeMotion?.(); removeFrameCallback(frame); host.remove(); zoomControls.remove(); svg.remove(); section.remove(); box.removeFromParent(); box.geometry.dispose(); box.material.dispose() } }
}
