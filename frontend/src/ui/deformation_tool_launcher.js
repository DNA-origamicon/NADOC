import { canonicalSelection } from '../scene/selection_model.js'
import { deformationTargets } from '../scene/deformation_targets.js'
import { moveRotateSelectionLabels } from '../scene/move_rotate_panel.js'
import { startToolForSelection, exitTool, setDeformSessionTargets, waitForDeformationIdle } from '../scene/deformation_editor.js'
import { showSelectionPopup, setDeformationSelectionUI, closePopup } from './bend_twist_popup.js'
import { armToolClusterSelection } from './tool_cluster_selection.js'
import { hasOrganization } from '../scene/part_group_display.js'

const ORGANIZATION_UNAVAILABLE = 'Creating Bend / Twist on organized parts requires the owned preview workflow, which is not available yet. Existing deformations can be edited through isolated history editing when enabled.'

/** Persistent selection → planes → parameters workflow, sharing canonical selection. */
export function initDeformationToolLauncher({
  store, selectionManager, showToast, deformView, watchDeformState, ownedEditor = null,
  start = startToolForSelection, exit = exitTool, setScope = setDeformSessionTargets,
  waitForIdle = waitForDeformationIdle, events = globalThis.window,
}) {
  let type = null, phase = 'selection', unsubscribe = null, resetting = false
  let finishClusterPick = null
  let selectionEpoch = 0, startError = null
  const owned = () => !!ownedEditor
  function clearLocal() {
    selectionEpoch++; resetting = false; type = null
    unsubscribe?.(); unsubscribe = null
    finishClusterPick?.(); finishClusterPick = null
    document.removeEventListener('keydown', escape, true)
    events?.removeEventListener('nadoc:document-reset', reset)
    setDeformationSelectionUI(null); closePopup()
  }
  function cancel({ localOnly = false } = {}) {
    if (ownedEditor?.active() && !localOnly) {
      const epoch = ++selectionEpoch
      return Promise.resolve(ownedEditor.cancel()).then(closed => {
        if (closed !== true) return false
        if (epoch === selectionEpoch) clearLocal()
        return true
      })
    }
    const legacyTool = !owned()
    clearLocal()
    if (!localOnly && legacyTool) exit()
    return true
  }
  function reset() {
    if (ownedEditor) void ownedEditor.cancel()
    cancel({ localOnly: true })
  }
  const escape = event => {
    if (phase !== 'selection' || event.key !== 'Escape' || event.defaultPrevented) return
    event.preventDefault(); event.stopPropagation(); void cancel()
  }
  async function change(clear = false, autoStart = false) {
    if (!type || resetting) return
    resetting = true
    const epoch = ++selectionEpoch
    startError = null
    if (owned()) {
      const closed = await ownedEditor.cancel()
      if (epoch !== selectionEpoch || !type) return
      if (closed !== true) { resetting = false; refresh(); return }
    } else { exit(); await waitForIdle() }
    if (epoch !== selectionEpoch || !type) return
    if (clear) selectionManager.clearSelection()
    phase = 'selection'; resetting = false
    finishClusterPick?.()
    finishClusterPick = armToolClusterSelection({ store, selectionManager })
    showSelectionPopup(type); refresh()
    if (autoStart) scheduleStart()
  }
  function scheduleStart() {
    const epoch = ++selectionEpoch
    // Freeze only after a complete click/lasso gesture has settled.
    queueMicrotask(async () => {
      if (epoch !== selectionEpoch || !type || resetting || phase !== 'selection') return
      if (!ownedEditor && hasOrganization(store.getState().currentDesign)) {
        cancel({ localOnly: true }); organizationUnavailable(); return
      }
      const current = deformationTargets(store.getState())
      if (current.error) return
      try {
        finishClusterPick?.(); finishClusterPick = null
        selectionManager.setSelectionLevel('default')
        phase = 'planes'; refresh()
        if (owned()) {
          const opened = await ownedEditor.openCreation({ type, targets: current.targets,
            clusterIds: [...new Set(current.targets.filter(ref => ref.kind === 'cluster').map(ref => ref.id))],
            placementHint: { kind: 'selection' } })
          if (epoch !== selectionEpoch || !type) return
          if (!opened) throw new Error('The isolated deformation preview is unavailable. Review the source and selection.')
        } else { setScope(current.targets); start(type) }
        watchDeformState(); refresh()
      } catch (error) {
        if (epoch !== selectionEpoch || !type) return
        phase = 'selection'
        if (!owned()) exit()
        showSelectionPopup(type)
        startError = error.message
        showToast(startError, { severity: 'error' }); refresh()
      }
    })
  }
  function refresh() {
    if (!type || resetting) return
    const state = store.getState(), resolved = deformationTargets(state)
    setDeformationSelectionUI({ labels: moveRotateSelectionLabels(state),
      error: startError || resolved.error, phase,
      onClear: () => change(true), onChange: () => change(), onCancel: cancel })
  }
  function begin(nextType) {
    const state = store.getState()
    if (state.assemblyActive) { showToast('Not available in assembly mode.', { severity: 'error' }); return }
    if (!state.currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    if (!deformView.isActive() && state.currentDesign.deformations?.length) {
      showToast('Switch back to deformed view before adding further deformations.', { severity: 'error' }); return
    }
    type = nextType; phase = 'selection'; startError = null
    finishClusterPick = armToolClusterSelection({ store, selectionManager })
    showSelectionPopup(type); refresh()
    const designId = state.currentDesign.id
    unsubscribe = store.subscribe((next, previous) => {
      if (next.currentDesign?.id !== designId
          || (owned() && next.currentDesign !== previous.currentDesign)) { reset(); return }
      if (resetting) return
      if (previous.deformToolActive && !next.deformToolActive && phase === 'planes') { void cancel(); return }
      if (JSON.stringify(canonicalSelection(next).items) !== JSON.stringify(canonicalSelection(previous).items)) {
        startError = null
        if (phase === 'planes') void change(false, true)
        else { refresh(); scheduleStart() }
      }
    })
    document.addEventListener('keydown', escape, true)
    events?.addEventListener('nadoc:document-reset', reset)
    scheduleStart()
  }
  function open(nextType) {
    if (!ownedEditor && hasOrganization(store.getState().currentDesign)) { organizationUnavailable(); return }
    const stopped = cancel()
    if (stopped?.then) return stopped.then(closed => { if (closed) begin(nextType) })
    begin(nextType)
  }
  function organizationUnavailable() {
    showToast(ORGANIZATION_UNAVAILABLE, { severity: 'error' })
  }
  for (const kind of ['bend', 'twist']) document.getElementById(`menu-tools-${kind}`)?.addEventListener('click', () => open(kind))
  return { open, cancel }
}
