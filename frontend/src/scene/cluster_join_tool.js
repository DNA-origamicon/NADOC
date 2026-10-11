/** Native cluster Join: backend-owned ports, pose preview and atomic scaffold splice. */
import * as THREE from 'three'
import { createClusterJoinPanel } from '../ui/cluster_join_panel.js'

const OTHER_TOOLS = ['forceXoverActive', 'sweepActive', 'deformToolActive', 'translateRotateActive', 'nucleotideTransformActive']
const finitePoint = point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite)
const siteKey = site => `${site.cluster_id}/${site.id}`
const describe = value => typeof value === 'string' ? value : value?.message || value?.detail || JSON.stringify(value)
// Save acknowledgements, history payload backfills and display metadata replace
// the design object too. Only native placement/routing changes retire this tool.
const JOIN_NATIVE_FIELDS = ['lattice_type', 'lattice_frames', 'helices', 'strands', 'deformations', 'cluster_transforms',
  'nucleotide_transforms', 'cluster_joints', 'overhangs', 'overhang_connections', 'overhang_bindings', 'duplexes',
  'flexible_segment_marks', 'flexible_connections', 'extensions', 'photoproduct_junctions', 'crossovers',
  'crossover_constraints', 'forced_ligations', 'protein_assets', 'protein_attachments', 'nanoparticles', 'nanoparticle_conjugations']
const nativeSignature = design => JSON.stringify(JOIN_NATIVE_FIELDS.map(key => design?.[key] ?? null))

function disposeLayer(group) {
  group.traverse(object => {
    object.geometry?.dispose()
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) material?.dispose()
  })
  group.clear()
}
function polylineTube(points, color, radius = 0.24, opacity = 1) {
  const vertices = points.filter(finitePoint).map(point => new THREE.Vector3(...point))
  if (vertices.length < 2) return null
  const path = new THREE.CurvePath()
  for (let i = 1; i < vertices.length; i++) if (vertices[i].distanceToSquared(vertices[i - 1]) > 1e-12) path.add(new THREE.LineCurve3(vertices[i - 1], vertices[i]))
  if (!path.curves.length) return null
  return new THREE.Mesh(new THREE.TubeGeometry(path, Math.min(2048, Math.max(16, vertices.length * 3)), radius, 8, false),
    new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity, depthWrite: opacity === 1 }))
}

/** Project native attachment positions, excluding hidden, clipped and rear-facing camera space. */
export function nearbyJoinSites(sites, { camera, rect, clientX, clientY, isVisible = () => true, radius = 70, limit = 24 } = {}) {
  if (!camera || !rect?.width || !rect?.height) return []
  camera.updateMatrixWorld?.()
  const forward = camera.getWorldDirection(new THREE.Vector3())
  return sites.flatMap(site => {
    if (!finitePoint(site.position) || !isVisible(site)) return []
    const world = new THREE.Vector3(...site.position)
    if (world.clone().sub(camera.position).dot(forward) <= 0) return []
    const ndc = world.clone().project(camera)
    if (ndc.z < -1 || ndc.z > 1 || Math.abs(ndc.x) > 1 || Math.abs(ndc.y) > 1) return []
    const x = rect.left + (ndc.x + 1) * rect.width / 2, y = rect.top + (1 - ndc.y) * rect.height / 2
    const distance = Math.hypot(x - clientX, y - clientY)
    return distance <= radius ? [{ site, distance, depth: ndc.z, x, y }] : []
  }).sort((a, b) => a.distance - b.distance || a.depth - b.depth).slice(0, limit)
}

