import { createCrossSectionWorkflow, CROSS_SECTION_HELP } from './cross_section_workflow.js'
/**
 * Extrude tool — the floating tool panel that hosts the extrude controls and the
 * "Extrude from" plane dropdown.
 *
 * This replaces the old floating `#slice-ctx-menu` + the `workspace.js` plane
 * picker as the entry point to every extrude. The controls' DOM lives in
 * `#extrude-panel` (their child IDs are unchanged, so `slice_plane.js` still reads
 * them by ID); THIS module owns the panel's visibility + the dropdown state +
 * the tool lifecycle (activate / hide).
 *
 * Modes:
 *  - 'newBundle'   — Tools→Extrude / right-click empty space. The dropdown is the
 *    sole plane selector; activating (and changing the dropdown) drives
 *    `slicePlane.show(plane, …, { newBundle:true })`.
 *  - 'continuation' | 'deformed' | 'segment' — context-driven (a blunt end / a
 *    deformed frame). The CALLER drives `slicePlane.showAtEnd/showDeformed`; this
 *    module just shows the panel and locks the dropdown to the context plane.
 */
import { createToolPopup } from './tool_popup.js'
import { resolveExtrudeSourcePlane } from './extrude_source_plane.js'
import { resolveDefaultPlane, dropdownStateForMode } from './extrude_panel_logic.js'

const NEW_BUNDLE_INDICATOR =
  'NEW BUNDLE — select cross-section · Next to set length · Esc to cancel'
const IDLE_INDICATOR = 'NADOC · WORKSPACE'

/**
 * @param {object} deps
 * @param {object} deps.store
 * @param {object} deps.slicePlane       slice_plane API (show / showAtEnd / hide / setExtrudeUiOpen)
 * @param {object} deps.expandedSpacing  { forceOff }
 * @returns {{ activate: Function, hide: Function, isActive: () => boolean }}
 */
