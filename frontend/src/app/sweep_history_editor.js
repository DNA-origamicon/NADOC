/** Owns Sweep history display and controls; canonical publication is controller-only. */
import { createDeformationHistoryController } from '../features/deformation_history_controller.js'
import { createDeformationPreviewEndpoints } from '../api/deformation_preview_endpoints.js'
import { validateSweepPreviewDisplay } from '../features/sweep_preview_display.js'
import { createDeformationHistoryPreview } from '../scene/deformation_history_preview.js'
import { DEFORMATION_PREVIEW_LAYER } from '../scene/deformation_preview_camera.js'
import { getDocId } from '../shared/doc_id.js'

export const SWEEP_HISTORY_EDITOR_ENABLED = false
export const isNativeSweepFeature = entry => entry?.feature_type === 'snapshot' && entry.op_kind === 'sweep'
  && entry.params?._proof_version === 1 && typeof entry.params.sweep_id === 'string' && !!entry.params.sweep_id
  && !Object.hasOwn(entry.params, '_generator') && !Object.hasOwn(entry.params, '_generated_scope')

export function createSweepHistoryEditor({ store, api, scene, camera, view, slicePlane,
  getDocumentId = getDocId, showToast = () => {}, events = globalThis.window,
  previewAPI = createDeformationPreviewEndpoints({ request: api._request, family: 'sweep' }),
  createPreview = () => createDeformationHistoryPreview({ scene, camera: typeof camera === 'function' ? camera() : camera }),
  validateDisplay = validateSweepPreviewDisplay }) {
  let opening = false, boundOpening = false, ready = false, disposed = false, generation = 0
  let preview = null, release = null, lastProjection = null, localError = null
  function context() {
    const state = store.getState(), design = state.currentDesign
    if (!design || state.assemblyActive) return null
    const loadoutId = design.active_loadout_id ?? null, loadout = design.loadouts?.find(item => item.id === loadoutId)
    return { docId: getDocumentId(), designId: design.id, revision: api.currentRevisionWatermark(), loadoutId,
      cursor: design.feature_log_cursor ?? -1, subCursor: design.feature_log_sub_cursor ?? null,
      editable: !loadout?.protected && !state.featureSeekPending && !state.cadnanoActive && !state.unfoldActive }
  }
  const controller = createDeformationHistoryController({ api: previewAPI, getContext: context, events,
    subscribeContext: callback => store.subscribe(callback),
    validateDisplay: (packet, options) => validateDisplay(packet, { ...options, requireEnvelope: true }),
    applyPublished: packet => api.syncDesignResponse(packet) })
  function teardown() {
    if (!ready && !preview && !release) return
    const ownedRelease = release, ownedPreview = preview
    ready = false; release = preview = lastProjection = null
    try { view.close() }
    finally { try { ownedRelease?.() } finally { ownedPreview?.dispose() } }
  }
  function render(state) {
    if (opening) {
      if (state.open) boundOpening = true
      else if (boundOpening) { generation++; opening = false; boundOpening = false }
    }
    if (!ready) return
    if (!state.open) { teardown(); return }
    if (state.projection && state.projection !== lastProjection) {
      lastProjection = state.projection
      try {
        preview.replaceCandidate(state.projection.candidate)
        preview.show(state.projection.candidate ? 'candidate' : 'before')
        view.updatePreview(state.projection.sweep_preview)
        localError = null
      } catch (failure) { localError = failure; preview.show('before') }
    }
    view.setStatus({ busy: state.busy, expired: state.expired, error: localError ?? state.error,
      publicationUnknown: state.publicationUnknown, refreshNeeded: state.refreshNeeded,
      feasibility: state.projection?.sweep_preview?.feasibility })
  }
  const unsubscribe = controller.subscribe(render)
  async function change(patch, options = {}) {
    if (!ready) return null
    if (options.includeGeometry === false) preview.show('before')
    return controller.update(patch, options)
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
    if (closed && opening) { generation++; opening = false }
    return closed
  }
  async function open(entry) {
    if (disposed || opening || controller.getState().open) return false
    const token = ++generation
    opening = true; boundOpening = false; localError = null
    try {
      const packet = await controller.open(entry?.id)
      if (disposed || token !== generation) return false
      if (!packet || !controller.getState().open) throw controller.getState().error ?? new Error('Preview is no longer current')
      const c = packet.control_context
      const design = { ...packet.before.display_topology, helices: c.helices, lattice_frames: c.lattice_frames, lattice_type: c.lattice_type }
      const helixAxes = Object.fromEntries(packet.before.helix_axes.map(axis => [axis.helix_id,
        { start: axis.start, end: axis.end, samples: axis.samples, segments: axis.segments, ovhgAxes: axis.ovhg_axes ?? null }]))
      preview = createPreview(); preview.open(packet)
      const pickerLease = slicePlane.usePrivateContext({ design, helixAxes, displayLayer: DEFORMATION_PREVIEW_LAYER })
      release = pickerLease
      ready = true
      view.open(c.inputs, { design, helixAxes, displayLayer: DEFORMATION_PREVIEW_LAYER,
        isPickerCurrent: () => pickerLease.isCurrent?.() !== false,
        onChange: change, onApply: apply, onCancel: cancel })
      lastProjection = null; render(controller.getState())
      return true
    } catch (failure) {
      if (token !== generation) return false
      teardown(); await controller.cancel()
      if (!disposed) showToast(`Sweep history unavailable: ${failure.message}`, 6000)
      return false
    } finally { if (token === generation) { opening = false; boundOpening = false } }
  }
  return { open, cancel, active: () => opening || controller.getState().open,
    dispose() { if (!disposed) { disposed = true; generation++; opening = false; unsubscribe(); controller.dispose(); teardown() } } }
}
