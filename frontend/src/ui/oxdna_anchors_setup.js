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
 * Factory: initOxdnaAnchorsSetup({ getSelection, ids, engine }) → { getAnchors,
 *   addSelectedAnchors, clear, refresh }.  ``ids`` overrides the DOM element ids so a
 *   SECOND instance (e.g. the CanDo FEM panel's Anchors card, same shared scope resolver)
 *   can drive its own ``cando-anchors-*`` skeleton; omit it and the oxDNA ids are used.
 *   ``engine`` tags the ``nadoc:anchors-change`` event this card fires on every mutation
 *   (engine-selector key — 'oxdna' | 'mrdna' | 'cando' | 'snupi' | 'namd'), so main.js can
 *   drive the purple anchor halo for whichever engine is on screen.
 *
 * Highlighting (purple) is a DISPLAY preference — chips and 3D halo always agree, both driven
 * by the pure ``highlightedAnchors``:
 *   • "Highlight all anchors" checkbox (per card, DEFAULT ON) → all, or none.
 *   • Click a chip → ONLY that anchor (focus beats the toggle). Click it again, or the empty
 *     space beside the chips, to drop focus and hand control back to the toggle.
 * None of it may fire ``onChange`` (which recomposes a running live session) — the anchor SET
 * is unchanged by looking at it.
 */

import {
  resolveSelectionAnchors, unsupportedBaseKeys,
  anchorKey, anchorLabel, addAnchors, removeAnchor, highlightedAnchors,
} from '../scene/efield_math.js'

// Chip palette. The highlighted chip echoes the 3D halo's purple (design_renderer's
// anchorGlow layer is 0xb14aff) so the list and the scene read as the same thing.
const _C = { dim: '#8b949e', warn: '#e0a800' }
const _CHIP = {
  off: 'background:#1c2733;border:1px solid #30363d;color:#c9d1d9',
  on:  'background:#2d1b4e;border:1px solid #b14aff;color:#e9d5ff',
}
const _CHIP_BASE = 'display:inline-flex;align-items:center;gap:4px;margin:2px 4px 2px 0;'
  + 'padding:2px 6px;border-radius:10px;font-size:var(--text-xs);cursor:pointer;'

const _DEFAULT_IDS = {
  toggle: 'oxdna-anchors-toggle', arrow: 'oxdna-anchors-arrow', body: 'oxdna-anchors-body',
  add: 'oxdna-anchors-add', clear: 'oxdna-anchors-clear', list: 'oxdna-anchors-list',
  status: 'oxdna-anchors-status', glow: 'oxdna-anchors-glow',
}

export function initOxdnaAnchorsSetup({ getSelection = null, onChange = null, ids = {}, engine = 'oxdna' } = {}) {
  const id = { ..._DEFAULT_IDS, ...ids }
  const toggle = document.getElementById(id.toggle)
  const arrow  = document.getElementById(id.arrow)
  const bodyEl = document.getElementById(id.body)
  const noop = {
    getAnchors: () => [], addSelectedAnchors: () => 0, clear: () => {}, refresh: () => {},
    applyConfig: () => {}, isGlowOn: () => true, getFocusKey: () => null, getHighlighted: () => [],
  }
  if (!toggle || !bodyEl) return noop

  const addBtn   = document.getElementById(id.add)
  const clearBtn = document.getElementById(id.clear)
  const listEl   = document.getElementById(id.list)
  const statusEl = document.getElementById(id.status)
  const glowEl   = document.getElementById(id.glow)

  let _open    = false
  let _anchors = []
  // Highlight-in-3D defaults ON, and the DEFAULT LIVES HERE, not in the markup: the skeleton
  // ships `checked` only so the pre-hydration paint matches, and a card whose HTML forgot it
  // (or has no toggle at all) must still default on rather than silently start dark.
  let _glow    = true
  if (glowEl) glowEl.checked = _glow
  // Key of the ONE chip the user clicked, or null. Focus beats the toggle (see
  // highlightedAnchors); clicking the focused chip again — or the empty space beside the
  // chips — drops focus and hands control back to the toggle.
  let _focusKey = null

  function getAnchors() { return _anchors.slice() }
  function getFocusKey() { return _focusKey }
  function getHighlighted() { return highlightedAnchors(_anchors, { glowAll: _glow, focusKey: _focusKey }) }

  // One notification point for every anchor mutation (add / chip × / clear / applyConfig).
  // The window event lets ONE listener drive the purple halo for all five engine cards
  // without each jobs panel having to forward a callback; `engine` matches the engine
  // selector's keys so the listener can show the ACTIVE engine's anchors.
  function _dispatch() {
    window.dispatchEvent(new CustomEvent('nadoc:anchors-change', {
      // `highlighted` is what the halo draws — the card owns the rule so main.js stays wiring
      // and the chips can't drift out of sync with the scene. `anchors` is still the full set.
      detail: { engine, anchors: getAnchors(), glow: _glow, focusKey: _focusKey, highlighted: getHighlighted() },
    }))
  }

  function _emit() {
    onChange?.(getAnchors())
    _dispatch()
  }

  function isGlowOn() { return _glow }

  function _setStatus(text, color = _C.dim) {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }

  function _renderAnchors() {
    if (statusEl) {
      const n = _anchors.length
      // "strands" was accurate when overhangs/strands/domains were the only scopes; an
      // anchor set can now be entirely individual bases, so name what is actually held.
      const noun = _anchors.every(a => a?.kind === 'base') ? 'base' : 'anchor'
      _setStatus(n ? `${n} fixed ${noun}${n === 1 ? '' : 's'}.`
                   : 'No anchors — runs are free unless you add fixed strands.')
    }
    if (!listEl) return
    const lit = new Set(getHighlighted().map(anchorKey))
    listEl.innerHTML = ''
    for (const a of _anchors) {
      const key = anchorKey(a)
      const isLit = lit.has(key)
      const chip = document.createElement('span')
      chip.dataset.key = key
      if (isLit) chip.dataset.hl = '1'                    // e2e/console handle
      if (_focusKey === key) chip.dataset.focused = '1'
      chip.style.cssText = _CHIP_BASE + (isLit ? _CHIP.on : _CHIP.off)
      chip.title = _focusKey === key ? 'Click again to show all anchors' : 'Click to show only this anchor'
      // Click = focus this one (rest go dark); click the focused one again = back to the toggle.
      chip.addEventListener('click', () => _setFocus(_focusKey === key ? null : key))
      const lbl = document.createElement('span'); lbl.textContent = anchorLabel(a)
      const x = document.createElement('span')
      x.textContent = '×'; x.style.cssText = 'cursor:pointer;color:#8b949e;font-weight:700'
      x.addEventListener('click', (e) => {
        e.stopPropagation()                                // don't let × also focus the chip
        _anchors = removeAnchor(_anchors, key)
        if (_focusKey === key) _focusKey = null            // never keep focus on a deleted anchor
        _renderAnchors()
        _emit()
      })
      chip.append(lbl, x)
      listEl.appendChild(chip)
    }
  }

  // Focus is a DISPLAY choice: repaint the chips + the halo, never onChange (which would
  // recompose a running live session over a change that doesn't touch the anchor set).
  function _setFocus(key) {
    if (_focusKey === key) return
    _focusKey = key
    _renderAnchors()
    _dispatch()
  }

  function addSelectedAnchors() {
    const sel = getSelection ? getSelection() : null
    const found = resolveSelectionAnchors(sel)
    // Bases the `base` selection level can pick but no anchor can address: crossover
    // extra-base inserts and extension-tail beads have no (helix, bp, direction) in the
    // strand walk, so they would resolve to zero particles. Say so rather than dropping
    // them silently — a user who lassoed a run of extra bases must not read an empty
    // anchor set as "added".
    const skipped = unsupportedBaseKeys(sel)
    if (!found.length) {
      _setStatus(skipped.length
        ? `Can't anchor ${skipped.length} picked base${skipped.length === 1 ? '' : 's'} — extra crossover bases and extension tails aren't addressable as anchors.`
        : 'Select an overhang, binding strand, domain, cluster, or base first.', _C.warn)
      return 0
    }
    const before = _anchors.length
    _anchors = addAnchors(_anchors, found)
    _renderAnchors()
    _emit()
    const added = _anchors.length - before
    if (skipped.length) {
      _setStatus(`Added ${added}; skipped ${skipped.length} base${skipped.length === 1 ? '' : 's'} (extra crossover / extension beads aren't anchorable).`, _C.warn)
    }
    return added
  }

  function clear() { _anchors = []; _focusKey = null; _renderAnchors(); _emit() }

  // Replace the anchor set from a stored list of descriptors so selecting an
  // oxDNA job shows exactly the strands that run held fixed (chips + 3D glow via
  // onChange).  Deduped through addAnchors; an empty/missing list clears.
  function applyConfig(anchors) {
    _anchors = addAnchors([], anchors || [])
    _focusKey = null                 // a new anchor set starts unfocused (toggle governs)
    _renderAnchors()
    _emit()
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
  // Display-only: _dispatch (repaint the halo), NOT _emit — onChange would recompose a
  // running live session over a change that doesn't touch the anchor set.
  glowEl?.addEventListener('change', () => { _glow = glowEl.checked; _renderAnchors(); _dispatch() })
  // Clicking the empty space beside the chips also drops focus (the other reading of
  // "click off the selected entry"; chip clicks never reach here — they hit the chip).
  listEl?.addEventListener('click', (e) => { if (e.target === listEl) _setFocus(null) })
  _renderAnchors()

  return {
    getAnchors, addSelectedAnchors, clear, refresh: _renderAnchors, applyConfig,
    isGlowOn, getFocusKey, getHighlighted,
  }
}
