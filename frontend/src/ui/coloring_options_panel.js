// Representation Options → Coloring array.
//
// Renders the FULL set of coloring modes as a button grid in the
// representation-options sidebar. For the active representation, the modes it
// supports are clickable; the rest are disabled (grayed/unclickable). Clicking
// an enabled mode drives the global coloring via the injected `onSelect`
// (main's _setColoringMode, which also keeps the View → Coloring menu and the
// atomistic/surface side buttons in sync). The active highlight tracks
// store.coloringMode so it stays correct no matter where the mode was changed
// (menu, F-key cycle, or availability fallback).
//
// Pure decision (which modes are enabled/active for a repr) lives in
// scene/coloring_modes.js → coloringOptionStates; this module is the thin DOM
// wiring around it.

import { coloringOptionStates, COLORING_ORDER } from '../scene/coloring_modes.js'

/**
 * @param {object} deps
 * @param {object} deps.store     app store (reads assemblyActive + coloringMode)
 * @param {(mode:string)=>void} deps.onSelect  invoked when an enabled mode is clicked
 * @returns {{updateForRepr: (repr:string)=>void}}
 */
export function initColoringOptionsPanel({ store, onSelect }) {
  let _repr = 'full'
  const _btns = new Map()

  for (const mode of COLORING_ORDER) {
    const el = document.getElementById(`repr-color-${mode}`)
    if (!el) continue
    _btns.set(mode, el)
    el.addEventListener('click', () => {
      if (el.disabled) return
      onSelect(mode)
    })
  }

  function _render() {
    const { assemblyActive, coloringMode } = store.getState()
    for (const s of coloringOptionStates(_repr, assemblyActive, coloringMode || 'strand')) {
      const el = _btns.get(s.mode)
      if (!el) continue
      el.disabled = !s.enabled
      el.classList.toggle('active', s.active)
    }
  }

  // Recompute availability + active when the representation changes.
  function updateForRepr(repr) {
    _repr = repr
    _render()
  }

  // Keep the active highlight in lockstep with the global coloring mode,
  // wherever it is set from.
  store.subscribe((newState, prevState) => {
    if (newState.coloringMode !== prevState.coloringMode) _render()
  })

  return { updateForRepr }
}
