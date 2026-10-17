/** Owns one historical transform editor; canonical adoption is controller-only. */
import { createDeformationHistoryController } from '../features/deformation_history_controller.js'
import { createDeformationPreviewEndpoints } from '../api/deformation_preview_endpoints.js'
import { validateTransformPreviewDisplay } from '../features/transform_preview_display.js'
import { createTransformHistoryPreview } from '../scene/transform_history_preview.js'
import { createTransformHistoryTool } from '../scene/transform_history_tool.js'
import { getDocId } from '../shared/doc_id.js'
import { sameRepairContext } from '../features/part_repair_model.js'

export const TRANSFORM_HISTORY_EDITOR_ENABLED = false
const SNAPSHOTS = new Set(['placement-poses', 'nucleotide-transform', 'nucleotide-transform-batch', 'nucleotide-transform-delete'])
export function isNativeTransformFeature(entry) {
  if (entry?.feature_type === 'cluster_op') return entry.proof_version === 1
  return entry?.feature_type === 'snapshot' && SNAPSHOTS.has(entry.op_kind)
    && entry.params?._proof_version === 1 && !Object.hasOwn(entry.params, '_generator') && !Object.hasOwn(entry.params, '_generated_scope')
}

export function createTransformHistoryEditor({ store, api, scene, camera, canvas, controls, getPanel,
  getDocumentId = getDocId, showToast = () => {}, events = globalThis.window,
  previewAPI = createDeformationPreviewEndpoints({ request: api._request, family: 'transform' }),
  createPreview = () => createTransformHistoryPreview({ scene, camera: typeof camera === 'function' ? camera() : camera }),
  createTool = createTransformHistoryTool, validateDisplay = validateTransformPreviewDisplay }) {
  let opening = false, boundOpening = false, ready = false, disposed = false, generation = 0
  let preview = null, tool = null, lastProjection = null, localError = null
  function context() {
    const state = store.getState(), design = state.currentDesign
    if (!design || state.assemblyActive) return null
    const loadoutId = design.active_loadout_id ?? null, loadout = design.loadouts?.find(item => item.id === loadoutId)
    return { docId: getDocumentId(), designId: design.id, revision: api.currentRevisionWatermark(), loadoutId,
      cursor: design.feature_log_cursor ?? -1, subCursor: design.feature_log_sub_cursor ?? null,
      editable: !loadout?.protected && !state.featureSeekPending && !state.cadnanoActive && !state.unfoldActive && !state.translateRotateActive }
  }
  const controller = createDeformationHistoryController({ api: previewAPI, family: 'transform', getContext: context, events,
    subscribeContext: callback => store.subscribe(callback),
    validateDisplay: (packet, options) => validateDisplay(packet, { ...options, requireEnvelope: true }),
    applyPublished: packet => api.syncDesignResponse(packet) })
  function teardown() {
    const ownedTool = tool, ownedPreview = preview
    ready = false; tool = preview = lastProjection = null
    try { ownedTool?.dispose() } finally { ownedPreview?.dispose() }
  }
  function render(state) {
    if (opening) {
      if (state.open) boundOpening = true
      else if (boundOpening) { generation++; opening = false; boundOpening = false }
    }
    if (!ready) return
    if (!state.open) { teardown(); return }
    if (state.projection && state.projection !== lastProjection) {
      try {
        preview.replaceCandidate(state.projection.candidate)
        preview.show(state.projection.candidate ? 'candidate' : 'before')
        tool.update(state.projection)
        lastProjection = state.projection; localError = null
      } catch (failure) { localError = failure; preview.show('before') }
    }
    tool.setStatus({ busy: state.busy, expired: state.expired, error: localError ?? state.error,
      publicationUnknown: state.publicationUnknown, refreshNeeded: state.refreshNeeded })
  }
  const unsubscribe = controller.subscribe(render)
  const resetOpening = () => {
    if (opening && !boundOpening) { generation++; opening = false }
  }
  const comparisonMode = event => {
    if (!['multi-view', 'multi-overlay'].includes(event.detail?.mode) || (!opening && !controller.getState().open)) return
    event.detail.waits.push(cancel().then(closed => {
      if (!closed) throw new Error('Resolve the saved result before changing comparison views')
    }))
  }
  events?.addEventListener('nadoc:document-reset', resetOpening)
  events?.addEventListener('nadoc:comparison-mode', comparisonMode)
  function change(patch, options) {
    if (!ready) return Promise.resolve(null)
    localError = null
    return controller.update(patch, options)
  }
  async function reset() {
    if (!ready) return null
    const token = generation
    const packet = await controller.resetDraft()
    if (packet && token === generation && ready) { localError = null; tool.reset?.(packet); render(controller.getState()) }
    return packet
  }
  async function apply() {
    const state = controller.getState()
    if (state.publicationUnknown) await controller.resolvePublication()
    else if (state.refreshNeeded) await controller.refreshCommitted()
    else if (!localError) await controller.apply()
    return !controller.getState().open
  }
  async function cancel() {
    await controller.cancel()
    const closed = !controller.getState().open
    if (closed && opening) { generation++; opening = false; boundOpening = false }
    return closed
  }
  async function open(entry) {
    const requestedContext = context()
    if (disposed || opening || controller.getState().open || !isNativeTransformFeature(entry) || !requestedContext?.editable) return false
    const token = ++generation
    opening = true; boundOpening = false; localError = null
    try {
      const waits = []
      events?.dispatchEvent(new CustomEvent('nadoc:comparison-mode', { detail: { mode: 'transform-history', waits } }))
      await Promise.all(waits)
      if (disposed || token !== generation || !sameRepairContext(requestedContext, context())) return false
      const packet = await controller.open(entry.id)
      if (disposed || token !== generation) return false
      if (!packet || !controller.getState().open) throw controller.getState().error ?? new Error('Preview is no longer current')
      preview = createPreview(); preview.open(packet)
      tool = createTool({ scene, camera: typeof camera === 'function' ? camera() : camera, canvas, controls,
        panel: getPanel(), preview, onChange: change, onReset: reset, onApply: apply, onCancel: cancel,
        onError: failure => { if (token === generation) { localError = failure; render(controller.getState()) } } })
      tool.open(packet); ready = true; lastProjection = packet; render(controller.getState())
      return true
    } catch (failure) {
      if (token !== generation) return false
      teardown(); await controller.cancel()
      if (!disposed) showToast(`Move/Rotate history unavailable: ${failure.message}`, 6000)
      return false
    } finally { if (token === generation) { opening = false; boundOpening = false } }
  }
  return { open, cancel, active: () => opening || controller.getState().open,
    dispose() { if (!disposed) {
      disposed = true; generation++; opening = false; unsubscribe(); controller.dispose(); teardown()
      events?.removeEventListener('nadoc:document-reset', resetOpening)
      events?.removeEventListener('nadoc:comparison-mode', comparisonMode)
    } } }
}
