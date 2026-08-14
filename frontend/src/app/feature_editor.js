import * as api from '../api/client.js'
import { store } from '../state/store.js'
import {
  initDeformationEditor, previewDeformation, confirmDeformation,
  exitTool as deformExitTool, getPlanes as getDeformPlanes,
  repositionPlane as repositionDeformPlane,
  getState as getDeformState, getToolType as getDeformToolType,
  startToolForEdit as startDeformToolForEdit,
  markEditCommitted as markDeformEditCommitted,
  STATES as DEFORM_STATES,
} from '../scene/deformation_editor.js'
import {
  initBendTwistPopup, openPopup as openDeformPopup,
  closePopup as closeDeformPopup, setPlanePositions as setDeformPopupPlanes,
} from '../ui/bend_twist_popup.js'

/** Owns deformation feature creation/editing and popup synchronization. */
export function initFeatureEditor({
  scene, camera, canvas, controls, designRenderer,
  seekFeaturesWithDelta, showToast, getOrientPanel,
  activateTranslateRotateTool,
}) {
  // Context set while editing an existing feature; cleared on confirm or cancel.
  let _editContext = null  // { priorCursor, pendingParams }

  initDeformationEditor(scene, camera, canvas, controls, designRenderer,
    () => {
      // onExit: restore mode indicator + (for an unconfirmed edit) restore
      // the original op that _onEditFeature peeled off the design.
      //
      // The deformation editor's preview-op DELETE already happened inside
      // _exitTool → _clearPreviewSession. But the ORIGINAL op was peeled off
      // separately by _onEditFeature, so design.deformations is missing it
      // until we replay the log. A seek to priorCursor handles that — the
      // backend re-runs the log and the original op pops back with its
      // original params. Triggered when _editContext is still set on exit
      // (Cancel / Escape paths). onConfirm clears _editContext BEFORE
      // exiting, so the seek-restore is skipped on the confirm path
      // (editFeature already updated the log and rebuilt design.deformations).
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      const ctx = _editContext
      _editContext = null
      if (ctx?.editingFeatureType === 'deformation' && ctx.origOpId) {
        seekFeaturesWithDelta(ctx.priorCursor ?? -1).catch(() => {})
      }
    },
    () => {
      // onPlaneDragEnd: sync popup inputs with dragged plane positions
      const { a, b } = getDeformPlanes()
      setDeformPopupPlanes(a?.bp ?? 0, b?.bp ?? 0)
    },
  )

  initBendTwistPopup({
    onPreview: (params) => previewDeformation(params),
    onConfirm: async (params) => {
      const ctx = _editContext
      if (ctx?.featureIndex != null && ctx.editingFeatureType === 'deformation') {
        // Edit-confirm: the bent GHOST is currently held by a preview op
        // (added by previewDeformation while the original op was peeled off
        // in _onEditFeature). editFeature updates the log entry's snapshot
        // and rebuilds design.deformations from the log — the backend
        // explicitly drops any preview op as part of that rebuild
        // (see backend _edit_deformation_feature). So a single editFeature
        // call commits the new params and cleans the overlay in one shot.
        const planes = getDeformPlanes()
        const bpA = planes.a?.bp ?? 0
        const bpB = planes.b?.bp ?? 0
        const editBody = {
          type:       getDeformToolType() ?? 'twist',
          plane_a_bp: Math.min(bpA, bpB),
          plane_b_bp: Math.max(bpA, bpB),
          params,
          cluster_ids: ctx.clusterIds ?? [],
        }
        markDeformEditCommitted()   // so the exit below does NOT revert the op
        const resp = await api.editFeature(ctx.featureIndex, editBody)
        if (resp == null) {
          showToast(`Edit failed: ${store.getState().lastError?.message ?? 'unknown error'}`, 4000)
        } else if (ctx.priorCursor != null && ctx.priorCursor !== -1) {
          // editFeature leaves the cursor at latest; if the user was mid-scrub
          // when they hit edit, return the slider to where they were.
          await seekFeaturesWithDelta(ctx.priorCursor)
        }
        _editContext = null
        deformExitTool()
        _watchDeformState()
        return
      }
      _editContext = null   // clear before confirm; addDeformation takes over
      await confirmDeformation(params)
      _watchDeformState()
    },
    onCancel: () => {
      // For an edit-cancel, leave _editContext set so onExit (called below
      // via deformExitTool → _exitTool) sees it and restores the original
      // op via seek. Escape goes through the same _exitTool path with the
      // same restore. New-op cancels (no _editContext) just exit cleanly.
      deformExitTool()
      _watchDeformState()
    },
    onPlaneChanged: (which, bp) => repositionDeformPlane(which, bp),
  })

  // Watch deformation editor state — open/close popup when state changes
  let _prevDeformState = DEFORM_STATES.IDLE
  function _watchDeformState() {
    const st = getDeformState()
    if (st === _prevDeformState) return
    _prevDeformState = st
    if (st === DEFORM_STATES.BOTH) {
      const { a, b } = getDeformPlanes()
      const editParams = _editContext?.pendingParams ?? null
      const editClusterIds = _editContext ? (_editContext.clusterIds ?? []) : null
      // Edit mode now uses the preview-op flow (the original op was peeled off
      // in _onEditFeature). Let the initial preview fire so the popup's first
      // previewDeformation call lands beginDeformPreview (SOLID = un-deformed)
      // and adds the bent overlay (GHOST = deformed). The new-deformation
      // path obviously also wants the initial preview.
      const skipInitialPreview = false
      openDeformPopup(
        getDeformToolType() ?? 'twist',
        a?.bp ?? 0, b?.bp ?? 0,
        editParams,
        editClusterIds,
        skipInitialPreview,
      )
      if (_editContext) delete _editContext.pendingParams
    } else {
      closeDeformPopup()
    }
  }

  async function _onEditFeature(entry, featureIndex) {
    // ── Overhang orientation edit — open orientation panel for this overhang ─
    if (entry.feature_type === 'overhang_rotation') {
      const ovhgIds = entry.overhang_ids
      if (!ovhgIds?.length) return
      getOrientPanel().open(ovhgIds)
      return
    }

    // ── Move/rotate (cluster_op) edit — highlight cluster and open tool ─────
    if (entry.feature_type === 'cluster_op') {
      const clusterId = entry.cluster_id
      if (!clusterId) return
      // Editing an EARLIER op (a later cluster_op for this cluster exists): seek
      // the feature log to this op first so the cluster shows THIS step's pose
      // while you adjust it; commit/cancel seeks back to where the cursor was
      // (the latest pose). Only this step's pose is rewritten — the latest op
      // keeps defining the final pose. Editing the latest op needs no seek (the
      // live pose already == that op), preserving the in-place edit path.
      const log = store.getState().currentDesign?.feature_log ?? []
      const hasLater = log.slice(featureIndex + 1).some(e =>
        e.feature_type === 'cluster_op' && e.cluster_id === clusterId)
      let seekRestoreCursor = null
      if (hasLater) {
        seekRestoreCursor = store.getState().currentDesign?.feature_log_cursor ?? -1
        await api.seekFeatures(featureIndex)
      }
      store.setState({ activeClusterId: clusterId })
      await activateTranslateRotateTool()
      // Mark cluster_op edit in flight; _confirmTranslateRotateTool will
      // route the apply through api.editFeature instead of patchCluster, so
      // the existing log entry is updated rather than a new one appended.
      _editContext = {
        editingFeatureType: 'cluster_op',
        featureIndex,
        clusterId,
        seekRestoreCursor,
      }
      return
    }

    const op = entry.op_snapshot
    if (!op) return

    const design = store.getState().currentDesign
    const priorCursor = design?.feature_log_cursor ?? -1

    // Edit flow: peel the original op off the design (silent DELETE preview=true)
    // so the live geometry becomes the pre-op (un-deformed) state. The popup's
    // first previewDeformation then freezes THAT as the SOLID reference and
    // re-adds the op as a preview overlay (the bent GHOST), restoring the
    // "before/after" visual comparison that's most useful when tuning bends.
    // The original log entry is untouched; Apply commits the new params via
    // editFeature(featureIndex, …) and the design rebuilds from the log;
    // Cancel deletes the preview overlay and seeks to priorCursor, replaying
    // the log to restore the original op with its original params.
    _editContext = {
      priorCursor,
      pendingParams:    op.params,
      featureIndex,
      editingFeatureType: entry.feature_type,
      clusterIds:       op.cluster_ids ?? [],
      // Original op id captured so cancel can no-op-restore it via the log
      // replay; the deformation editor's preview-op flow takes ownership of
      // the design from here.
      origOpId: op.id,
    }

    // Transient DELETE — exposes the un-deformed design under the bent overlay.
    let peeled = false
    try {
      const resp = await api.deleteDeformation(op.id, /*preview=*/true)
      peeled = resp != null
    } catch {
      // Non-fatal: if the delete fails the user falls back to the old in-place
      // edit (bent solid, no ghost). Without `peeled` the seek-restore below
      // is also skipped so the editor doesn't replay the log unnecessarily.
    }
    if (!peeled) _editContext.origOpId = null

    // Open editor in NEW-OP (preview) flow — _editOpId stays null so the
    // popup's first previewDeformation goes through addDeformation(preview=true),
    // producing a fresh preview op that owns the bent GHOST layer.
    startDeformToolForEdit(op.type, op.plane_a_bp, op.plane_b_bp, /*opId=*/null, op.params)

    document.getElementById('mode-indicator').textContent =
      `EDIT ${op.type.toUpperCase()} F${featureIndex + 1} — adjust params · Apply to save · Esc to cancel`

    // Open the popup now rather than waiting for a canvas pointerdown to fire it.
    _watchDeformState()
  }
  return {
    onEditFeature: _onEditFeature,
    watchDeformState: _watchDeformState,
    getEditContext: () => _editContext,
    setEditContext: value => { _editContext = value },
  }
}
