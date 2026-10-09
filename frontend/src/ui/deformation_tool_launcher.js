import { canonicalSelection } from '../scene/selection_model.js'
import { deformationTargets } from '../scene/deformation_targets.js'
import { moveRotateSelectionLabels } from '../scene/move_rotate_panel.js'
import { startToolForSelection, exitTool, setDeformSessionTargets, waitForDeformationIdle } from '../scene/deformation_editor.js'
import { showSelectionPopup, setDeformationSelectionUI, closePopup } from './bend_twist_popup.js'
import { armToolClusterSelection } from './tool_cluster_selection.js'

/** Persistent selection → planes → parameters workflow, sharing canonical selection. */
export function initDeformationToolLauncher({
  store, selectionManager, showToast, deformView, watchDeformState,
  start = startToolForSelection, exit = exitTool, setScope = setDeformSessionTargets,
  waitForIdle = waitForDeformationIdle,
}) {
  let type = null, phase = 'selection', unsubscribe = null, resetting = false
  let finishClusterPick = null
  let selectionEpoch = 0, startError = null
  const cancel = () => {
    selectionEpoch++
    resetting = false
    type = null
    unsubscribe?.(); unsubscribe = null
    finishClusterPick?.(); finishClusterPick = null
    document.removeEventListener('keydown', escape, true)
    setDeformationSelectionUI(null)
    exit(); closePopup()
  }
  const escape = event => {
    if (phase !== 'selection' || event.key !== 'Escape' || event.defaultPrevented) return
    event.preventDefault(); event.stopPropagation(); cancel()
  }
  async function change(clear = false, autoStart = false) {
    if (!type || resetting) return
    resetting = true
    const epoch = ++selectionEpoch
    startError = null
    exit()
    await waitForIdle()
    if (epoch !== selectionEpoch || !type) return
    if (clear) selectionManager.clearSelection()
    phase = 'selection'; resetting = false
    if (type) {
      finishClusterPick?.()
      finishClusterPick = armToolClusterSelection({ store, selectionManager })
      showSelectionPopup(type); refresh()
      if (autoStart) scheduleStart()
    }
  }
  function scheduleStart() {
    const epoch = ++selectionEpoch
    // Let a complete click/lasso gesture settle before freezing its target set.
    queueMicrotask(() => {
      if (epoch !== selectionEpoch || !type || resetting || phase !== 'selection') return
      const current = deformationTargets(store.getState())
      if (current.error) return
      try {
        finishClusterPick?.(); finishClusterPick = null
        selectionManager.setSelectionLevel('default')
        setScope(current.targets)
        phase = 'planes'
        start(type); watchDeformState(); refresh()
      } catch (error) {
        phase = 'selection'
        exit()
        showSelectionPopup(type)
        startError = error.message
        showToast(startError, { severity: 'error' })
        refresh()
      }
    })
  }
  function refresh() {
    if (!type || resetting) return
    const state = store.getState(), resolved = deformationTargets(state)
    setDeformationSelectionUI({
      labels: moveRotateSelectionLabels(state),
      error: startError || resolved.error, phase,
      onClear: () => change(true), onChange: () => change(), onCancel: cancel,
    })
  }
  function open(nextType) {
    cancel()
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
      if (next.currentDesign?.id !== designId) { cancel(); return }
      if (resetting) return
      if (previous.deformToolActive && !next.deformToolActive && phase === 'planes') { cancel(); return }
      if (JSON.stringify(canonicalSelection(next).items) !== JSON.stringify(canonicalSelection(previous).items)) {
        startError = null
        if (phase === 'planes') void change(false, true)
        else { refresh(); scheduleStart() }
      }
    })
    document.addEventListener('keydown', escape, true)
    scheduleStart()
  }
  for (const kind of ['bend', 'twist']) document.getElementById(`menu-tools-${kind}`)?.addEventListener('click', () => open(kind))
  return { open, cancel }
}
