import * as api from '../api/client.js'
import { store } from '../state/store.js'
import { createDeformationHistoryEditor } from './deformation_history_editor.js'
import { createTransformHistoryEditor, isNativeTransformFeature, TRANSFORM_HISTORY_EDITOR_ENABLED } from './transform_history_editor.js'
import {
  initDeformationEditor, previewDeformation, confirmDeformation,
  exitTool as deformExitTool, getPlanes as getDeformPlanes,
  repositionPlane as repositionDeformPlane,
  getState as getDeformState, getToolType as getDeformToolType,
  startToolForHistory, startToolForCreation, finishHistoryTool, updateHistoryScope,
  STATES as DEFORM_STATES,
} from '../scene/deformation_editor.js'
import {
  showPickingPopup, initBendTwistPopup, openPopup as openDeformPopup,
  closePopup as closeDeformPopup, setPlanePositions as setDeformPopupPlanes,
  setHistoryPopupStatus,
} from '../ui/bend_twist_popup.js'

// Ordinary Bend/Twist creation and history use isolated previews exclusively.
export const ISOLATED_DEFORMATION_HISTORY_ENABLED = true
export const ISOLATED_DEFORMATION_CREATION_ENABLED = true

/** Owns deformation feature creation/editing and popup synchronization. */
export function initFeatureEditor({
  scene, camera, canvas, controls, designRenderer,
  seekFeaturesWithDelta, showToast, getOrientPanel,
  activateTranslateRotateTool, isolatedHistoryEnabled = ISOLATED_DEFORMATION_HISTORY_ENABLED,
  isolatedCreationEnabled = ISOLATED_DEFORMATION_CREATION_ENABLED,
  getMoveRotatePanel, isolatedTransformEnabled = TRANSFORM_HISTORY_EDITOR_ENABLED,
}) {
  // Context set while editing an existing feature; cleared on confirm or cancel.
  let _editContext = null  // { priorCursor, pendingParams }
  const transformHistory = isolatedTransformEnabled ? createTransformHistoryEditor({
    store, api, scene, camera, canvas, controls, getPanel: getMoveRotatePanel, showToast,
  }) : null
  const history = (isolatedHistoryEnabled || isolatedCreationEnabled) ? createDeformationHistoryEditor({
    store, api, scene, camera, designRenderer, showToast,
    editor: { startToolForHistory, startToolForCreation, finishHistoryTool, updateHistoryScope, repositionPlane: repositionDeformPlane,
      getState: getDeformState, getPlanes: getDeformPlanes },
    popup: { openPopup: openDeformPopup, showPickingPopup, closePopup: closeDeformPopup, setHistoryPopupStatus },
    setMode: value => { const node = document.getElementById('mode-indicator'); if (node) node.textContent = value ?? 'NADOC · WORKSPACE' },
  }) : null

  initDeformationEditor(scene, camera, canvas, controls, designRenderer,
    () => {
      if (history?.active()) { history.onToolExit(); return }
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      _editContext = null
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
      _editContext = null   // clear before confirm; addDeformation takes over
      await confirmDeformation(params)
      _watchDeformState()
    },
    onCancel: () => {
      deformExitTool()
      _watchDeformState()
    },
    onPlaneChanged: (which, bp) => repositionDeformPlane(which, bp),
  })

  // Watch deformation editor state — open/close popup when state changes
  let _prevDeformState = DEFORM_STATES.IDLE
  let _prevDeformType = null
  function _watchDeformState() {
    if (history?.watchToolState()) return
    const st = getDeformState()
    const type = getDeformToolType()
    if (st === _prevDeformState && type === _prevDeformType) return
    _prevDeformState = st
    _prevDeformType = type
    if (st === DEFORM_STATES.BOTH) {
      const { a, b } = getDeformPlanes()
      const editParams = _editContext?.pendingParams ?? null
      const editClusterIds = _editContext ? (_editContext.clusterIds ?? []) : null
      // Owned history popups supply their own callbacks and preview state.
      const skipInitialPreview = false
      openDeformPopup(
        getDeformToolType() ?? 'twist',
        a?.bp ?? 0, b?.bp ?? 0,
        editParams,
        editClusterIds,
        skipInitialPreview,
      )
      if (_editContext) delete _editContext.pendingParams
    } else if (st === DEFORM_STATES.AWAITING_A || st === DEFORM_STATES.A_PLACED) {
      showPickingPopup(type ?? 'twist', getDeformPlanes().a?.bp ?? null)
    } else {
      closeDeformPopup()
    }
  }

  const unsubscribe = store.subscribe((next, previous) => {
    if (next.deformToolActive !== previous.deformToolActive) {
      _watchDeformState()
      // End/context entry points place both planes synchronously after activation.
      queueMicrotask(_watchDeformState)
    }
  })

  async function _onEditFeature(entry, featureIndex) {
    if (history?.active() || transformHistory?.active()) { showToast('Finish the current feature edit before opening another', 4000); return }
    if (transformHistory && isNativeTransformFeature(entry)) {
      if (getDeformState() !== DEFORM_STATES.IDLE || _editContext) {
        showToast('Finish the current tool before editing feature history', 4000); return
      }
      return transformHistory.open(entry)
    }
    if (isolatedHistoryEnabled && history && entry.feature_type === 'deformation') {
      if (getDeformState() !== DEFORM_STATES.IDLE || _editContext) {
        showToast('Finish the current tool before editing feature history', 4000); return
      }
      return history.open(entry, featureIndex)
    }
    // ── Overhang orientation edit — open orientation panel for this overhang ─
    if (entry.feature_type === 'overhang_rotation') {
      const ovhgIds = entry.overhang_ids
      if (!ovhgIds?.length) return
      getOrientPanel().open(ovhgIds)
      return
    }

    // ── Move/rotate (cluster_op) edit — highlight cluster and open tool ─────
    if (entry.feature_type === 'cluster_op') {
      if (store.getState().currentDesign?.group_organization != null) {
        showToast('Earlier placement editing needs the isolated history editor. Select a Placement to record a new move.', 5000)
        return
      }
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

    if (entry.feature_type === 'deformation') {
      showToast('Deformation history editing is unavailable. The part has not been changed.', 5000)
      return false
    }
  }
  return {
    creationEditor: isolatedCreationEnabled ? history : null,
    onEditFeature: _onEditFeature,
    watchDeformState: _watchDeformState,
    getEditContext: () => _editContext,
    setEditContext: value => { _editContext = value },
    dispose() { unsubscribe(); history?.dispose(); transformHistory?.dispose() },
  }
}
