import * as THREE from 'three'
import { createVRCommitRefresh } from './vr_commit_refresh.js'
import { featureLogTailId } from './vr_tool_transaction.js'
import { clusterJoinNativeSignature } from './cluster_join_document.js'

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
const point = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite)
const targetSnapshot = event => ({ identity: event.targetIdentity, selectionKind: event.targetKind, ownerTokens: event.targetOwnerTokens })
const targetKey = event => JSON.stringify([event.targetIdentity, event.targetKind, event.targetOwnerTokens])

/** A rigid world delta maps directly to the desktop FreeClusterJoinRequest.
 * Reject scale/shear/reflection instead of silently changing the proposed pose. */
export function vrJoinPose(matrix) {
  if (!Array.isArray(matrix) || matrix.length !== 16 || !matrix.every(Number.isFinite)) return null
  const m = new THREE.Matrix4().fromArray(matrix), translation = new THREE.Vector3()
  const rotation = new THREE.Quaternion(), scale = new THREE.Vector3()
  m.decompose(translation, rotation, scale)
  if (scale.toArray().some(value => Math.abs(value - 1) > 1e-5)) return null
  const rigid = new THREE.Matrix4().compose(translation, rotation, new THREE.Vector3(1, 1, 1))
  if (rigid.elements.some((value, i) => Math.abs(value - matrix[i]) > 1e-5)) return null
  return { world_translation: translation.toArray(), world_rotation: rotation.normalize().toArray() }
}

/** The hint catalog is bounded; checked connections still use every native port. */
export function vrJoinSites(sites, movingId) {
  const usable = (sites ?? []).filter(site => point(site.position) && point(site.normal))
  const moving = usable.filter(site => site.cluster_id === movingId).slice(0, 4096)
  const fixed = usable.filter(site => site.cluster_id !== movingId).slice(0, 8192 - moving.length)
  return [...moving, ...fixed].map(site => ({ moving: site.cluster_id === movingId,
    position: [...site.position], normal: [...site.normal] }))
}

export function vrJoinSegments(bridges) {
  const segments = []
  const paths = (bridges ?? []).map(bridge => bridge.points ?? []).filter(points => points.length > 1).slice(0, 128)
  for (let index = 0; index < paths.length; index++) {
    const points = paths[index], budget = Math.floor((128 - segments.length) / (paths.length - index))
    const count = Math.min(points.length - 1, budget)
    for (let i = 0; i < count; i++) {
      const a = points[Math.floor(i * (points.length - 1) / count)], b = points[Math.floor((i + 1) * (points.length - 1) / count)]
      if (point(a) && point(b)) segments.push({ a, b })
    }
  }
  return segments
}

/** Native owns disposable render poses. Only Apply invokes the desktop join
 * mutation, routing and history. One backend preview runs at a time; intervening
 * frames coalesce while the native cached hint grid updates independently. */
