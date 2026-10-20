import { attributeFailure } from '../features/feature_history_failure.js'
import { createFeatureHistoryFeedback } from '../features/feature_history_feedback.js'
export { attributeFailure } from '../features/feature_history_failure.js'
/** One private, source-bound owner shared by creation and history editing. */
import { createDeformationHistoryController } from '../features/deformation_history_controller.js'
import { validateDeformationPreviewDisplay } from '../features/deformation_preview_display.js'
import { createDeformationPreviewEndpoints } from '../api/deformation_preview_endpoints.js'
import { createDeformationHistoryPreview } from '../scene/deformation_history_preview.js'
import { DEFORMATION_PREVIEW_LAYER } from '../scene/deformation_preview_camera.js'
import { getDocId } from '../shared/doc_id.js'

export function createDeformationHistoryEditor({ store, api, scene, camera, designRenderer,
  editor, popup, showToast, setMode = () => {}, getDocumentId = getDocId,
  previewAPI = createDeformationPreviewEndpoints({ request: api._request }),
  createPreview = () => createDeformationHistoryPreview({ scene, camera, getLiveRoot: () => designRenderer.getHelixCtrl()?.root }),
  validateDisplay = validateDeformationPreviewDisplay, events = globalThis.window }) {
  let opening = false, openingBound = false, ready = false, tearingDown = false, disposed = false, visual = true, generation = 0
  let preview = null, lastProjection = null, localError = null, creationSession = null, lastToolState = null
  let editedFeatureId = null
  const feedback = createFeatureHistoryFeedback(store, events)
  function getContext() {
    const state = store.getState(), design = state.currentDesign
    if (!design || state.assemblyActive) return null
    const loadoutId = design.active_loadout_id ?? null
    const loadout = design.loadouts?.find(item => item.id === loadoutId)
    return { docId: getDocumentId(), designId: design.id, revision: api.currentRevisionWatermark(), loadoutId,
      cursor: design.feature_log_cursor ?? -1, subCursor: design.feature_log_sub_cursor ?? null,
      editable: !loadout?.protected && !state.featureSeekPending && !state.cadnanoActive && !state.unfoldActive }
  }
  const controller = createDeformationHistoryController({ api: previewAPI, getContext, events,
    subscribeContext: callback => store.subscribe(callback),
    validateDisplay: (value, options) => validateDisplay(value, { ...options, requireEnvelope: true }),
    applyPublished: value => api.syncDesignResponse(value) })

  function teardown() {
    feedback.clear()
    if (!ready && !preview) return
    ready = false; tearingDown = true; creationSession = null; lastToolState = null
    try {
      preview?.dispose(); preview = null; lastProjection = null
      popup.closePopup(); editor.finishHistoryTool(); setMode(null)
    } finally { tearingDown = false }
  }
  function render(state) {
    // The controller first invalidates an old binding when Open starts. Only a
    // subsequent open→closed transition retires this pending owner generation.
    if (opening) {
      if (state.open) openingBound = true
      else if (openingBound) { generation++; opening = false; openingBound = false }
    }
    if (!ready) return
    if (!state.open) { teardown(); return }
    if (state.projection && state.projection !== lastProjection) {
      lastProjection = state.projection
      try {
        if (state.projection.candidate) {
          preview.replaceCandidate(state.projection.candidate); preview.show('candidate')
        } else {
          preview.show('before'); preview.replaceCandidate(null)
        }
        editor.updateHistoryScope(state.projection.selected_scope)
        localError = null
      } catch (error) { localError = error }
    }
    feedback.update(state.busy ? null : state.error)
    popup.setHistoryPopupStatus({ busy: state.busy, expired: state.expired,
      awaitingParameters: state.awaitingParameters,
      error: localError ?? attributeFailure(state.error, store.getState().currentDesign, editedFeatureId), feasibility: state.projection?.feasibility ?? null,
      publicationUnknown: state.publicationUnknown, refreshNeeded: state.refreshNeeded })
  }
  const unsubscribe = controller.subscribe(render)
  async function change(patch, options = {}) {
    if (!ready) return null
    visual = options.includeGeometry ?? visual
    if (!visual) preview.show('before')
    return controller.update(patch, { includeGeometry: visual })
  }
  async function publication(operation) {
    await operation()
    return !controller.getState().open
  }
  async function apply(patch = {}) {
    const state = controller.getState()
    if (state.publicationUnknown) return publication(controller.resolvePublication)
    if (state.refreshNeeded) return publication(controller.refreshCommitted)
    if (Object.keys(patch).length && !await change(patch)) return false
    if (localError) return false
    return publication(controller.apply)
  }
  async function cancel() {
    const wasOpening = opening
    await controller.cancel()
    const closed = !controller.getState().open
    if (closed && wasOpening) { generation++; opening = false }
    return closed
  }
  function controls(packet) {
    const c = packet.control_context
    const design = { helices: c.helices, strands: c.strands,
      cluster_transforms: c.cluster_transforms, group_organization: c.group_organization,
      deformations: c.deformations, forced_ligations: c.forced_ligations }
    const helixAxes = Object.fromEntries(packet.before.helix_axes.map(axis => [axis.helix_id,
      { start: axis.start, end: axis.end, samples: axis.samples, segments: axis.segments, ovhgAxes: axis.ovhg_axes ?? null }]))
    return { design, helixAxes }
  }
  function session(design, capabilities, extra) {
    return { design, capabilities, ...extra, onChange: change, onApply: apply, onCancel: cancel,
      onPlaneChanged: (which, bp) => editor.repositionPlane(which, bp),
      onResolvePublication: () => publication(controller.resolvePublication),
      onRefreshCommitted: () => publication(controller.refreshCommitted) }
  }
  function watchToolState() {
    if (!opening && !controller.getState().open) return false
    if (!ready || !creationSession) return true
    const state = editor.getState(), planes = editor.getPlanes()
    if (state === lastToolState) return true
    lastToolState = state
    const creation = creationSession.creation
    if (state === 'BOTH') {
      popup.openPopup(creation.type, planes.a.bp, planes.b.bp, null, creation.cluster_ids, false, creationSession)
      render(controller.getState())
    } else if (state === 'AWAITING_A' || state === 'A_PLACED') {
      popup.showPickingPopup(creation.type, planes.a?.bp ?? null, creationSession)
      render(controller.getState())
    }
    return true
  }
  async function openPrepared(prepare, configure, label) {
    if (disposed || opening || controller.getState().open) return false
    const token = ++generation
    opening = true; openingBound = false; localError = null; visual = true
    try {
      const packet = await prepare()
      if (token !== generation || disposed) return false
      if (!packet || !controller.getState().open) throw controller.getState().error ?? new Error('Preview is no longer current')
      const context = controls(packet)
      preview = createPreview(); preview.open(packet); lastProjection = packet; ready = true
      configure(packet, context)
      render(controller.getState()); return true
    } catch (error) {
      if (token !== generation) return false
      teardown(); await controller.cancel()
      if (disposed) return false
      showToast(`${label} unavailable: ${error.message}`, 6000)
      return false
    } finally { if (token === generation) { opening = false; openingBound = false } }
  }
  function open(entry, index) {
    editedFeatureId = entry?.id ?? null
    return openPrepared(() => controller.open(entry?.id), (packet, { design, helixAxes }) => {
      const operation = packet.control_context.selected_operation
      editor.startToolForHistory(operation, { design, helixAxes, displayLayer: DEFORMATION_PREVIEW_LAYER,
        onPreview: patch => change(patch), onConfirm: apply, onCancel: cancel })
      popup.openPopup(operation.type, operation.plane_a_bp, operation.plane_b_bp, operation.params,
        operation.cluster_ids, true, session(design, packet.control_context.capabilities, { operation }))
      setMode(`EDIT ${operation.type.toUpperCase()} F${index + 1} — feature preview · Apply to rebuild · Esc to cancel`)
    }, 'History edit')
  }
  function openCreation({ type, targets, clusterIds = [], placementHint = null } = {}) {
    editedFeatureId = null
    return openPrepared(() => controller.openCreation({ type, targets, clusterIds }), (packet, { design, helixAxes }) => {
      const creation = { ...packet.control_context.creation, id: packet.deformation_id }
      creationSession = session(design, packet.control_context.capabilities, { mode: 'create', creation })
      editor.startToolForCreation(creation, { design, helixAxes, selectedScope: packet.selected_scope,
        displayLayer: DEFORMATION_PREVIEW_LAYER, onPreview: patch => change(patch), onConfirm: apply,
        onCancel: cancel, onStateChange: watchToolState }, placementHint)
      watchToolState()
      setMode(`NEW ${creation.type.toUpperCase()} — isolated preview · Apply to add · Esc to cancel`)
    }, 'Deformation creation')
  }
  return { open, openCreation, watchToolState, cancel,
    active: () => opening || controller.getState().open,
    onToolExit() { if (!tearingDown && ready) void cancel() },
    dispose() {
      if (disposed) return
      disposed = true; generation++; opening = false
      unsubscribe(); controller.dispose(); teardown(); feedback.dispose()
    },
  }
}
