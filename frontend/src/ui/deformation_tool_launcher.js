import { beginClusterSelection } from './tool_cluster_selection.js'
import { createToolPopup } from './tool_popup.js'
import { el } from './primitives/dom.js'
import { startTool, exitTool, setDeformSessionClusterIds } from '../scene/deformation_editor.js'

/** Menu entry: select one cluster before enabling the deformation plane picker. */
export function initDeformationToolLauncher({
  store, selectionManager, showToast, deformView, watchDeformState,
  start = startTool, exit = exitTool, setScope = setDeformSessionClusterIds,
}) {
  let pending = null, popup = null
  const cancel = () => {
    pending?.cancel(); pending = null
    popup?.dispose(); popup = null
    document.removeEventListener('keydown', escape, true)
  }
  const escape = event => {
    if (event.key !== 'Escape' || event.defaultPrevented || document.querySelector('.modal__overlay')) return
    event.preventDefault(); event.stopPropagation(); cancel()
  }
  function open(type) {
    cancel()
    const state = store.getState()
    if (state.assemblyActive) { showToast('Not available in assembly mode.', { severity: 'error' }); return }
    if (!state.currentDesign?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
    if (!deformView.isActive() && state.currentDesign.deformations?.length) {
      showToast('Switch back to deformed view (View → Deformed View) before adding further deformations.', { severity: 'error' }); return
    }
    if (!state.currentDesign.cluster_transforms?.length) {
      showToast('Create a cluster before bending or twisting.', { severity: 'info' }); return
    }
    exit()
    const panel = el('div', { id: 'deformation-cluster-picker', className: 'ox-card__body', children: [
      el('p', { className: 'tool-picking-hint', text: 'Select a cluster', attrs: { title: 'Pick a cluster in the 3D view or cluster list. Selection returns to Default automatically.' } }),
      el('button', { className: 'btn btn--sm', text: 'Cancel', attrs: { type: 'button' }, on: { click: cancel } }),
    ] })
    popup = createToolPopup({ panel, title: type === 'bend' ? 'Bend' : 'Twist', onClose: cancel })
    popup.show()
    pending = beginClusterSelection({ store, selectionManager, onCancelled: cancel, onSelected: cluster => {
      cancel()
      // The editor owns its scope independently of Move/Rotate's active marker.
      // Leaving that marker set makes the cluster row stay lit after deselection.
      setScope([cluster.id])
      start(type)
      watchDeformState()
      const indicator = document.getElementById('mode-indicator')
      if (indicator) indicator.textContent = `${type.toUpperCase()} — click plane A (fixed), then plane B · Esc to exit`
    } })
    document.addEventListener('keydown', escape, true)
  }
  for (const type of ['bend', 'twist']) document.getElementById(`menu-tools-${type}`)?.addEventListener('click', () => open(type))
  return { open, cancel }
}