export function createVRJoin({ api, getState, resolveTarget, transaction, sendFeedback,
  getDocumentToken = () => getState().currentDesign?.id,
  setSelectionLevel = () => {}, clearSelection = () => {}, onError = () => {},
  previewInterval = 140,
} = {}) {
  let active = false, busy = false, generation = 0, toolSequence = 0, feedbackSequence = 0
  let bound = null, latest = null, preview = null, binding = null, inFlight = null, timer = null
  let feedback = null, published = null, publishing = null, uncertain = null, lastStart = -Infinity, pendingSites = []
  let pendingSessionReset = false
  const signatures = new WeakMap()
  const signature = design => {
    if (!design) return null
    if (!signatures.has(design)) signatures.set(design, clusterJoinNativeSignature(design))
    return signatures.get(design)
  }

  const documentMatches = pin => !!pin && pin.token === getDocumentToken() && pin.signature === signature(getState().currentDesign)
  const revisionMatches = pin => documentMatches(pin) && (!Number.isSafeInteger(api.currentRevisionWatermark?.()) || api.currentRevisionWatermark() <= pin.revision)
  const current = (pin, epoch) => active && generation === epoch && documentMatches(pin)

  function update(status, message, result = null, sites = []) {
    if (pendingSessionReset) return
    if (sites.length) pendingSites = sites
    feedback = { sequence: ++feedbackSequence, tool_sequence: toolSequence,
      request_sequence: latest?.sequence ?? 0, status, message: String(message).slice(0, 512),
      valid: !!result?.valid, connection_count: result?.connection_count ?? 0,
      bridges: result?.valid ? vrJoinSegments(result.bridges) : [], sites: pendingSites }
    void publish()
  }
  async function publish() {
    if (active && !busy && bound?.ready && !binding && documentMatches(bound) && !revisionMatches(bound)) schedule()
    if (publishing) return publishing
    if (!feedback || feedback === published) return
    publishing = (async () => {
      while (feedback && feedback !== published) {
        const payload = feedback
        try {
          const result = await api.sendVRJoinFeedback(payload)
          if (result?.published === false && Number.isSafeInteger(result.current_sequence)) {
            feedbackSequence = Math.max(feedbackSequence, result.current_sequence)
            if (feedback === payload) feedback = { ...payload, sequence: ++feedbackSequence }
            continue
          }
          if (!result) break
          published = payload
        } catch { break } // Native poll retries transient transport failures.
      }
    })().finally(() => { publishing = null })
    return publishing
  }
  function retire() {
    generation++; clearTimeout(timer); timer = null
    bound?.abort?.abort(); bound = null; binding = null; latest = null; preview = null; pendingSites = []
  }
  function cancel() {
    if (busy) return false
    retire(); active = false; update('cancelled', 'Preview cancelled. Original pose and routing restored.')
    return true
  }
  function invalidate(message) {
    preview = null; update('invalid', message)
  }
  function resolve(event) {
    const target = resolveTarget(targetSnapshot(event))
    return target?.selectedRef?.kind === 'cluster' ? target.selectedRef.id : null
  }
  function requestBody(pin, pose) {
    return { mode: 'free', moving_cluster_id: pin.id, fixed_cluster_id: null,
      ...pose, reach_nm: 3, expected_design_id: pin.design.id, expected_revision: pin.revision }
  }
  async function loadTarget(event) {
    const id = resolve(event)
    if (!id) { retire(); invalidate('Select a cluster to join.'); return false }
    if (bound?.id === id && bound.key === targetKey(event) && documentMatches(bound)) {
      if (binding) return binding
      if (revisionMatches(bound)) {
        update('checking', 'Checking compatible connections…', null, bound.sites)
        return true
      }
    }
    retire()
    const pin = { id, key: targetKey(event), target: targetSnapshot(event), token: getDocumentToken(),
      design: getState().currentDesign, signature: signature(getState().currentDesign), revision: null, abort: new AbortController() }
    bound = pin
    const epoch = generation
    binding = (async () => {
      update('checking', 'Loading cluster attachment sites…')
      try {
        const catalog = await api.getClusterJoinSites({ signal: pin.abort.signal })
        if (!current(pin, epoch)) return false
        if (!catalog || catalog.design_id !== pin.design.id || !Number.isSafeInteger(catalog.revision)) throw new Error('Attachment sites are unavailable. Select the cluster again.')
        pin.revision = catalog.revision
        if (!revisionMatches(pin)) throw new Error('Design changed. Select the cluster again.')
        const cluster = catalog.clusters?.find(value => value.cluster_id === id)
        if (!cluster?.eligible) throw new Error(cluster?.reason || 'This cluster has no eligible attachment sites.')
        pin.ready = true
        pin.sites = vrJoinSites(catalog.sites, id)
        update('checking', 'Move the cluster near compatible attachments.', null, pin.sites)
        return true
      } catch (error) {
        if (current(pin, epoch)) invalidate(error.message)
        return false
      } finally { if (current(pin, epoch)) { binding = null; schedule() } }
    })()
    return binding
  }
  function queuePose(matrix, sequence) {
    const pose = vrJoinPose(matrix)
    if (!pose || !Number.isSafeInteger(sequence) || sequence < 0) { invalidate('Invalid rigid Join pose.'); return false }
    const key = JSON.stringify(pose)
    if (latest?.sequence === sequence && latest.key === key) return true
    latest = { pose, sequence, key }; preview = null
    update('checking', 'Checking compatible connections…')
    schedule(); return true
  }
  function schedule() {
    if (!active || busy || binding || inFlight || timer || !latest || !bound?.ready) return
    if (!revisionMatches(bound)) {
      if (!documentMatches(bound)) { invalidate('Design changed. Select the cluster again.'); return }
      const pose = latest, target = bound.target
      void loadTarget({ targetIdentity: target.identity, targetKind: target.selectionKind, targetOwnerTokens: target.ownerTokens })
      latest = pose
      return
    }
    const delay = Math.max(0, previewInterval - (performance.now() - lastStart))
    timer = setTimeout(() => { timer = null; void evaluate() }, delay)
  }
  async function evaluate() {
    if (inFlight || !bound?.ready || !latest || !revisionMatches(bound)) return false
    const pin = bound, pose = latest, epoch = generation, body = requestBody(pin, pose.pose)
    lastStart = performance.now()
    inFlight = (async () => {
      try {
        const result = await api.previewClusterJoin(body, { signal: pin.abort.signal })
        if (!current(pin, epoch) || latest !== pose) return false
        if (!result || result.design_id !== pin.design.id || result.revision !== pin.revision || !revisionMatches(pin)) throw new Error('Design changed. Select the cluster again.')
        preview = result.valid && result.preview_token ? { result, body, pose } : null
        update(preview ? 'valid' : 'invalid', preview
          ? `${result.connection_count ?? 1} compatible connections. Apply joins them in one edit.`
          : (result.errors ?? []).map(value => typeof value === 'string' ? value : value.message).join(' · ') || 'No compatible connections at this pose.', preview?.result)
        return !!preview
      } catch (error) {
        if (current(pin, epoch) && latest === pose) invalidate(error.message)
        return false
      }
    })().finally(() => {
      inFlight = null
      if (current(pin, epoch) && latest !== pose) schedule()
      else if (active && bound !== pin) schedule()
    })
    return inFlight
  }
  async function apply(event) {
    if (busy) return
    busy = true; clearTimeout(timer); timer = null
    const epoch = generation
    let committed = false, outcome
    const sceneRefresh = createVRCommitRefresh({ api, getState })
    try {
      if (event.action === 'undo') {
        await sendFeedback(event, 'pending', 'undoing')
        outcome = await transaction.undo({ tool: 'join', onCommitted: sceneRefresh.onCommitted })
      } else {
        const ready = binding ? await binding : true
        if (uncertain || !ready || !bound || resolve(event) !== bound.id || targetKey(event) !== bound.key || !revisionMatches(bound)) throw new Error('Select the cluster again and preview its current connections.')
        if (!queuePose(event.transformMatrix, event.transformSequence ?? latest?.sequence ?? 0)) throw new Error('The final Join pose is missing or invalid.')
        if (inFlight) await inFlight
        if (!preview || preview.pose !== latest) await evaluate()
        if (generation !== epoch || !preview || !revisionMatches(bound)) throw new Error('A valid preview of the final pose is required.')
        const pin = bound, request = { ...preview.body, preview_token: preview.result.preview_token }
        const ack = await sendFeedback(event, 'pending', 'committing')
        if (ack?.published !== true) throw new Error('Join acknowledgement was not published.')
        update('applying', 'Applying previewed connections…')
        outcome = await transaction.commit({ tool: 'join', targetKey: pin.key,
          targetIdentity: event.targetIdentity, targetKind: event.targetKind,
          execute: async () => {
            if (!revisionMatches(pin) || generation !== epoch || resolve(event) !== pin.id) return { accepted: false, reason: 'stale_target' }
            let response
            try { response = await api.applyClusterJoin(request) }
            catch (error) { uncertain = { token: pin.token, design: pin.design }; throw error }
            if (!response) {
              if (!getState().lastError?.status) uncertain = { token: pin.token, design: pin.design }
              throw new Error(getState().lastError?.message || 'Join failed.')
            }
            committed = true; uncertain = { token: pin.token, design: pin.design }
            if (!documentMatches(pin)) throw new Error('Join saved in the previous document.')
            sceneRefresh.onCommitted(response)
            if (!await api._syncFromDesignResponse(response)) throw new Error('Join saved; desktop refresh failed.')
            uncertain = null; clearSelection()
            return { accepted: true, vr_transaction: { feature_log_entry_id: featureLogTailId(getState()), target_count: 1 } }
          } })
      }
      if (outcome.accepted) {
        retire(); active = false
        try { if (!(await sceneRefresh.complete())?.published) throw new Error('VR scene refresh failed.') }
        catch (error) { onError(`Join saved; ${error.message}`) }
        update('applied', event.action === 'undo' ? 'Join undone.' : 'Clusters joined. Undo restores pose and routing.')
      } else {
        preview = null
        update('failed', uncertain ? 'Join result unknown. Reload the design before retrying.' : outcome.reason.replaceAll('_', ' '))
      }
      if (!pendingSessionReset) await sendFeedback(event, outcome.accepted ? 'succeeded' : 'refused', outcome.reason, outcome.transaction)
    } catch (error) {
      const message = uncertain ? 'Join result unknown. Reload the design before retrying.' : error.message
      preview = null
      update('failed', message); onError(message)
      if (!pendingSessionReset) await sendFeedback(event, 'failed', committed ? 'refresh_failed' : 'join_failed').catch(() => {})
    } finally { busy = false; if (pendingSessionReset) reset() }
  }
  async function recover() {
    busy = true; retire()
    const token = getDocumentToken()
    update('checking', 'Reloading the design to confirm the previous Join result…')
    try {
      if (!await api.getDesign() || token !== getDocumentToken()) throw new Error('The current design could not be reloaded.')
      const refresh = await api.refreshNativeVRScene({ expected_design_id: getState().currentDesign.id,
        expected_revision: api.currentRevisionWatermark() })
      if (!refresh?.published || token !== getDocumentToken()) throw new Error('The VR scene could not be refreshed.')
      uncertain = null; active = true
      update('ready', 'Design reloaded. Select the moving cluster again.')
    } catch (error) { update('failed', error.message); onError(error.message) }
    finally { busy = false; if (pendingSessionReset) reset() }
  }
  function handle(event) {
    if (event?.type === 'native_session_end') { reset(); return false }
    if (event?.type === 'tool' && event.mode !== 'join') { if (active) cancel(); return false }
    if (event?.type === 'tool_transform') {
      if (!active) return false
      if (busy || uncertain) return true
      if (event.targetKind && event.targetKind !== 'none' && (!bound || targetKey(event) !== bound.key)) void loadTarget(event)
      queuePose(event.matrix, event.sequence); return true
    }
    if (event?.type !== 'tool' || event.mode !== 'join') return false
    if (!Number.isSafeInteger(event.sequence) || event.sequence <= toolSequence) return true
    toolSequence = event.sequence
    if (event.action === 'cancel') { cancel(); return true }
    if (busy) return true
    if (uncertain && uncertain.token !== getDocumentToken()) uncertain = null
    if (uncertain) {
      if (event.action === 'activate' && typeof api.getDesign === 'function') void recover()
      else update('failed', 'Join result unknown. Reopen Join to reload the design before retrying.')
      return true
    }
    if (event.action === 'confirm' || event.action === 'undo') { void apply(event); return true }
    if (!['activate', 'preview'].includes(event.action)) return true
    active = true; setSelectionLevel('cluster')
    if (event.targetKind !== 'cluster') { retire(); update('ready', 'Select a cluster, then move it near compatible attachments.'); return true }
    void loadTarget(event)
    queuePose(event.transformMatrix ?? IDENTITY, event.transformSequence ?? 0)
    return true
  }
  function reset() {
    if (busy) {
      // Finish an already-issued mutation, then retire its event cursor. A new
      // native session starts again at sequence 1 and must not inherit this one.
      pendingSessionReset = true; active = false; feedback = null; published = null
      return false
    }
    pendingSessionReset = false
    retire(); active = false; toolSequence = 0; feedback = null; published = null
    return true
  }
  return { handle, publish, reset, getState: () => ({ active, busy, needsResync: !!uncertain,
    status: feedback?.status ?? 'ready', targetId: bound?.id ?? null,
    sequence: toolSequence, transformSequence: latest?.sequence ?? 0,
    valid: !!preview, connectionCount: preview?.result.connection_count ?? 0 }) }
}
