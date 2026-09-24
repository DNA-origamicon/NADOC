import * as THREE from 'three'
import { matchTargetEntries, unresolvedBaseKeys, describeTarget } from './annotation_targets.js'
import { createExternalTargets } from './annotation_external.js'
import { mountSelectionPing } from '../viewer/selection_ping.js'

const sources = new WeakMap()
export const capturePresentationSelection = scene => sources.get(scene)?.capture() ?? null

/** Canonical part refs and assembly selections resolved against current displayed coordinates. */
export function resolvePresentationSelection({ state, entries, resolveBasePosition, resolveExternal, assemblyRenderer, assemblyCluster, extras = [] }) {
  if (!state.assemblyActive) {
    const refs = state.selection?.items?.length ? state.selection.items : state.activeClusterId ? [{ kind: 'cluster', id: state.activeClusterId }] : []
    const matched = matchTargetEntries(refs, state.currentDesign, entries)
    const points = matched.map(e => e.pos)
    const unresolved = unresolvedBaseKeys(refs, matched)
    for (const key of unresolved) { const p = resolveBasePosition(key); if (p) points.push(p) }
    for (const ref of refs) {
      const s = resolveExternal(ref)
      if (s) for (const [x, y, z] of [[0,0,0],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]]) points.push(new THREE.Vector3(s.x + x*s.radius, s.y + y*s.radius, s.z + z*s.radius))
    }
    for (const e of extras) if (e.position) points.push(e.position)
    return { cacheable: !extras.length && !unresolved.length && !refs.some(r => ['protein', 'nanoparticle'].includes(r.kind)), key: JSON.stringify(['part', state.currentDesign?.id, refs, extras.map(e => e.id)]), label: [refs.length ? describeTarget(refs, state.currentDesign) : '', extras.length ? `${extras.length} loop/skip marker(s)` : ''].filter(Boolean).join(' · '), points }
  }
  const overhangs = state.assemblyOverhangSelection ?? [], ids = new Set(state.multiSelectedInstanceIds ?? [])
  if (state.activeInstanceId) ids.add(state.activeInstanceId)
  const seen = new Set(), addGroup = id => {
    if (seen.has(id)) return
    seen.add(id)
    const g = state.currentAssembly?.groups?.find(g => g.id === id)
    g?.instance_ids?.forEach(id => ids.add(id)); g?.subgroup_ids?.forEach(addGroup)
  }
  if (state.activeGroupId) addGroup(state.activeGroupId)
  const targets = overhangs.length ? overhangs.map(o => ({ id: o.instanceId, refs: [{ kind: 'overhang', id: o.overhangId }] }))
    : assemblyCluster && ids.has(assemblyCluster.instanceId) ? [{ id: assemblyCluster.instanceId, refs: [{ kind: 'cluster', id: assemblyCluster.clusterId }] }]
    : [...ids].map(id => ({ id, refs: null }))
  const points = []
  for (const t of targets) {
    const data = assemblyRenderer?.getInstanceBackboneEntries?.(t.id)
    const matched = t.refs ? matchTargetEntries(t.refs, assemblyRenderer?.getInstanceDesign?.(t.id), data?.entries ?? []) : data?.entries ?? []
    for (const e of matched) points.push(e.pos.clone().applyMatrix4(data.matrixWorld))
    if (!matched.length && !t.refs) {
      const center = assemblyRenderer?.getInstanceCenters?.().find(c => c.id === t.id)
      if (center) points.push(center.center)
    }
  }
  return { key: JSON.stringify(['assembly', state.currentAssembly?.id, targets]), label: targets.length ? `Selected ${overhangs.length ? 'overhang' : assemblyCluster ? 'cluster' : state.activeGroupId ? 'group' : 'part'}${targets.length > 1 ? ` (${targets.length})` : ''}` : '', points }
}