export function initClusterJoinTool({
  store, scene, canvas, camera, getCamera, controls, getControls, api,
  onActivate, onApplied, onDeactivate, showToast = () => {},
  getDocumentToken = () => store.getState().currentDesign?.id,
  isSiteVisible = () => true,
  panelFactory = createClusterJoinPanel,
  previewDelay = 120,
} = {}) {
  const root = new THREE.Group(); root.name = 'cluster-join-preview'; root.visible = false
  const markers = new THREE.Group(); markers.name = 'cluster-join-markers'
  const ghost = new THREE.Group(); ghost.name = 'cluster-join-ghost'
  const bridges = new THREE.Group(); bridges.name = 'cluster-join-bridges'
  root.add(markers, ghost, bridges); scene.add(root)
  const markerGeometry = new THREE.SphereGeometry(0.55, 12, 8)
  const sideGeometry = new THREE.OctahedronGeometry(0.65)
  const markerMaterials = Object.fromEntries(Object.entries({ normal: 0x55cfff, hover: 0xffd36f, fixed: 0x59e38f, moving: 0xcc9fff }).map(([key, color]) => [key, new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.95, wireframe: key === 'fixed' || key === 'moving' })]))
  let active = false, opening = false, applying = false, loading = false, previewLoading = false, syncing = false, disposed = false, needsResync = false
  let lifecycle = 0, sitesEpoch = 0, previewEpoch = 0, timer = null, siteAbort = null, previewAbort = null
  let bound = null, resyncPin = null, clusters = [], sites = [], first = null, second = null, preview = null, previewBody = null
  let status = '', lastPointer = null, visible = [], hovered = null, pendingPick = null, consumedPointer = null, listenedControls = null
  let params = { gap_nm: 0.8, roll_deg: 0, tilt_deg: 0 }
  const panel = panelFactory({ onApply: apply, onReset: reset, onCancel: deactivate, onParameters: updateParameters, onRefresh: refreshSites })
  const liveCamera = () => getCamera?.() ?? camera
  const documentMatches = pin => !!pin && getDocumentToken() === pin.token && store.getState().currentDesign === pin.design
  const revisionCurrent = pin => {
    const watermark = api.currentRevisionWatermark?.()
    return !Number.isSafeInteger(watermark) || !Number.isSafeInteger(pin?.revision) || watermark <= pin.revision
  }
  const eligibleSites = () => sites.filter(site => (!first || site.cluster_id !== first.cluster_id) && isSiteVisible(site))
  function renderPanel() {
    panel.render({ first, second, clusters, loading, applying, previewLoading, status, params, preview, needsResync,
      canApply: !!preview?.valid && !!preview.preview_token && !!previewBody && documentMatches(bound) && revisionCurrent(bound) })
  }
  function clearPreview() {
    preview = null; previewBody = null
    disposeLayer(ghost); ghost.matrix.identity(); ghost.matrixAutoUpdate = true
    disposeLayer(bridges)
  }
  function cancelPreviewRequest() {
    previewEpoch++; clearTimeout(timer); timer = null
    previewAbort?.abort(); previewAbort = null; previewLoading = false
  }
  function refreshMarkers() {
    markers.clear()
    const picked = new Map(visible.map(item => [siteKey(item.site), item.site]))
    if (first && isSiteVisible(first)) picked.set(siteKey(first), first)
    if (second && isSiteVisible(second)) picked.set(siteKey(second), second)
    for (const site of picked.values()) {
      const role = first && siteKey(first) === siteKey(site) ? 'fixed' : second && siteKey(second) === siteKey(site) ? 'moving' : hovered && siteKey(hovered) === siteKey(site) ? 'hover' : 'normal'
      const point = new THREE.Vector3(...site.position)
      if (role === 'moving' && preview?.valid && preview.donor_world_delta?.length === 16) point.applyMatrix4(new THREE.Matrix4().fromArray(preview.donor_world_delta))
      const mesh = new THREE.Mesh(site.kind === 'side' ? sideGeometry : markerGeometry, markerMaterials[role])
      mesh.position.copy(point)
      if (role !== 'normal') mesh.scale.setScalar(1.35)
      mesh.renderOrder = 1001
      mesh.userData = { joinSiteId: site.id, clusterId: site.cluster_id, kind: site.kind, role }
      markers.add(mesh)
    }
  }
  function updateHover(event = lastPointer) {
    if (!active || !event || applying || loading) return
    if (!needsResync && !revisionCurrent(bound)) { void refreshSites({ preserveSelection: true }); return }
    lastPointer = { clientX: event.clientX, clientY: event.clientY }
    visible = nearbyJoinSites(eligibleSites(), { camera: liveCamera(), rect: canvas.getBoundingClientRect(), ...lastPointer, isVisible: isSiteVisible })
    hovered = visible[0]?.distance <= 18 ? visible[0].site : null
    canvas.style.cursor = hovered ? 'crosshair' : ''
    refreshMarkers()
  }
  function drawPreview(result) {
    disposeLayer(ghost); disposeLayer(bridges)
    if (!result.valid || result.donor_world_delta?.length !== 16 || !result.donor_world_delta.every(Number.isFinite)) return
    const donor = clusters.find(cluster => cluster.cluster_id === second?.cluster_id)
    const native = store.getState().currentDesign?.cluster_transforms?.find(cluster => cluster.id === second?.cluster_id)
    const ids = result.donor_helix_ids ?? donor?.helix_ids ?? native?.helix_ids ?? []
    const axes = store.getState().currentHelixAxes ?? {}
    for (const id of ids) {
      const axis = axes[id]
      if (!axis) continue
      const points = axis.samples?.length > 1 ? axis.samples : [axis.start, axis.end]
      const mesh = polylineTube(points, 0x60d7ff, 1.04, 0.35)
      if (!mesh) continue
      mesh.userData = { helixId: id, joinGhost: true }
      ghost.add(mesh)
    }
    ghost.matrix.fromArray(result.donor_world_delta); ghost.matrixAutoUpdate = false
    for (const [index, bridge] of (result.bridges ?? []).entries()) {
      const points = bridge.points ?? [bridge.from?.position ?? bridge.from, bridge.to?.position ?? bridge.to]
      const color = index % 2 ? 0x72edb6 : 0xffc66b
      const mesh = polylineTube(points, color, 0.28)
      if (!mesh) continue
      mesh.userData = { joinBridge: index, from: bridge.from, to: bridge.to }
      bridges.add(mesh)
      const a = points[Math.max(0, Math.floor(points.length / 2) - 1)], b = points[Math.floor(points.length / 2)]
      if (finitePoint(a) && finitePoint(b)) {
        const direction = new THREE.Vector3(...b).sub(new THREE.Vector3(...a)).normalize()
        if (direction.lengthSq()) {
          const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.38, 0.8, 12), new THREE.MeshBasicMaterial({ color }))
          arrow.position.set(...b); arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction)
          arrow.userData.joinBridgeDirection = index
          bridges.add(arrow)
        }
      }
    }
  }
  async function refreshSites({ preserveSelection = false } = {}) {
    if (!active || applying) return false
    if (needsResync) {
      const token = getDocumentToken()
      loading = true; status = 'Reloading the design to confirm the previous join result…'; renderPanel()
      try {
        if (!api.getDesign || !await api.getDesign()) throw new Error('The design could not be reloaded. Reconnect, then refresh again.')
        if (getDocumentToken() !== token) return false
        needsResync = false; resyncPin = null
        if (active) deactivate(true)
        showToast('Design refreshed. Reopen Join to choose current attachment sites.')
        return true
      } catch (error) {
        if (active) { status = describe(error); loading = false; renderPanel() }
        return false
      }
    }
    const current = store.getState().currentDesign
    if (!current || getDocumentToken() !== bound?.token || current !== bound.design) { deactivate(true); return false }
    const selectedFirst = preserveSelection ? first : null, selectedSecond = preserveSelection ? second : null
    cancelPreviewRequest(); clearPreview()
    first = selectedFirst; second = selectedSecond
    if (!preserveSelection) { sites = []; visible = []; hovered = null; pendingPick = null }
    loading = true; status = 'Finding native scaffold attachment sites…'; renderPanel(); refreshMarkers()
    const version = ++sitesEpoch, session = lifecycle, pin = bound
    let loaded = false
    siteAbort?.abort(); siteAbort = new AbortController()
    try {
      const response = await api.getClusterJoinSites({ signal: siteAbort.signal })
      if (!active || session !== lifecycle || version !== sitesEpoch || !documentMatches(pin)) return false
      if (!response) throw new Error(store.getState().lastError?.message || 'Attachment sites could not be loaded.')
      if (response.design_id !== pin.design.id || !Number.isSafeInteger(response.revision)) throw new Error('Attachment sites belong to another document revision. Refresh the design and try again.')
      bound.revision = response.revision
      clusters = response.clusters ?? []
      sites = (response.sites ?? clusters.filter(cluster => cluster.eligible).flatMap(cluster => cluster.ports ?? [])).filter(site => finitePoint(site.position))
      if (!revisionCurrent(bound)) throw new Error('The design changed while sites were loading. Refresh sites.')
      // Rebind the current intent, not the request-start snapshot: Reset or
      // Escape may have cancelled either pick while this read was in flight.
      first = first ? sites.find(site => siteKey(site) === siteKey(first) && isSiteVisible(site)) ?? null : null
      second = first && second ? sites.find(site => siteKey(site) === siteKey(second) && isSiteVisible(site)) ?? null : null
      const count = new Set(sites.map(site => site.cluster_id)).size
      status = first ? 'Fixed point selected. Choose an attachment on a different cluster.' : count >= 2 ? `${sites.length} attachment sites in ${count} clusters. Hover near a cluster, then click a marker.` : 'Join needs two eligible clusters with separate scaffold paths. See cluster eligibility below.'
      loaded = true
      return true
    } catch (error) {
      if (active && session === lifecycle && version === sitesEpoch) { pendingPick = null; status = error?.name === 'AbortError' ? 'Site lookup cancelled.' : describe(error) }
      return false
    } finally {
      if (active && session === lifecycle && version === sitesEpoch) {
        loading = false; renderPanel(); refreshMarkers()
        if (loaded && first && second) schedulePreview()
        if (loaded && pendingPick) { const intent = pendingPick; pendingPick = null; pickSite(intent.id, intent.cluster_id) }
        if (loaded && lastPointer) updateHover()
      }
    }
  }
  function requestBody() {
    return { first: { cluster_id: first.cluster_id, port_id: first.id }, second: { cluster_id: second.cluster_id, port_id: second.id }, ...params,
      expected_design_id: bound.design.id, expected_revision: bound.revision }
  }
  function validParameters() {
    return Number.isFinite(params.gap_nm) && params.gap_nm >= 0.3 && params.gap_nm <= 10 && Number.isFinite(params.roll_deg) && Math.abs(params.roll_deg) <= 180 && Number.isFinite(params.tilt_deg) && Math.abs(params.tilt_deg) <= 60
  }
  function schedulePreview() {
    cancelPreviewRequest(); clearPreview(); refreshMarkers()
    if (!active || !first || !second || applying) { renderPanel(); return }
    if (needsResync) { status = 'The previous join result is unknown. Refresh the design before continuing.'; renderPanel(); return }
    if (!validParameters()) { status = 'Enter a gap from 0.3–10 nm, roll from −180–180°, and tilt from −60–60°.'; renderPanel(); return }
    if (!documentMatches(bound)) { status = 'The design changed. Refresh attachment sites before joining.'; renderPanel(); return }
    if (!revisionCurrent(bound)) { void refreshSites({ preserveSelection: true }); return }
    previewLoading = true; status = 'Checking placement and scaffold routing…'; renderPanel()
    const version = previewEpoch
    timer = setTimeout(() => fetchPreview(version), previewDelay)
  }
  async function fetchPreview(version) {
    const pin = bound, session = lifecycle, request = requestBody()
    previewAbort = new AbortController()
    try {
      const result = await api.previewClusterJoin(request, { signal: previewAbort.signal })
      if (!active || version !== previewEpoch || session !== lifecycle || !documentMatches(pin)) return
      if (!result) throw new Error(store.getState().lastError?.message || 'Join preview failed.')
      if (result.design_id !== pin.design.id || result.revision !== pin.revision) throw new Error('The preview is stale. Refresh attachment sites.')
      if (!revisionCurrent(pin)) { void refreshSites({ preserveSelection: true }); return }
      preview = result
      previewBody = result.valid && result.preview_token ? request : null
      if (result.valid) {
        drawPreview(result)
        status = 'Cyan shows the moved cluster. Amber and green arrows show the two scaffold bridges. Apply joins them in one undoable edit.'
      } else status = (result.errors ?? []).map(describe).join(' · ') || 'These attachment points cannot be joined. Choose another point or adjust placement.'
      refreshMarkers()
    } catch (error) {
      if (active && version === previewEpoch && session === lifecycle) { clearPreview(); status = describe(error); refreshMarkers() }
    } finally {
      if (active && version === previewEpoch && session === lifecycle) { previewLoading = false; renderPanel() }
    }
  }
  function pickSite(id, clusterId = null) {
    if (!active || applying || loading || !documentMatches(bound)) return false
    const site = typeof id === 'object' ? sites.find(item => siteKey(item) === siteKey(id)) : sites.find(item => item.id === id && (!clusterId || item.cluster_id === clusterId))
    if (!site || !isSiteVisible(site)) return false
    if (!first) {
      first = site; status = 'Fixed point selected. Choose an attachment on a different cluster.'
      visible = []; hovered = null; refreshMarkers(); renderPanel(); return true
    }
    if (site.cluster_id === first.cluster_id) return false
    second = site; visible = []; hovered = null; schedulePreview(); return true
  }
  function updateParameters(next) {
    if (!active || applying) return
    params = { ...params, ...next }; schedulePreview()
  }
  function reset() {
    if (!active || applying) return false
    cancelPreviewRequest(); clearPreview(); first = null; second = null; pendingPick = null; visible = []; hovered = null
    status = 'Hover near a cluster and choose a fixed attachment point.'
    renderPanel(); refreshMarkers(); return true
  }
  async function apply() {
    if (applying || loading || previewLoading || !active || !preview?.valid || !preview.preview_token || !previewBody) return false
    if (!documentMatches(bound)) { clearPreview(); status = 'The preview is stale. Refresh attachment sites.'; renderPanel(); return false }
    if (!revisionCurrent(bound)) { void refreshSites({ preserveSelection: true }); return false }
    applying = true; const pin = bound, request = { ...previewBody, preview_token: preview.preview_token }
    status = 'Joining clusters and reconnecting the scaffold…'; renderPanel()
    let committed = false, unknownOutcome = false
    try {
      let response
      try { response = await api.applyClusterJoin(request) }
      catch (error) { unknownOutcome = true; throw error }
      if (!documentMatches(pin)) return false
      if (!response) {
        unknownOutcome = !store.getState().lastError?.status
        throw new Error(store.getState().lastError?.message || 'Join did not return a result.')
      }
      committed = true; syncing = true
      const accepted = await onApplied?.(response)
      if (accepted === false || accepted === null) throw new Error('Join completed, but the editor could not refresh. Reload the current design.')
      applying = false; syncing = false; deactivate(true)
      showToast('Clusters joined. Undo restores the previous pose and routing.')
      return true
    } catch (error) {
      if (active && documentMatches(pin)) {
        status = describe(error)
        if (committed || unknownOutcome) {
          needsResync = true; resyncPin = pin; clearPreview(); refreshMarkers()
          status += ' Refresh the design to confirm the join result before continuing.'
        }
        renderPanel()
      }
      return false
    } finally {
      applying = false; syncing = false
      if (active) renderPanel()
    }
  }
  function onMove(event) { if (!event.buttons) updateHover(event) }
  function onDown(event) {
    if (!active || event.button !== 0 || applying || needsResync) return
    const hit = nearbyJoinSites(eligibleSites(), { camera: liveCamera(), rect: canvas.getBoundingClientRect(), clientX: event.clientX, clientY: event.clientY, isVisible: isSiteVisible, radius: 18, limit: 1 })[0]?.site
    if (!hit) return
    event.preventDefault(); event.stopImmediatePropagation(); consumedPointer = event.pointerId
    canvas.setPointerCapture?.(event.pointerId)
    lastPointer = { clientX: event.clientX, clientY: event.clientY }
    // A save acknowledgement may advance the revision between hover and press.
    // Keep the user's intent, but resolve it only against the refreshed catalog.
    if (loading || !revisionCurrent(bound)) {
      pendingPick ??= { id: hit.id, cluster_id: hit.cluster_id }
      if (!loading) void refreshSites({ preserveSelection: true })
      return
    }
    pickSite(hit)
  }
  function onUp(event) {
    if (consumedPointer == null || event.pointerId !== consumedPointer) return
    event.stopImmediatePropagation(); consumedPointer = null
    if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
  }
  function onLeave() { if (consumedPointer == null) { lastPointer = null; visible = []; hovered = null; canvas.style.cursor = ''; refreshMarkers() } }
  function onKey(event) {
    if (!active || event.key !== 'Escape') return
    event.preventDefault(); event.stopImmediatePropagation()
    if (applying) return
    pendingPick = null
    if (second) { cancelPreviewRequest(); clearPreview(); second = null; status = 'Choose another moving attachment point.'; renderPanel(); refreshMarkers() }
    else if (first) reset()
    else deactivate()
  }
  function onControlsChange() { if (active && lastPointer) updateHover() }
  async function activate() {
    if (disposed || active || opening || applying) return active
    const initial = store.getState()
    if (!initial.currentDesign || initial.assemblyActive) { showToast('Open a part with two scaffolded clusters to join.'); return false }
    opening = true; const version = ++lifecycle, token = getDocumentToken()
    try {
      const allowed = await onActivate?.()
      if (allowed === false || disposed || version !== lifecycle || token !== getDocumentToken()) return false
      const design = store.getState().currentDesign
      if (!design || store.getState().assemblyActive) return false
      needsResync = !!resyncPin && documentMatches(resyncPin)
      if (!needsResync) resyncPin = null
      bound = { token: getDocumentToken(), design, signature: nativeSignature(design), revision: null }
      active = true; root.visible = true; first = null; second = null; sites = []; clusters = []; params = { gap_nm: 0.8, roll_deg: 0, tilt_deg: 0 }
      store.setState({ joinActive: true })
      canvas.addEventListener('pointermove', onMove, true)
      canvas.addEventListener('pointerdown', onDown, true)
      canvas.addEventListener('pointerup', onUp, true)
      canvas.addEventListener('pointercancel', onUp, true)
      canvas.addEventListener('pointerleave', onLeave)
      window.addEventListener('keydown', onKey, true)
      listenedControls = getControls?.() ?? controls
      listenedControls?.addEventListener?.('change', onControlsChange)
      panel.show(); await refreshSites(); return active
    } finally { if (version === lifecycle) opening = false }
  }
  function deactivate(force = false) {
    if (applying && force !== true) return false
    lifecycle++; opening = false; siteAbort?.abort(); siteAbort = null; sitesEpoch++
    cancelPreviewRequest(); clearPreview()
    const wasActive = active; active = false; loading = false; first = null; second = null; pendingPick = null; visible = []; hovered = null; lastPointer = null
    root.visible = false; markers.clear(); panel.hide(); canvas.style.cursor = ''
    canvas.removeEventListener('pointermove', onMove, true); canvas.removeEventListener('pointerdown', onDown, true)
    canvas.removeEventListener('pointerup', onUp, true); canvas.removeEventListener('pointercancel', onUp, true); canvas.removeEventListener('pointerleave', onLeave)
    window.removeEventListener('keydown', onKey, true)
    listenedControls?.removeEventListener?.('change', onControlsChange); listenedControls = null
    if (consumedPointer != null && canvas.hasPointerCapture?.(consumedPointer)) canvas.releasePointerCapture(consumedPointer)
    consumedPointer = null
    if (store.getState().joinActive) store.setState({ joinActive: false })
    if (wasActive) onDeactivate?.()
    return true
  }
  const unsubscribe = store.subscribe((next, previous) => {
    if (!active) return
    if (next.assemblyActive || !next.currentDesign || getDocumentToken() !== bound?.token) { deactivate(true); return }
    if (next.joinActive === false || OTHER_TOOLS.some(key => next[key] && !previous[key])) { deactivate(true); return }
    if (!syncing && next.currentDesign !== bound.design) {
      const signature = nativeSignature(next.currentDesign)
      if (next.currentDesign.id !== bound.design.id || signature !== bound.signature) { deactivate(true); return }
      // Keep an in-flight Apply bound to its original pin; harmless metadata
      // must not discard the eventual native mutation response.
      bound.design = next.currentDesign
      if (resyncPin) resyncPin.design = next.currentDesign
      if (!applying && !needsResync) { void refreshSites({ preserveSelection: true }); return }
    }
    if (!applying && !loading && !needsResync && !revisionCurrent(bound)) void refreshSites({ preserveSelection: true })
  })
  const getSiteScreenPositions = () => {
    if (!active) return []
    const rect = canvas.getBoundingClientRect()
    return nearbyJoinSites(eligibleSites(), { camera: liveCamera(), rect,
      clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2,
      isVisible: isSiteVisible, radius: Infinity, limit: Infinity,
    }).map(item => ({ ...item.site, x: item.x, y: item.y, z: item.depth }))
  }
  const getState = () => ({ active, opening, busy: applying, loading, previewLoading, needsResync, sites, clusters, first, second, preview, status, params: { ...params }, visibleSiteIds: visible.map(item => item.site.id), hoveredSiteId: hovered?.id ?? null, revision: bound?.revision })
  return {
    activate, deactivate, reset, apply, refreshSites, updateParameters, getState,
    isActive: () => active, isBusy: () => applying,
    testApi: { getState, getSiteScreenPositions, pickSite, updateParameters, refreshSites, apply, reset },
    dispose() {
      if (disposed) return
      disposed = true; deactivate(true); unsubscribe?.(); panel.dispose()
      markerGeometry.dispose(); sideGeometry.dispose(); Object.values(markerMaterials).forEach(material => material.dispose()); root.removeFromParent()
    },
  }
}
