import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { getSectionCollapsed, setSectionCollapsed } from '../ui/section_collapse_state.js'

export const VIEW_VOLUME_REPRESENTATIONS = [
  ['Full', 'full'], ['Beads', 'beads'], ['Cylinders', 'cylinders'],
  ['Surface', 'surface'], ['VDW', 'vdw'], ['Ball & Stick', 'ballstick'], ['Stick', 'stick'],
]

export function normalizeBounds(a, b) {
  return {
    min_corner: [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.min(a[2], b[2])],
    max_corner: [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.max(a[2], b[2])],
  }
}

export function pointInVolume(point, volume) {
  const min = new THREE.Vector3(...volume.min_corner), max = new THREE.Vector3(...volume.max_corner)
  const center = min.clone().add(max).multiplyScalar(.5)
  const local = new THREE.Vector3(...point).sub(center)
    .applyQuaternion(new THREE.Quaternion(...(volume.rotation ?? [0, 0, 0, 1])).invert())
  const half = max.clone().sub(min).multiplyScalar(.5)
  if (volume.shape === 'hexagonal') {
    // Hexagonal prisms run along local Z, matching NADOC helix axes. The stored
    // X/Y span is the circumdiameter, preserving the bounds persistence contract as
    // boxes. This flat-top test is the intersection of three pairs of slabs.
    const radius = Math.min(half.x, half.y)
    const x = Math.abs(local.x), y = Math.abs(local.y)
    return Math.abs(local.z) <= half.z
      && x <= radius
      && y <= Math.sqrt(3) * radius / 2
      && Math.sqrt(3) * x + y <= Math.sqrt(3) * radius
  }
  return Math.abs(local.x) <= half.x && Math.abs(local.y) <= half.y && Math.abs(local.z) <= half.z
}

/** Resolve spatial membership without collapsing overlaps. */
export function resolveViewVolumeLayers(volumes, points) {
  return (volumes ?? []).map(volume => ({
    volume,
    keys: new Set((points ?? []).filter(item => pointInVolume(item.position, volume)).map(item => item.key)),
  }))
}

/** Disabled volumes remain editable/outlined but contribute no representation layer. */
export function activeViewVolumes(volumes) {
  return (volumes ?? []).filter(volume => volume.enabled !== false)
}

export function segmentsForKeys(keys) {
  const byHelix = new Map()
  for (const key of keys ?? []) {
    const split = key.lastIndexOf(':')
    if (split < 0) continue
    const helixId = key.slice(0, split), bp = Number(key.slice(split + 1))
    if (!Number.isInteger(bp)) continue
    if (!byHelix.has(helixId)) byHelix.set(helixId, new Set())
    byHelix.get(helixId).add(bp)
  }
  const segments = []
  for (const [helix_id, values] of byHelix) {
    const sorted = [...values].sort((a, b) => a - b)
    let start = sorted[0], previous = sorted[0]
    for (const bp of sorted.slice(1)) {
      if (bp === previous + 1) { previous = bp; continue }
      segments.push({ helix_id, bp_start: start, bp_end: previous })
      start = previous = bp
    }
    if (start !== undefined) segments.push({ helix_id, bp_start: start, bp_end: previous })
  }
  return segments
}

function defaultBounds(entries) {
  const box = new THREE.Box3()
  for (const entry of entries) box.expandByPoint(entry.pos)
  if (box.isEmpty()) return { min_corner: [-5, -5, -5], max_corner: [5, 5, 5] }
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3()).multiplyScalar(0.28)
  size.x = Math.max(size.x, 2); size.y = Math.max(size.y, 2); size.z = Math.max(size.z, 2)
  return { min_corner: center.clone().sub(size).toArray(), max_corner: center.clone().add(size).toArray() }
}

/** One pending preview per paint. New input cancels the older revision. */
export function createLatestFrameScheduler(task, {
  requestFrame = callback => requestAnimationFrame(callback),
  cancelFrame = id => cancelAnimationFrame(id),
} = {}) {
  let frame = null, controller = null, revision = 0, latest = null
  function schedule(payload) {
    latest = payload; revision += 1
    controller?.abort('superseded')
    controller = new AbortController()
    if (frame !== null) cancelFrame(frame)
    const runRevision = revision, signal = controller.signal
    frame = requestFrame(async () => {
      frame = null
      if (signal.aborted || runRevision !== revision) return
      await task(latest, { signal, revision: runRevision })
    })
    return runRevision
  }
  function abort(reason = 'aborted') {
    revision += 1; controller?.abort(reason)
    if (frame !== null) cancelFrame(frame)
    frame = null
  }
  return { schedule, abort, revision: () => revision }
}