export function initPresentationSelection({ scene, store, container, getCamera, addFrameCallback, removeFrameCallback,
  getEntries, resolveBasePosition, getProteinRenderer, getNanoparticleSubsystem, assemblyRenderer, getAssemblyCluster = () => null, getExtras = () => [],
  document: doc = document, now = Date.now }) {
  const external = createExternalTargets({ getDesign: () => store.getState().currentDesign, getProteinRenderer, getNanoparticleSubsystem })
  let geometry = new THREE.BufferGeometry()
  const material = new THREE.PointsMaterial({ color: 0xffd166, size: .65, transparent: true, opacity: .65, depthTest: false, depthWrite: false })
  const cloud = new THREE.Points(geometry, material); cloud.name = 'Presenter selection'; cloud.raycast = () => {}; cloud.userData.setupOnly = true; cloud.renderOrder = 1250; cloud.frustumCulled = false; cloud.visible = false; scene.add(cloud)
  let cache = null
  let key = '', revision = 0, selection = null, ping = null, disposed = false
  const effect = mountSelectionPing({ container, getCamera, getTarget: () => cloud, now })
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn'; button.dataset.selectionPing = ''; button.textContent = 'Ping ·'; button.title = 'Ping selected element (.)'; button.setAttribute('aria-label', 'Ping selected element (.)')
  const presentationBar = doc.getElementById('presentation-controls')
  if (presentationBar) presentationBar.insertBefore(button, presentationBar.querySelector('[data-end-presentation]'))
  function update() {
    if (disposed) return
    const state = store.getState(), entries = getEntries() ?? [], extras = getExtras()
    // Matched backbone entries hold live position vectors; reuse membership between
    // selection/topology changes instead of scanning an entire design every frame.
    const cached = !state.assemblyActive && !extras.length && cache?.value.cacheable && cache.design === state.currentDesign && cache.selection === state.selection && cache.cluster === state.activeClusterId && cache.entries === entries
    const value = cached ? cache.value : resolvePresentationSelection({ state, entries, resolveBasePosition, resolveExternal: external.resolve, assemblyRenderer, assemblyCluster: getAssemblyCluster(), extras })
    cache = { value, design: state.currentDesign, selection: state.selection, cluster: state.activeClusterId, entries }
    if (value.key !== key) { key = value.key; revision++; ping = null; effect.clear() }
    const points = value.points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z))
    const stride = Math.max(1, Math.ceil(points.length / 20000)), count = Math.ceil(points.length / stride)
    let attr = geometry.getAttribute('position')
    if (!attr || attr.count !== count) { geometry.dispose(); geometry = new THREE.BufferGeometry(); cloud.geometry = geometry; attr = new THREE.Float32BufferAttribute(new Float32Array(count * 3), 3); geometry.setAttribute('position', attr) }
    let changed = false
    for (let i = 0; i < count; i++) {
      const p = points[i * stride], offset = i * 3
      if (attr.array[offset] !== Math.fround(p.x) || attr.array[offset + 1] !== Math.fround(p.y) || attr.array[offset + 2] !== Math.fround(p.z)) { attr.setXYZ(i, p.x, p.y, p.z); changed = true }
    }
    if (changed) attr.needsUpdate = true
    cloud.visible = count > 0
    button.disabled = !count
    if (ping && now() - ping.createdAt > 8000) ping = null
    selection = count ? { label: value.label.slice(0, 500), revision, target: cloud.uuid, ping } : null
    effect.update()
  }
  function trigger() {
    update()
    if (!selection) return
    ping = { id: THREE.MathUtils.generateUUID(), createdAt: now() }
    selection = { ...selection, ping }; effect.play(ping)
  }
  function keydown(event) {
    if (event.key !== '.' || event.repeat || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented ||
        event.target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])') || doc.querySelector('dialog[open]')) return
    event.preventDefault(); trigger()
  }
  button.onclick = trigger; doc.addEventListener('keydown', keydown)
  const source = { capture() { update(); return selection } }; sources.set(scene, source)
  addFrameCallback(update)
  return { trigger, update, capture: source.capture, dispose() {
    disposed = true; removeFrameCallback(update); doc.removeEventListener('keydown', keydown); button.remove(); effect.dispose(); scene.remove(cloud); geometry.dispose(); material.dispose()
    if (sources.get(scene) === source) sources.delete(scene)
  } }
}