export function initExtrudePanel({ store, slicePlane, expandedSpacing, getCamera, getControls, canvas, beginAuthoringDisplay }) {
  const _panel  = document.getElementById('extrude-panel')
  const _select = document.getElementById('extrude-from')
  let _active = false
  let _mode   = null
  let _editCancel = null
  let _editPlane = null
  const popup = createToolPopup({ panel: _panel, title: 'Extrude', onClose: hide })

  const workflow = createCrossSectionWorkflow({ slicePlane, getCamera, getControls, canvas, popup, beginAuthoringDisplay })
  let step = 1
  const next = document.getElementById('extrude-next')
  const cancel = document.getElementById('slice-cancel-btn')
  const apply = document.getElementById('slice-extrude-btn')
  const help = document.getElementById('extrude-section-help')
  if (help) help.textContent = CROSS_SECTION_HELP
  function selectionChanged() { if (next) next.disabled = !(slicePlane.getSelectedCells?.().length > 0) }
  function setStep(value) {
    step = value
    for (const group of _panel?.querySelectorAll('[data-extrude-step]') ?? []) group.hidden = group.dataset.extrudeStep !== String(step)
    if (help) help.hidden = step !== 1
    const status = document.getElementById('extrude-step')
    if (status) status.textContent = step === 1 ? 'Step 1/2 · Select cross-section' : 'Step 2/2 · Set extrusion length'
    if (next) next.hidden = step !== 1
    if (apply) apply.hidden = step !== 2
    if (cancel) cancel.textContent = step === 1 ? 'Cancel' : 'Previous'
    selectionChanged()
    workflow.setStep(step)
  }
  next?.addEventListener('click', () => { if (_active && !next.disabled) setStep(2) })
  cancel?.addEventListener('click', event => {
    if (_active && step === 2) { event.stopImmediatePropagation(); setStep(1) }
  }, true)
  const unsubscribeSource = slicePlane.subscribeSource?.(selectionChanged)
  const unsubscribeSelection = slicePlane.subscribeSelection?.(selectionChanged)
  const refit = () => { if (_active && step === 2) workflow.refit() }
  _panel?.addEventListener('input', refit)
  _panel?.addEventListener('change', refit)
  _panel?.addEventListener('click', event => { if (event.target.closest('.rec-chip, .ctx-dir-btn')) refit() })

  function _modeIndicator() { return document.getElementById('mode-indicator') }
  function _latticeType() { return store.getState().currentDesign?.lattice_type ?? 'HONEYCOMB' }

  function _showNewBundleOnPlane(plane) {
    slicePlane.show(plane, 0, false, false, { latticeType: _latticeType(), newBundle: true })
  }

  /**
   * Open the Extrude panel in a given mode. For 'newBundle' this also positions the
   * slice widget on the chosen origin plane; for context modes the caller positions
   * the widget (showAtEnd/showDeformed) and sets its own mode-indicator text.
   * @param {'newBundle'|'segment'|'continuation'|'deformed'} mode
   * @param {{ plane?: 'XY'|'XZ'|'YZ' }} [ctx]
   */
  function activate(mode = 'newBundle', ctx = {}) {
    _mode   = mode
    _active = true
    expandedSpacing?.forceOff?.()

    const source = resolveExtrudeSourcePlane(store.getState().currentDesign, resolveDefaultPlane(store.getState().currentPlane))
    const defaultPlane = source.plane
    if (_select) _select.title = ['mixed', 'unknown'].includes(source.reason)
      ? 'Mixed or unrecognized source planes: choose XY, XZ, or YZ explicitly.'
      : 'Canonical lattice source plane; independent of viewing orientation.'
    const { value, disabled } = dropdownStateForMode(mode, ctx.plane, defaultPlane)
    if (_select) { _select.value = value; _select.disabled = disabled }
    popup?.show()
    slicePlane.setExtrudeUiOpen(true)
    setStep(1)

    if (mode === 'newBundle') {
      store.setState({ currentPlane: value })
      _showNewBundleOnPlane(value)
      const mi = _modeIndicator()
      if (mi) mi.textContent = NEW_BUNDLE_INDICATOR
    }
    // context modes: the caller drives slicePlane + mode indicator.
  }

  /** Tear down the tool: hide the panel + slice widget, reset the dropdown + indicator. */
  function hide() {
    if (_editCancel) return _editCancel()
    const wasActive = _active
    _active = false
    _mode   = null
    workflow.close()
    slicePlane.setExtrudeUiOpen(false)
    if (wasActive) slicePlane.hide()
    popup?.hide()
    if (_select) _select.disabled = false
    if (wasActive) {
      const mi = _modeIndicator()
      if (mi) mi.textContent = IDLE_INDICATOR
    }
  }

  // Dropdown is the sole plane selector in new-bundle mode: re-position the widget
  // onto the chosen origin plane (slice_plane.show clears the in-progress selection).
  _select?.addEventListener('change', () => {
    if (_active && _mode === 'edit') { _editPlane?.(_select.value); return }
    if (!_active || _mode !== 'newBundle') return
    const plane = _select.value
    store.setState({ currentPlane: plane })
    _showNewBundleOnPlane(plane)
  })

  function finishEdit() {
    _editCancel = _editPlane = null
    popup?.setAvoidCanvas(false)
    const apply = document.getElementById('slice-extrude-btn')
    if (apply) apply.textContent = 'Extrude'
    hide()
  }
  function activateEdit({ plane, onCancel, onPlaneChange }) {
    activate('edit', { plane })
    popup?.setAvoidCanvas(true)
    _editCancel = onCancel
    _editPlane = onPlaneChange
    if (_select) _select.disabled = !onPlaneChange
    const apply = document.getElementById('slice-extrude-btn')
    if (apply) apply.textContent = 'Apply'
    const mi = _modeIndicator()
    if (mi) mi.textContent = 'EDIT EXTRUDE — change cells and parameters · Apply to rebuild · Esc to cancel'
  }
  return { activate, activateEdit, finishEdit, hide, refreshCrossSection: () => workflow.refit(), isActive: () => _active,
    dispose() { hide(); unsubscribeSelection?.(); unsubscribeSource?.(); workflow.dispose(); popup?.dispose() } }
}