export function initViewVolumes({ document, scene, camera, canvas, controls, store, api, designRenderer }) {
  const pane = document.getElementById('right-tab-content-visualization')
  if (!pane) return null
  const section = document.createElement('div')
  section.id = 'view-volumes-section'; section.className = 'panel-section ox-card'
  const boxIcon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16"><rect x="3" y="3" width="12" height="12" rx="1" fill="none" stroke="currentColor" stroke-width="2"/><path d="M18 13v8M14 17h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
  const hexIcon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16"><path d="M8 3h7l4 6-4 6H8L4 9z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M18 14v8M14 18h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
  const eyeIcon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="2.5" fill="currentColor"/></svg>'
  const powerIcon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16"><path d="M12 2v9M7 5.5a8 8 0 1 0 10 0" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>'
  section.innerHTML = `<h2 id="view-volume-heading" aria-expanded="true" style="display:flex;align-items:center;justify-content:space-between;cursor:pointer"><span style="display:inline-flex;align-items:center;gap:7px"><span class="section-arrow">▼</span><span>View Volumes</span><span id="view-volume-busy" class="nadoc-spinner" role="status" aria-label="View volume representation loading" title="Building view volume representation…" style="display:none"></span></span><span style="display:inline-flex;gap:4px"><button id="view-volume-enable-all" type="button" title="Disable all volume representations" aria-label="Disable all volume representations" aria-pressed="true" style="width:28px;height:26px;display:grid;place-items:center">${powerIcon}</button><button id="view-volume-toggle-all" type="button" title="Hide all volume outlines" aria-label="Hide all volume outlines" aria-pressed="true" style="width:28px;height:26px;display:grid;place-items:center">${eyeIcon}</button><button id="view-volume-add-box" type="button" title="Add square view volume" aria-label="Add square view volume" style="width:28px;height:26px;display:grid;place-items:center">${boxIcon}</button><button id="view-volume-add-hexagonal" type="button" title="Add hexagonal view volume" aria-label="Add hexagonal view volume" style="width:28px;height:26px;display:grid;place-items:center">${hexIcon}</button></span></h2><div id="view-volume-body"><div class="view-volume-tool-row" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;margin-bottom:7px"><button type="button" data-volume-tool="translate" class="xover-mode-btn active" title="Move the selected volume without changing its shape (Tab)">Move</button><button type="button" data-volume-tool="scale" class="xover-mode-btn" title="Resize the selected volume about its center (Tab)">Resize</button><button type="button" data-volume-tool="rotate" class="xover-mode-btn" title="Rotate the selected volume (Tab)">Rotate</button></div><div id="view-volume-list" style="max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:6px"></div></div>`
  pane.append(section)
  const list = section.querySelector('#view-volume-list')
  const heading = section.querySelector('#view-volume-heading'), body = section.querySelector('#view-volume-body')
  const collapseArrow = heading.querySelector('.section-arrow')
  let collapsed = getSectionCollapsed('visualization', 'view-volumes-section', false)
  function applyCollapsed() {
    body.hidden = collapsed
    heading.setAttribute('aria-expanded', String(!collapsed))
    collapseArrow.classList.toggle('is-collapsed', collapsed)
  }
  heading.addEventListener('click', () => {
    collapsed = !collapsed; applyCollapsed()
    setSectionCollapsed('visualization', 'view-volumes-section', collapsed)
  })
  for (const button of heading.querySelectorAll('button')) button.addEventListener('click', event => event.stopPropagation())
  applyCollapsed()
  const root = new THREE.Group(); root.name = 'view-volumes'; scene.add(root)
  const visualById = new Map(), handles = [], edgeTargets = []
  const transform = new TransformControls(camera, canvas)
  transform.setMode('translate'); transform.setSpace('world'); transform.setSize(0.8)
  // TransformControls has no API for disabling only its planar scale picker.
  // Keep references so hex resize can fold XZ into the disabled XYZ group;
  // this removes it from both drawing and raycasting while retaining X and Z.
  const hexDisabledScaleHandles = [
    ...transform._gizmo.gizmo.scale.children,
    ...transform._gizmo.picker.scale.children,
  ].filter(handle => handle.name === 'XZ')
  scene.add(transform.getHelper())
  let selectedId = null, hoveredId = null, draftVolumes = null, transformStart = null, dragStartScale = null, draggingHexagonal = false
  const timing = { events: [], counters: { previewRequested: 0, previewApplied: 0, previewAborted: 0, commits: 0, persisted: 0 }, last: {} }
  const note = (type, detail = {}) => {
    const item = { type, at: performance.now(), ...detail }
    timing.events.push(item); if (timing.events.length > 300) timing.events.shift()
    performance.mark?.(`nadoc:view-volume:${type}`, { detail })
    return item
  }
  const busyIndicator = section.querySelector('#view-volume-busy')
  const busyKinds = new Set()
  const onStage = event => {
    const detail = event.detail ?? {}, stage = detail.stage ?? 'renderer-stage'
    note(stage, detail)
    if (!detail.viewVolume) return
    if (stage === 'atom-scheduled') busyKinds.add('atom')
    if (stage === 'surface-scheduled') busyKinds.add('surface')
    if (['atom-applied', 'atom-cleared', 'atom-failed'].includes(stage)) busyKinds.delete('atom')
    if (['surface-applied', 'surface-cleared', 'surface-failed', 'surface-request-aborted'].includes(stage)) busyKinds.delete('surface')
    busyIndicator.style.display = busyKinds.size ? 'inline-block' : 'none'
    busyIndicator.setAttribute('aria-busy', busyKinds.size ? 'true' : 'false')
  }
  window.addEventListener('nadoc:view-volume-stage', onStage)

  const volumes = () => draftVolumes ?? store.getState().currentDesign?.view_volumes ?? []
  const entries = () => designRenderer.getBackboneEntries().filter(entry => entry?.nuc && entry?.pos)
  function points() {
    return entries().map(entry => ({ key: `${entry.nuc.helix_id}:${entry.nuc.bp_index}`, position: entry.pos.toArray() }))
  }
  function computeLayers(sourceVolumes = volumes()) {
    const started = performance.now(), sourcePoints = points()
    const layers = resolveViewVolumeLayers(activeViewVolumes(sourceVolumes), sourcePoints).map(layer => ({
      id: layer.volume.id, name: layer.volume.name, representation: layer.volume.representation,
      opacity: layer.volume.opacity, keys: [...layer.keys], segments: segmentsForKeys(layer.keys),
    }))
    timing.last.membershipMs = performance.now() - started
    timing.last.pointCount = sourcePoints.length; timing.last.layerCount = layers.length
    return layers
  }
  function applyLayers(layers, revision) {
    const started = performance.now()
    designRenderer.applyViewVolumeLayers?.(layers)
    window.dispatchEvent(new CustomEvent('nadoc:view-volume-layers', { detail: { layers, revision } }))
    timing.last.rendererApplyMs = performance.now() - started
    note('renderer-applied', { revision, durationMs: timing.last.rendererApplyMs })
  }
  let representationTimer = null, pendingRepresentation = null
  function scheduleRepresentation(layers, revision) {
    pendingRepresentation = { layers, revision }
    if (representationTimer !== null) clearTimeout(representationTimer)
    representationTimer = setTimeout(() => {
      representationTimer = null
      const pending = pendingRepresentation; pendingRepresentation = null
      if (pending) applyLayers(pending.layers, pending.revision)
    }, 120)
  }
  const previewScheduler = createLatestFrameScheduler((sourceVolumes, { signal, revision }) => {
    const layers = computeLayers(sourceVolumes)
    if (signal.aborted) { timing.counters.previewAborted += 1; return }
    timing.counters.previewApplied += 1
    note('preview-applied', { revision, membershipMs: timing.last.membershipMs })
    scheduleRepresentation(layers, revision)
  })
  function requestPreview(sourceVolumes = volumes()) {
    timing.counters.previewRequested += 1
    const revision = previewScheduler.schedule(sourceVolumes.map(volume => ({ ...volume })))
    note('preview-requested', { revision })
  }
  let saveQueue = Promise.resolve(), saveGeneration = 0
  function save(next) {
    // Update immediately so rapid rename/representation/opacity gestures compose
    // against the latest UI state, then serialize persistence to prevent an older
    // response from overwriting a newer edit.
    const generation = ++saveGeneration
    store.setState({ currentDesign: { ...store.getState().currentDesign, view_volumes: next } })
    saveQueue = saveQueue.then(async () => {
      const started = performance.now(), response = await api.saveViewVolumes(next)
      timing.last.persistMs = performance.now() - started; timing.counters.persisted += 1
      note('persisted', { durationMs: timing.last.persistMs })
      // A stale rebuild response may have replaced currentDesign while this PUT
      // was in flight. Reassert only the newest acknowledged snapshot: applying
      // an older queued acknowledgement would briefly snap a newer drag back.
      if (response?.view_volumes && generation === saveGeneration) {
        store.setState({
          currentDesign: { ...store.getState().currentDesign, view_volumes: response.view_volumes },
        })
      }
    }).then(() => requestPreview())
    return saveQueue
  }

  function makeVisual(volume) {
    const group = new THREE.Group(); group.userData.volumeId = volume.id
    const material = new THREE.LineBasicMaterial({ color: 0x45b6fe, transparent: true, opacity: 0.9, depthTest: false })
    const geometry = volume.shape === 'hexagonal'
      ? new THREE.CylinderGeometry(.5, .5, 1, 6, 1, false, Math.PI / 2).rotateX(Math.PI / 2)
      : new THREE.BoxGeometry(1, 1, 1)
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), material)
    edges.userData = { volumeId: volume.id, volumeEdges: true }; edgeTargets.push(edges)
    edges.renderOrder = 19; group.add(edges)
    const hitbox = new THREE.Mesh(geometry.clone(), new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, depthWrite: false, colorWrite: false, side: THREE.DoubleSide,
    }))
    hitbox.userData = { volumeId: volume.id, volumeHitbox: true }; group.add(hitbox)
    const handlePositions = volume.shape === 'hexagonal'
      ? [[0, 0, -.5], [0, 0, .5], [.5, 0, 0]]
      : Array.from({ length: 8 }, (_, index) => [index & 1 ? .5 : -.5, index & 2 ? .5 : -.5, index & 4 ? .5 : -.5])
    for (let index = 0; index < handlePositions.length; index++) {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.08, 10, 6), new THREE.MeshBasicMaterial({ color: 0xffd54a, depthTest: false }))
      mesh.position.fromArray(handlePositions[index])
      mesh.userData = { volumeId: volume.id, cornerIndex: index }; mesh.renderOrder = 20
      group.add(mesh)
    }
    root.add(group); visualById.set(volume.id, group)
    return group
  }
  function syncVisual(volume) {
    const group = visualById.get(volume.id) ?? makeVisual(volume)
    const min = new THREE.Vector3(...volume.min_corner), max = new THREE.Vector3(...volume.max_corner)
    group.position.copy(min).add(max).multiplyScalar(.5)
    group.scale.copy(max).sub(min).max(new THREE.Vector3(.05, .05, .05))
    group.quaternion.fromArray(volume.rotation ?? [0, 0, 0, 1]).normalize()
    const outlineVisible = volume.outline_visible !== false
    group.children[0].visible = outlineVisible
    group.children[0].material.color.set(volume.id === selectedId || volume.id === hoveredId ? 0xffd54a : 0x45b6fe)
    group.children[0].material.opacity = volume.id === hoveredId ? 1 : 0.9
    for (const child of group.children.slice(2)) child.visible = outlineVisible && volume.id === selectedId
    return group
  }
  function attachSelected() {
    const selected = volumes().find(volume => volume.id === selectedId)
    const visual = selected && selected.outline_visible !== false ? visualById.get(selectedId) : null
    if (visual) transform.attach(visual); else transform.detach()
    handles.splice(0, handles.length, ...(visual?.children.slice(2) ?? []))
    configureTransformAxes()
  }
  function configureTransformAxes() {
    const selected = volumes().find(volume => volume.id === selectedId)
    const hexResize = selected?.shape === 'hexagonal' && transform.getMode() === 'scale'
    transform.showX = true
    transform.showY = !hexResize
    transform.showZ = true
    for (const handle of hexDisabledScaleHandles) handle.name = hexResize ? 'XYZ' : 'XZ'
    transform.setSpace(hexResize ? 'local' : transform.getMode() === 'translate' ? 'world' : 'local')
  }
  function render() {
    if (hoveredId && volumes().find(volume => volume.id === hoveredId)?.outline_visible === false) hoveredId = null
    const ids = new Set(volumes().map(volume => volume.id))
    for (const [id, visual] of visualById) if (!ids.has(id)) {
      const edges = visual.children.find(child => child.userData?.volumeEdges)
      const edgeIndex = edges ? edgeTargets.indexOf(edges) : -1
      if (edgeIndex >= 0) edgeTargets.splice(edgeIndex, 1)
      visual.removeFromParent(); visualById.delete(id)
    }
    list.replaceChildren()
    for (const volume of volumes()) {
      syncVisual(volume)
      const row = document.createElement('div'); row.className = 'view-volume-row'; row.dataset.volumeId = volume.id
      row.style.cssText = `border:1px solid ${volume.id === selectedId ? '#58a6ff' : '#30363d'};border-radius:4px;padding:6px;background:#0d1117`
      const top = document.createElement('div'); top.style.cssText = 'display:flex;gap:5px;align-items:center;margin-bottom:5px'
      const name = document.createElement('input'); name.className = 'view-volume-name'; name.value = volume.name; name.title = 'Rename volume'; name.style.cssText = 'min-width:0;flex:1;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;padding:3px'
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'view-volume-delete'; remove.textContent = '×'; remove.title = 'Delete volume'
      const enabled = document.createElement('button'); enabled.type = 'button'; enabled.className = 'view-volume-enabled-toggle'
      enabled.innerHTML = powerIcon; enabled.title = volume.enabled === false ? 'Enable volume representation' : 'Disable volume representation'
      enabled.setAttribute('aria-label', enabled.title); enabled.setAttribute('aria-pressed', String(volume.enabled !== false))
      if (volume.enabled === false) enabled.style.opacity = '.4'
      const outline = document.createElement('button'); outline.type = 'button'; outline.className = 'view-volume-outline-toggle'
      outline.innerHTML = eyeIcon; outline.title = volume.outline_visible === false ? 'Show volume outline' : 'Hide volume outline'
      outline.setAttribute('aria-label', outline.title); outline.setAttribute('aria-pressed', String(volume.outline_visible !== false))
      if (volume.outline_visible === false) outline.style.opacity = '.4'
      top.append(name, enabled, outline, remove)
      const controlsRow = document.createElement('div'); controlsRow.style.cssText = 'display:grid;grid-template-columns:1fr 74px;gap:5px'
      const rep = document.createElement('select'); rep.className = 'view-volume-representation'; rep.title = 'Representation'
      rep.style.cssText = 'min-width:0;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;padding:3px'
      for (const [label, value] of VIEW_VOLUME_REPRESENTATIONS) rep.add(new Option(label, value))
      rep.value = volume.representation
      const opacity = document.createElement('input'); opacity.className = 'view-volume-opacity'; opacity.type = 'range'; opacity.min = '0'; opacity.max = '1'; opacity.step = '0.05'; opacity.value = String(volume.opacity); opacity.title = `Opacity ${Math.round(volume.opacity * 100)}%`
      controlsRow.append(rep, opacity); row.append(top, controlsRow); list.append(row)
      row.addEventListener('click', () => { selectedId = selectedId === volume.id ? null : volume.id; render() })
      for (const control of [name, rep, opacity, enabled, outline, remove]) control.addEventListener('click', event => event.stopPropagation())
      name.addEventListener('change', e => save(volumes().map(v => v.id === volume.id ? { ...v, name: e.target.value.trim() || 'View Volume' } : v)))
      rep.addEventListener('change', e => save(volumes().map(v => v.id === volume.id ? { ...v, representation: e.target.value } : v)))
      opacity.addEventListener('change', e => save(volumes().map(v => v.id === volume.id ? { ...v, opacity: Number(e.target.value) } : v)))
      enabled.addEventListener('click', () => save(volumes().map(v => v.id === volume.id ? { ...v, enabled: v.enabled === false } : v)))
      outline.addEventListener('click', () => save(volumes().map(v => v.id === volume.id ? { ...v, outline_visible: v.outline_visible === false } : v)))
      remove.addEventListener('click', e => { e.stopPropagation(); if (selectedId === volume.id) selectedId = null; save(volumes().filter(v => v.id !== volume.id)) })
    }
    const allVisible = volumes().length > 0 && volumes().every(volume => volume.outline_visible !== false)
    const master = section.querySelector('#view-volume-toggle-all')
    master.style.opacity = allVisible ? '1' : '.4'
    master.title = allVisible ? 'Hide all volume outlines' : 'Show all volume outlines'
    master.setAttribute('aria-label', master.title); master.setAttribute('aria-pressed', String(allVisible))
    const allEnabled = volumes().length > 0 && volumes().every(volume => volume.enabled !== false)
    const enableMaster = section.querySelector('#view-volume-enable-all')
    enableMaster.style.opacity = allEnabled ? '1' : '.4'
    enableMaster.title = allEnabled ? 'Disable all volume representations' : 'Enable all volume representations'
    enableMaster.setAttribute('aria-label', enableMaster.title); enableMaster.setAttribute('aria-pressed', String(allEnabled))
    attachSelected(); requestPreview()
  }
  function addVolume(shape) {
    const bounds = defaultBounds(entries()), id = crypto.randomUUID()
    if (shape === 'hexagonal') {
      const centerX = (bounds.min_corner[0] + bounds.max_corner[0]) / 2
      const centerY = (bounds.min_corner[1] + bounds.max_corner[1]) / 2
      const radius = Math.max((bounds.max_corner[0] - bounds.min_corner[0]) / 2, (bounds.max_corner[1] - bounds.min_corner[1]) / 2)
      bounds.min_corner[0] = centerX - radius; bounds.max_corner[0] = centerX + radius
      bounds.min_corner[1] = centerY - radius; bounds.max_corner[1] = centerY + radius
    }
    selectedId = id
    // Start as Full: creating a box must stay instantaneous even for an 80 MB
    // design. The user explicitly opts into surface/atomistic computation.
    save([...volumes(), { id, name: `${shape === 'hexagonal' ? 'Hex Volume' : 'Volume'} ${volumes().length + 1}`, shape, ...bounds, rotation: [0, 0, 0, 1], representation: 'full', opacity: 1, outline_visible: true, enabled: true }])
  }
  section.querySelector('#view-volume-enable-all').addEventListener('click', () => {
    const enable = volumes().some(volume => volume.enabled === false)
    save(volumes().map(volume => ({ ...volume, enabled: enable })))
  })
  section.querySelector('#view-volume-toggle-all').addEventListener('click', () => {
    const show = volumes().some(volume => volume.outline_visible === false)
    save(volumes().map(volume => ({ ...volume, outline_visible: show })))
  })
  section.querySelector('#view-volume-add-box').addEventListener('click', () => addVolume('box'))
  section.querySelector('#view-volume-add-hexagonal').addEventListener('click', () => addVolume('hexagonal'))
  for (const button of section.querySelectorAll('[data-volume-tool]')) button.addEventListener('click', () => {
    transform.setMode(button.dataset.volumeTool)
    configureTransformAxes()
    for (const other of section.querySelectorAll('[data-volume-tool]')) other.classList.toggle('active', other === button)
  })
  transform.addEventListener('mouseDown', () => {
    if (!selectedId) return
    draftVolumes = volumes().map(volume => ({ ...volume, min_corner: [...volume.min_corner], max_corner: [...volume.max_corner] }))
    const selected = volumes().find(volume => volume.id === selectedId)
    transformStart = performance.now(); controls.enabled = false
    dragStartScale = visualById.get(selectedId)?.scale.clone()
    draggingHexagonal = selected?.shape === 'hexagonal'
    note('interaction-start', { mode: transform.getMode(), id: selectedId })
  })
  transform.addEventListener('objectChange', () => {
    if (!draftVolumes || !selectedId) return
    if (draggingHexagonal && dragStartScale && transform.getMode() === 'scale') {
      const start = dragStartScale, radialFactor = visualById.get(selectedId).scale.x / start.x
      visualById.get(selectedId).scale.y = start.y * radialFactor
    }
    const visual = visualById.get(selectedId), half = visual.scale.clone()
    half.set(Math.abs(half.x), Math.abs(half.y), Math.abs(half.z)).multiplyScalar(.5)
    half.max(new THREE.Vector3(.025, .025, .025)); visual.scale.copy(half).multiplyScalar(2)
    const bounds = { min_corner: visual.position.clone().sub(half).toArray(), max_corner: visual.position.clone().add(half).toArray(), rotation: visual.quaternion.toArray() }
    draftVolumes = draftVolumes.map(volume => volume.id === selectedId ? { ...volume, ...bounds } : volume)
    requestPreview(draftVolumes)
  })
  transform.addEventListener('mouseUp', () => {
    if (!draftVolumes) return
    const committed = draftVolumes; draftVolumes = null; controls.enabled = true
    timing.last.interactionMs = performance.now() - transformStart; timing.counters.commits += 1
    note('interaction-commit', { durationMs: timing.last.interactionMs, id: selectedId })
    save(committed)
  })
  const edgeWorldA = new THREE.Vector3(), edgeWorldB = new THREE.Vector3()
  function edgeAtPointer(event, tolerancePx = 8) {
    const rect = canvas.getBoundingClientRect()
    let bestId = null, bestDistance = tolerancePx
    for (const edges of edgeTargets) {
      if (!edges.visible) continue
      const positions = edges.geometry.attributes.position
      for (let index = 0; index < positions.count; index += 2) {
        edgeWorldA.fromBufferAttribute(positions, index); edges.localToWorld(edgeWorldA); edgeWorldA.project(camera)
        edgeWorldB.fromBufferAttribute(positions, index + 1); edges.localToWorld(edgeWorldB); edgeWorldB.project(camera)
        const ax = rect.left + (edgeWorldA.x + 1) * rect.width / 2, ay = rect.top + (1 - edgeWorldA.y) * rect.height / 2
        const bx = rect.left + (edgeWorldB.x + 1) * rect.width / 2, by = rect.top + (1 - edgeWorldB.y) * rect.height / 2
        const dx = bx - ax, dy = by - ay, length2 = dx * dx + dy * dy
        const t = length2 ? Math.max(0, Math.min(1, ((event.clientX - ax) * dx + (event.clientY - ay) * dy) / length2)) : 0
        const distance = Math.hypot(event.clientX - (ax + t * dx), event.clientY - (ay + t * dy))
        if (distance < bestDistance) { bestDistance = distance; bestId = edges.userData.volumeId }
      }
    }
    return bestId
  }
  function setHovered(nextId) {
    if (nextId === hoveredId) return
    hoveredId = nextId
    for (const volume of volumes()) syncVisual(volume)
    canvas.style.cursor = hoveredId ? 'pointer' : ''
  }
  let pendingEmptyPointer = null
  const onCanvasPointerMove = event => {
    if (pendingEmptyPointer?.pointerId === event.pointerId
      && Math.hypot(event.clientX - pendingEmptyPointer.x, event.clientY - pendingEmptyPointer.y) > 4) {
      pendingEmptyPointer = null
    }
    setHovered(transform.dragging || transform.axis ? null : edgeAtPointer(event))
  }
  const onCanvasPointerDown = event => {
    if (event.button !== 0 || transform.dragging || transform.axis) return
    const nextId = edgeAtPointer(event)
    if (!nextId) {
      pendingEmptyPointer = selectedId
        ? { pointerId: event.pointerId, x: event.clientX, y: event.clientY }
        : null
      return
    }
    pendingEmptyPointer = null
    event.preventDefault(); event.stopImmediatePropagation()
    selectedId = nextId; hoveredId = nextId; render()
  }
  const onCanvasPointerUp = event => {
    if (!pendingEmptyPointer || pendingEmptyPointer.pointerId !== event.pointerId) return
    const moved = Math.hypot(event.clientX - pendingEmptyPointer.x, event.clientY - pendingEmptyPointer.y)
    pendingEmptyPointer = null
    if (moved <= 4 && selectedId) { selectedId = null; render() }
  }
  const onCanvasPointerCancel = event => {
    if (pendingEmptyPointer?.pointerId === event.pointerId) pendingEmptyPointer = null
  }
  canvas.addEventListener('pointermove', onCanvasPointerMove)
  canvas.addEventListener('pointerdown', onCanvasPointerDown, { capture: true })
  canvas.addEventListener('pointerup', onCanvasPointerUp, { capture: true })
  canvas.addEventListener('pointercancel', onCanvasPointerCancel, { capture: true })
  const onWindowKeyDown = event => {
    if (event.key === 'Escape' && selectedId) { selectedId = null; transform.detach(); render(); return }
    if (event.key !== 'Tab' || !selectedId || /^(INPUT|SELECT|TEXTAREA)$/.test(event.target?.tagName)) return
    event.preventDefault()
    const modes = ['translate', 'scale', 'rotate'], next = modes[(modes.indexOf(transform.getMode()) + 1) % modes.length]
    transform.setMode(next)
    configureTransformAxes()
    for (const button of section.querySelectorAll('[data-volume-tool]')) button.classList.toggle('active', button.dataset.volumeTool === next)
  }
  window.addEventListener('keydown', onWindowKeyDown)
  let previousDesign = store.getState().currentDesign
  let previousGeometry = store.getState().currentGeometry
  const unsubscribe = store.subscribe(state => {
    const designChanged = state.currentDesign !== previousDesign
    const geometryChanged = state.currentGeometry !== previousGeometry
    if (!designChanged && !geometryChanged) return
    previousDesign = state.currentDesign
    previousGeometry = state.currentGeometry
    // design_renderer subscribed before this module, so a geometry notification
    // reaches us after its synchronous rebuild has populated backbone entries.
    render()
  })
  render()
  const apiDebug = {
    add: (shape = 'box') => section.querySelector(shape === 'hexagonal' ? '#view-volume-add-hexagonal' : '#view-volume-add-box').click(),
    layers: () => resolveViewVolumeLayers(activeViewVolumes(volumes()), points()),
    select: id => { selectedId = id; render() },
    handles: () => {
      const rect = canvas.getBoundingClientRect()
      return handles.filter(handle => handle.visible).map(handle => {
        const projected = handle.getWorldPosition(new THREE.Vector3()).project(camera)
        return { x: rect.left + (projected.x + 1) * rect.width / 2, y: rect.top + (1 - projected.y) * rect.height / 2, ...handle.userData }
      })
    },
    centers: () => {
      const rect = canvas.getBoundingClientRect()
      return [...visualById].map(([id, visual]) => {
        const projected = visual.getWorldPosition(new THREE.Vector3()).project(camera)
        return { id, x: rect.left + (projected.x + 1) * rect.width / 2, y: rect.top + (1 - projected.y) * rect.height / 2 }
      })
    },
    outlinePoint: id => {
      const edges = visualById.get(id)?.children.find(child => child.userData?.volumeEdges)
      if (!edges) return null
      const rect = canvas.getBoundingClientRect(), positions = edges.geometry.attributes.position
      edgeWorldA.fromBufferAttribute(positions, 0); edges.localToWorld(edgeWorldA); edgeWorldA.project(camera)
      edgeWorldB.fromBufferAttribute(positions, 1); edges.localToWorld(edgeWorldB); edgeWorldB.project(camera)
      return {
        x: rect.left + ((edgeWorldA.x + edgeWorldB.x) / 2 + 1) * rect.width / 2,
        y: rect.top + (1 - (edgeWorldA.y + edgeWorldB.y) / 2) * rect.height / 2,
      }
    },
    backboneTargets: (limit = 100) => entries().slice(0, Math.max(0, limit)).map(entry => ({
      key: `${entry.nuc.helix_id}:${entry.nuc.bp_index}`,
      position: entry.pos.toArray(),
    })),
    selectedMembership: (targetKey = null) => {
      const layer = resolveViewVolumeLayers(volumes(), points()).find(item => item.volume.id === selectedId)
      return {
        id: selectedId,
        count: layer?.keys.size ?? 0,
        containsTarget: targetKey == null ? null : !!layer?.keys.has(targetKey),
        sampleKeys: [...(layer?.keys ?? [])].slice(0, 20),
      }
    },
    volumes: () => structuredClone(volumes()),
    isDragging: () => transform.dragging,
    setMode: mode => { transform.setMode(mode); configureTransformAxes(); return transform.getMode() },
    mode: () => transform.getMode(),
    scaleGizmoAxes: () => {
      transform.getHelper().updateMatrixWorld(true)
      return [...new Set(transform._gizmo.picker.scale.children.filter(handle => handle.visible).map(handle => handle.name))].sort()
    },
    selected: () => selectedId,
    hovered: () => hoveredId,
    gizmoVisible: () => !!transform.object && transform.getHelper().visible,
    representationBusy: () => busyKinds.size > 0,
    begin: () => { transform.dispatchEvent({ type: 'mouseDown' }); return !!draftVolumes },
    translatePreview: delta => {
      const visual = visualById.get(selectedId); if (!visual || !draftVolumes) return false
      visual.position.add(new THREE.Vector3(...delta)); transform.dispatchEvent({ type: 'objectChange' }); return true
    },
    scalePreview: factors => {
      const visual = visualById.get(selectedId); if (!visual || !draftVolumes) return false
      visual.scale.multiply(new THREE.Vector3(...factors)); transform.dispatchEvent({ type: 'objectChange' }); return true
    },
    rotatePreview: (axis, radians) => {
      const visual = visualById.get(selectedId); if (!visual || !draftVolumes) return false
      visual.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...axis).normalize(), radians)).normalize()
      transform.dispatchEvent({ type: 'objectChange' }); return true
    },
    commit: () => { if (!draftVolumes) return false; transform.dispatchEvent({ type: 'mouseUp' }); return true },
    moveSelected: delta => {
      const visual = visualById.get(selectedId); if (!visual) return false
      visual.position.add(new THREE.Vector3(...delta)); transform.dispatchEvent({ type: 'mouseDown' }); transform.dispatchEvent({ type: 'objectChange' }); transform.dispatchEvent({ type: 'mouseUp' }); return true
    },
    moveToBackbone: (keyOrIndex = 0) => {
      const source = entries()
      const entry = typeof keyOrIndex === 'string'
        ? source.find(item => `${item.nuc.helix_id}:${item.nuc.bp_index}` === keyOrIndex)
        : source[keyOrIndex]
      const visual = visualById.get(selectedId)
      if (!entry || !visual) return false
      transform.dispatchEvent({ type: 'mouseDown' })
      visual.position.copy(entry.pos)
      transform.dispatchEvent({ type: 'objectChange' })
      transform.dispatchEvent({ type: 'mouseUp' })
      return { key: `${entry.nuc.helix_id}:${entry.nuc.bp_index}`, position: entry.pos.toArray() }
    },
    resizeSelected: factors => {
      const visual = visualById.get(selectedId); if (!visual) return false
      transform.dispatchEvent({ type: 'mouseDown' }); visual.scale.multiply(new THREE.Vector3(...factors)); transform.dispatchEvent({ type: 'objectChange' }); transform.dispatchEvent({ type: 'mouseUp' }); return true
    },
    timing: () => structuredClone(timing),
    abort: () => previewScheduler.abort('debug-abort'),
  }
  return { render, debug: apiDebug, dispose: () => { unsubscribe?.(); window.removeEventListener('nadoc:view-volume-stage', onStage); window.removeEventListener('keydown', onWindowKeyDown); canvas.removeEventListener('pointermove', onCanvasPointerMove); canvas.removeEventListener('pointerdown', onCanvasPointerDown, { capture: true }); canvas.removeEventListener('pointerup', onCanvasPointerUp, { capture: true }); canvas.removeEventListener('pointercancel', onCanvasPointerCancel, { capture: true }); previewScheduler.abort('dispose'); if (representationTimer !== null) clearTimeout(representationTimer); transform.dispose(); transform.getHelper().removeFromParent(); root.removeFromParent() } }
}
