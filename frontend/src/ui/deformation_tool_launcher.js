import { canonicalSelection } from '../scene/selection_model.js'
import { deformationTargets } from '../scene/deformation_targets.js'
import { moveRotateSelectionLabels } from '../scene/move_rotate_panel.js'
import { startTool, exitTool, setDeformSessionTargets, waitForDeformationIdle } from '../scene/deformation_editor.js'
import { showSelectionPopup, setDeformationSelectionUI, closePopup } from './bend_twist_popup.js'

/** Persistent selection → planes → parameters workflow, sharing canonical selection. */
export function initDeformationToolLauncher({
  store, selectionManager, showToast, deformView, watchDeformState,
  start = startTool, exit = exitTool, setScope = setDeformSessionTargets,
  waitForIdle = waitForDeformationIdle,
}) {
  let type = null, phase = 'selection', unsubscribe = null, resetting = false
  const cancel = () => {
    type = null
    unsubscribe?.(); unsubscribe = null
    document.removeEventListener('keydown', escape, true)
    setDeformationSelectionUI(null)
    exit(); closePopup()
  }
  const escape = event => {
    if (phase !== 'selection' || event.key !== 'Escape' || event.defaultPrevented) return
    event.preventDefault(); event.stopPropagation(); cancel()
  }
  async function change(clear = false) {
    if (!type || resetting) return
    resetting = true
    exit()
    await waitForIdle()
    if (clear) selectionManager.clearSelection()
    phase = 'selection'; resetting = false
    if (type) { showSelectionPopup(type); refresh() }
  }
  function refresh() {
    if (!type || resetting) return
    const state = store.getState(), resolved = deformationTargets(state)
    setDeformationSelectionUI({
      labels: moveRotateSelectionLabels(state),
      error: resolved.error, phase,
      onClear: () => change(true), onChange: () => change(), onCancel: cancel,
      onPick: () => {
        const current = deformationTargets(store.getState())
        if (current.error) return
        setScope(current.targets)
        phase = 'planes'
        start(type); watchDeformState(); refresh()
      },
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
    type = nextType; phase = 'selection'
    showSelectionPopup(type); refresh()
    const designId = state.currentDesign.id
    unsubscribe = store.subscribe((next, previous) => {
      if (next.currentDesign?.id !== designId) { cancel(); return }
      if (resetting) return
      if (previous.deformToolActive && !next.deformToolActive && phase === 'planes') { cancel(); return }
      if (JSON.stringify(canonicalSelection(next).items) !== JSON.stringify(canonicalSelection(previous).items)) {
        if (phase === 'planes') void change()
        else refresh()
      }
    })
    document.addEventListener('keydown', escape, true)
  }
  for (const kind of ['bend', 'twist']) document.getElementById(`menu-tools-${kind}`)?.addEventListener('click', () => open(kind))
  return { open, cancel }
}
