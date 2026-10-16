/** Wires the existing tools to one private, source-bound history editing session. */
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
  let opening = false, ready = false, tearingDown = false, disposed = false, visual = true
  let preview = null, lastProjection = null, localError = null
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
    if (!ready && !preview) return
    ready = false; tearingDown = true
    try {
      preview?.dispose(); preview = null; lastProjection = null
      popup.closePopup(); editor.finishHistoryTool(); setMode(null)
    } finally { tearingDown = false }
  }
  function render(state) {
    if (!ready) return
    if (!state.open) { teardown(); return }
    if (state.projection && state.projection !== lastProjection) {
      lastProjection = state.projection
      try {
        // Controls-only feedback means the prefix remains visible, never latest geometry.
        if (state.projection.candidate) {
          preview.replaceCandidate(state.projection.candidate); preview.show('candidate')
        } else {
          preview.show('before'); preview.replaceCandidate(null)
        }
        localError = null
      } catch (error) { localError = error }
    }
    popup.setHistoryPopupStatus({ busy: state.busy, expired: state.expired,
      error: localError ?? state.error, feasibility: state.projection?.feasibility ?? null,
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
    if (Object.keys(patch).length) {
      if (!await change(patch)) return false
    }
    if (localError) return false
    return publication(controller.apply)
  }
  async function cancel() {
    await controller.cancel()
    return !controller.getState().open
  }
  async function open(entry, index) {
    if (disposed || opening || controller.getState().open) return false
    opening = true; localError = null; visual = true
    try {
      const packet = await controller.open(entry?.id)
      if (!packet || disposed) throw controller.getState().error ?? new Error('Feature preview is no longer current')
      const controls = packet.control_context, operation = controls.selected_operation
      const design = { helices: controls.helices, strands: controls.strands,
        cluster_transforms: controls.cluster_transforms, deformations: controls.deformations, forced_ligations: controls.forced_ligations }
      const helixAxes = Object.fromEntries(packet.before.helix_axes.map(axis => [axis.helix_id,
        { start: axis.start, end: axis.end, samples: axis.samples, segments: axis.segments, ovhgAxes: axis.ovhg_axes ?? null }]))
      preview = createPreview(); preview.open(packet); lastProjection = packet; ready = true
      editor.startToolForHistory(operation, { design, helixAxes, displayLayer: DEFORMATION_PREVIEW_LAYER,
        onPreview: patch => change(patch), onConfirm: apply, onCancel: cancel })
      popup.openPopup(operation.type, operation.plane_a_bp, operation.plane_b_bp, operation.params,
        operation.cluster_ids, true, { design, operation, capabilities: controls.capabilities,
          onChange: change, onApply: apply, onCancel: cancel,
          onPlaneChanged: (which, bp) => editor.repositionPlane(which, bp),
          onResolvePublication: () => publication(controller.resolvePublication),
          onRefreshCommitted: () => publication(controller.refreshCommitted) })
      setMode(`EDIT ${operation.type.toUpperCase()} F${index + 1} — feature preview · Apply to rebuild · Esc to cancel`)
      render(controller.getState()); return true
    } catch (error) {
      teardown(); await controller.cancel()
      if (!disposed) showToast(`History edit unavailable: ${error.message}`, 6000)
      return false
    } finally { opening = false }
  }
  return { open, cancel,
    active: () => opening || controller.getState().open,
    onToolExit() { if (!tearingDown && ready) void cancel() },
    dispose() {
      if (disposed) return
      disposed = true; unsubscribe(); controller.dispose(); teardown()
    },
  }
}
