import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

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
  return Math.abs(local.x) <= half.x && Math.abs(local.y) <= half.y && Math.abs(local.z) <= half.z
}

/** Resolve spatial membership without collapsing overlaps. */
export function resolveViewVolumeLayers(volumes, points) {
  return (volumes ?? []).map(volume => ({
    volume,
    keys: new Set((points ?? []).filter(item => pointInVolume(item.position, volume)).map(item => item.key)),
  }))
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
  section.innerHTML = `<h2 style="display:flex;align-items:center;justify-content:space-between"><span style="display:inline-flex;align-items:center;gap:7px"><span>View Volumes</span><span id="view-volume-busy" class="nadoc-spinner" role="status" aria-label="View volume representation loading" title="Building view volume representation…" style="display:none"></span></span><button id="view-volume-add" type="button" title="Add view volume" aria-label="Add view volume" style="width:26px;height:24px;font-size:19px;line-height:18px">+</button></h2><div class="view-volume-tool-row" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;margin-bottom:7px"><button type="button" data-volume-tool="translate" class="xover-mode-btn active" title="Move the selected volume without changing its shape (Tab)">Move</button><button type="button" data-volume-tool="scale" class="xover-mode-btn" title="Resize the selected volume about its center (Tab)">Resize</button><button type="button" data-volume-tool="rotate" class="xover-mode-btn" title="Rotate the selected volume (Tab)">Rotate</button></div><div id="view-volume-list" style="max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:6px"></div>`
  pane.append(section)
  const list = section.querySelector('#view-volume-list')
  const root = new THREE.Group(); root.name = 'view-volumes'; scene.add(root)
  const visualById = new Map(), handles = [], pickTargets = []
  const transform = new TransformControls(camera, canvas)
  transform.setMode('translate'); transform.setSpace('world'); transform.setSize(0.8)
  scene.add(transform.getHelper())
  let selectedId = null, draftVolumes = null, transformStart = null
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
    const layers = resolveViewVolumeLayers(sourceVolumes, sourcePoints).map(layer => ({
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
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), material)
    edges.renderOrder = 19; group.add(edges)
    const hitbox = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, depthWrite: false, colorWrite: false, side: THREE.DoubleSide,
    }))
    hitbox.userData = { volumeId: volume.id, volumeHitbox: true }; group.add(hitbox); pickTargets.push(hitbox)
    for (let index = 0; index < 8; index++) {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.08, 10, 6), new THREE.MeshBasicMaterial({ color: 0xffd54a, depthTest: false }))
      mesh.position.set(index & 1 ? .5 : -.5, index & 2 ? .5 : -.5, index & 4 ? .5 : -.5)
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
    group.children[0].material.color.set(volume.id === selectedId ? 0xffd54a : 0x45b6fe)
    for (const child of group.children.slice(2)) child.visible = volume.id === selectedId
    return group
  }
  function attachSelected() {
    const visual = selectedId && visualById.get(selectedId)
    if (visual) transform.attach(visual); else transform.detach()
    handles.splice(0, handles.length, ...(visual?.children.slice(2) ?? []))
  }
  function render() {
    const ids = new Set(volumes().map(volume => volume.id))
    for (const [id, visual] of visualById) if (!ids.has(id)) {
      const hitbox = visual.children.find(child => child.userData?.volumeHitbox)
      const pickIndex = hitbox ? pickTargets.indexOf(hitbox) : -1
      if (pickIndex >= 0) pickTargets.splice(pickIndex, 1)
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
      top.append(name, remove)
      const controlsRow = document.createElement('div'); controlsRow.style.cssText = 'display:grid;grid-template-columns:1fr 74px;gap:5px'
      const rep = document.createElement('select'); rep.className = 'view-volume-representation'; rep.title = 'Representation'
      rep.style.cssText = 'min-width:0;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;padding:3px'
      for (const [label, value] of VIEW_VOLUME_REPRESENTATIONS) rep.add(new Option(label, value))
      rep.value = volume.representation
      const opacity = document.createElement('input'); opacity.className = 'view-volume-opacity'; opacity.type = 'range'; opacity.min = '0'; opacity.max = '1'; opacity.step = '0.05'; opacity.value = String(volume.opacity); opacity.title = `Opacity ${Math.round(volume.opacity * 100)}%`
      controlsRow.append(rep, opacity); row.append(top, controlsRow); list.append(row)
      row.addEventListener('click', () => { selectedId = selectedId === volume.id ? null : volume.id; render() })
      for (const control of [name, rep, opacity, remove]) control.addEventListener('click', event => event.stopPropagation())
      name.addEventListener('change', e => save(volumes().map(v => v.id === volume.id ? { ...v, name: e.target.value.trim() || 'View Volume' } : v)))
      rep.addEventListener('change', e => save(volumes().map(v => v.id === volume.id ? { ...v, representation: e.target.value } : v)))
      opacity.addEventListener('change', e => save(volumes().map(v => v.id === volume.id ? { ...v, opacity: Number(e.target.value) } : v)))
      remove.addEventListener('click', e => { e.stopPropagation(); if (selectedId === volume.id) selectedId = null; save(volumes().filter(v => v.id !== volume.id)) })
    }
    attachSelected(); requestPreview()
  }
  section.querySelector('#view-volume-add').addEventListener('click', () => {
    const bounds = defaultBounds(entries()), id = crypto.randomUUID()
    selectedId = id
    // Start as Full: creating a box must stay instantaneous even for an 80 MB
    // design. The user explicitly opts into surface/atomistic computation.
    save([...volumes(), { id, name: `Volume ${volumes().length + 1}`, ...bounds, rotation: [0, 0, 0, 1], representation: 'full', opacity: 1 }])
  })
  for (const button of section.querySelectorAll('[data-volume-tool]')) button.addEventListener('click', () => {
    transform.setMode(button.dataset.volumeTool)
    for (const other of section.querySelectorAll('[data-volume-tool]')) other.classList.toggle('active', other === button)
  })
  transform.addEventListener('mouseDown', () => {
    if (!selectedId) return
    draftVolumes = volumes().map(volume => ({ ...volume, min_corner: [...volume.min_corner], max_corner: [...volume.max_corner] }))
    transformStart = performance.now(); controls.enabled = false; note('interaction-start', { mode: transform.getMode(), id: selectedId })
  })
  transform.addEventListener('objectChange', () => {
    if (!draftVolumes || !selectedId) return
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
  const pickRaycaster = new THREE.Raycaster(), pickPointer = new THREE.Vector2()
  const onCanvasPointerDown = event => {
    if (transform.dragging || transform.axis) return
    const rect = canvas.getBoundingClientRect()
    pickPointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
    pickRaycaster.setFromCamera(pickPointer, camera)
    const hit = pickRaycaster.intersectObjects([...pickTargets, ...handles], false)[0]
    const nextId = hit?.object?.userData?.volumeId ?? null
    if (nextId !== selectedId) { selectedId = nextId; render() }
  }
  canvas.addEventListener('pointerdown', onCanvasPointerDown)
  const onWindowKeyDown = event => {
    if (event.key === 'Escape' && selectedId) { selectedId = null; transform.detach(); render(); return }
    if (event.key !== 'Tab' || !selectedId || /^(INPUT|SELECT|TEXTAREA)$/.test(event.target?.tagName)) return
    event.preventDefault()
    const modes = ['translate', 'scale', 'rotate'], next = modes[(modes.indexOf(transform.getMode()) + 1) % modes.length]
    transform.setMode(next)
    for (const button of section.querySelectorAll('[data-volume-tool]')) button.classList.toggle('active', button.dataset.volumeTool === next)
  }
  window.addEventListener('keydown', onWindowKeyDown)
  let previousDesign = store.getState().currentDesign
  const unsubscribe = store.subscribe(state => { if (state.currentDesign === previousDesign) return; previousDesign = state.currentDesign; render() })
  render()
  const apiDebug = {
    add: () => section.querySelector('#view-volume-add').click(),
    layers: () => resolveViewVolumeLayers(volumes(), points()),
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
    setMode: mode => { transform.setMode(mode); return transform.getMode() },
    mode: () => transform.getMode(),
    selected: () => selectedId,
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
  return { render, debug: apiDebug, dispose: () => { unsubscribe?.(); window.removeEventListener('nadoc:view-volume-stage', onStage); window.removeEventListener('keydown', onWindowKeyDown); canvas.removeEventListener('pointerdown', onCanvasPointerDown); previewScheduler.abort('dispose'); if (representationTimer !== null) clearTimeout(representationTimer); transform.dispose(); transform.getHelper().removeFromParent(); root.removeFromParent() } }
}
