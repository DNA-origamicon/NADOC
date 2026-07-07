/**
 * Anchors setup UI — the shared "Anchors" sub-section of the oxDNA panel
 * (Dynamics tab).  Lets the user mark overhangs / binding strands / domains /
 * clusters / individual bases as FIXED (traps) held in place during a run,
 * independent of whether an electric field or a hard surface is enabled.
 *
 * The anchor set feeds the consolidated production run (the panel reads it via
 * getAnchors()).  A field requires ≥1 anchor (an unanchored uniform force drifts
 * the whole structure); a surface or a plain run can use anchors or not.
 *
 * Display-layer only.  Anchor helpers are shared with the E-field math module
 * (scene/efield_math.js) — "fix these nucleotides" is the same concept.
 *
 * Factory: initOxdnaAnchorsSetup({ getSelection, ids }) → { getAnchors,
 *   addSelectedAnchors, clear, refresh }.  ``ids`` overrides the DOM element ids so a
 *   SECOND instance (e.g. the CanDo FEM panel's Anchors card, same shared scope resolver)
 *   can drive its own ``cando-anchors-*`` skeleton; omit it and the oxDNA ids are used.
 */

import {
  resolveSelectionAnchors, anchorKey, anchorLabel, addAnchors, removeAnchor,
} from '../scene/efield_math.js'

const _C = { dim: '#8b949e', warn: '#e0a800' }

const _DEFAULT_IDS = {
  toggle: 'oxdna-anchors-toggle', arrow: 'oxdna-anchors-arrow', body: 'oxdna-anchors-body',
  add: 'oxdna-anchors-add', clear: 'oxdna-anchors-clear', list: 'oxdna-anchors-list',
  status: 'oxdna-anchors-status',
}

export function initOxdnaAnchorsSetup({ getSelection = null, onChange = null, ids = {} } = {}) {
  const id = { ..._DEFAULT_IDS, ...ids }
  const toggle = document.getElementById(id.toggle)
  const arrow  = document.getElementById(id.arrow)
  const bodyEl = document.getElementById(id.body)
  const noop = { getAnchors: () => [], addSelectedAnchors: () => 0, clear: () => {}, refresh: () => {}, applyConfig: () => {} }
  if (!toggle || !bodyEl) return noop

  const addBtn   = document.getElementById(id.add)
  const clearBtn = document.getElementById(id.clear)
  const listEl   = document.getElementById(id.list)
  const statusEl = document.getElementById(id.status)

  let _open    = false
  let _anchors = []

  function getAnchors() { return _anchors.slice() }

  function _setStatus(text, color = _C.dim) {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }

  function _renderAnchors() {
    if (statusEl) {
      const n = _anchors.length
      _setStatus(n ? `${n} fixed strand${n === 1 ? '' : 's'}.` : 'No anchors — runs are free unless you add fixed strands.')
    }
    if (!listEl) return
    listEl.innerHTML = ''
    for (const a of _anchors) {
      const chip = document.createElement('span')
      chip.dataset.key = anchorKey(a)
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;margin:2px 4px 2px 0;padding:2px 6px;' +
        'background:#1c2733;border:1px solid #30363d;border-radius:10px;font-size:var(--text-xs);color:#c9d1d9'
      const lbl = document.createElement('span'); lbl.textContent = anchorLabel(a)
      const x = document.createElement('span')
      x.textContent = '×'; x.style.cssText = 'cursor:pointer;color:#8b949e;font-weight:700'
      x.addEventListener('click', () => { _anchors = removeAnchor(_anchors, anchorKey(a)); _renderAnchors(); onChange?.(getAnchors()) })
      chip.append(lbl, x)
      listEl.appendChild(chip)
    }
  }

  function addSelectedAnchors() {
    const found = resolveSelectionAnchors(getSelection ? getSelection() : null)
    if (!found.length) {
      _setStatus('Select an overhang, binding strand, domain, cluster, or base first.', _C.warn)
      return 0
    }
    const before = _anchors.length
    _anchors = addAnchors(_anchors, found)
    _renderAnchors()
    onChange?.(getAnchors())
    return _anchors.length - before
  }

  function clear() { _anchors = []; _renderAnchors(); onChange?.(getAnchors()) }

  // Replace the anchor set from a stored list of descriptors so selecting an
  // oxDNA job shows exactly the strands that run held fixed (chips + 3D glow via
  // onChange).  Deduped through addAnchors; an empty/missing list clears.
  function applyConfig(anchors) {
    _anchors = addAnchors([], anchors || [])
    _renderAnchors()
    onChange?.(getAnchors())
  }

  // ── Section open/close ───────────────────────────────────────────────────────
  function _open_() {
    _open = true
    bodyEl.style.display = ''
    if (arrow) arrow.classList.remove('is-collapsed')
    _renderAnchors()
  }
  function _close_() {
    _open = false
    bodyEl.style.display = 'none'
    if (arrow) arrow.classList.add('is-collapsed')
  }
  toggle.addEventListener('click', () => { _open ? _close_() : _open_() })
  _close_()

  addBtn?.addEventListener('click', addSelectedAnchors)
  clearBtn?.addEventListener('click', clear)
  _renderAnchors()

  return { getAnchors, addSelectedAnchors, clear, refresh: _renderAnchors, applyConfig }
}
