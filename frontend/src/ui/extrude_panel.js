/**
 * Extrude tool — the right-sidebar panel that hosts the extrude controls and the
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
import { resolveDefaultPlane, dropdownStateForMode } from './extrude_panel_logic.js'

const NEW_BUNDLE_INDICATOR =
  'NEW BUNDLE — select cells on the plane · Extrude to build · Esc to cancel'
const IDLE_INDICATOR = 'NADOC · WORKSPACE'

/**
 * @param {object} deps
 * @param {object} deps.store
 * @param {object} deps.slicePlane       slice_plane API (show / showAtEnd / hide / setExtrudeUiOpen)
 * @param {object} deps.expandedSpacing  { forceOff }
 * @param {object} deps.rightSidebar     { open } tab controller
 * @returns {{ activate: Function, hide: Function, isActive: () => boolean }}
 */
export function initExtrudePanel({ store, slicePlane, expandedSpacing, rightSidebar }) {
  const _panel  = document.getElementById('extrude-panel')
  const _select = document.getElementById('extrude-from')
  let _active = false
  let _mode   = null

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
    rightSidebar?.open?.('properties')

    const defaultPlane = resolveDefaultPlane(store.getState().currentPlane)
    const { value, disabled } = dropdownStateForMode(mode, ctx.plane, defaultPlane)
    if (_select) { _select.value = value; _select.disabled = disabled }
    if (_panel) _panel.style.display = 'block'
    slicePlane.setExtrudeUiOpen(true)

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
    const wasActive = _active
    _active = false
    _mode   = null
    slicePlane.setExtrudeUiOpen(false)
    if (wasActive) slicePlane.hide()
    if (_panel)  _panel.style.display = 'none'
    if (_select) _select.disabled = false
    if (wasActive) {
      const mi = _modeIndicator()
      if (mi) mi.textContent = IDLE_INDICATOR
    }
  }

  // Dropdown is the sole plane selector in new-bundle mode: re-position the widget
  // onto the chosen origin plane (slice_plane.show clears the in-progress selection).
  _select?.addEventListener('change', () => {
    if (!_active || _mode !== 'newBundle') return
    const plane = _select.value
    store.setState({ currentPlane: plane })
    _showNewBundleOnPlane(plane)
  })

  return { activate, hide, isActive: () => _active }
}
