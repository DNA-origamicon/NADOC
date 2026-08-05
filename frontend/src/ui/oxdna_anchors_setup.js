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
 * The list is a scrollable TABLE, one row per anchor.  Rows carry ``data-key`` /
 * ``data-hl`` exactly as the old chips did, so every consumer that addresses a row by
 * anchor key still works.
 *
 * Highlighting (purple) is a DISPLAY preference — rows and 3D halo always agree, both driven
 * by the pure ``highlightedAnchors``:
 *   • "Highlight all anchors" checkbox (per card, DEFAULT ON) → all, or none.
 *   • Click a row → ONLY that anchor (focus beats the toggle). Click it again, or the empty
 *     space below the rows, to drop focus and hand control back to the toggle.
 * None of it may fire ``onChange`` (which recomposes a running live session) — the anchor SET
 * is unchanged by looking at it.
 *
 * ── The Hold-atoms column (``ids.atoms``, NAMD only) ─────────────────────────────────
 * Pass ``ids.atoms`` and the card grows a per-row <select> choosing which ATOMS of that
 * anchor's bases to hold, plus it binds that element as "Apply hold to all".  The seven
 * live instances of this factory are engine-wide, but atom-level holds are a NAMD concept
 * (they end up as a b-factor column in a NAMD marker PDB), so the column is opt-in — the
 * other six cards render exactly the DOM they always did.
 *
 * The row options are CLONED from that same <select>, so the four presets stay defined
 * once, in index.html, and the card can never drift from them.  Unlike focus, an atom
 * change DOES fire ``onChange``: it changes the marker PDB and the physics, so a listener
 * that recomposes a live session genuinely needs to hear it.
 */

import {
  resolveSelectionAnchors, unsupportedBaseKeys,
  anchorKey, makeAnchorLabeller, addAnchors, removeAnchor, highlightedAnchors,
  anchorAtoms, hasAnchorAtoms, commonAnchorAtomsKey, atomOptionByKey,
  atomNamesFromValue, withAnchorAtoms, withAllAnchorAtoms,
} from '../scene/efield_math.js'

// Row palette. The highlighted row echoes the 3D halo's purple (design_renderer's
// anchorGlow layer is 0xb14aff) so the list and the scene read as the same thing.
const _C = { dim: '#8b949e', warn: '#e0a800' }
const _ROW = {
  off: 'background:#1c2733;border:1px solid #30363d;color:#c9d1d9',
  on:  'background:#2d1b4e;border:1px solid #b14aff;color:#e9d5ff',
}
const _ROW_BASE = 'font-size:var(--text-xs);cursor:pointer;'
const _CELL = 'padding:2px 4px;border-radius:0'
// The label cell must TRUNCATE, never push the other columns out. A `width:100%` label
// starved the Hold-atoms select to 6px in the ~230px sidebar — the column was rendered
// and effectively invisible. table-layout:fixed + these widths is what keeps it honest.
const _LABEL_CELL = `${_CELL};overflow:hidden;text-overflow:ellipsis;white-space:nowrap`
const _ATOMS_COL_W = '104px'
const _SELECT_CSS = 'width:100%;background:#0d1117;border:1px solid #30363d;'
  + 'color:#c9d1d9;border-radius:3px;padding:1px 2px;font-size:var(--text-xs);cursor:pointer'

const _DEFAULT_IDS = {
  toggle: 'oxdna-anchors-toggle', arrow: 'oxdna-anchors-arrow', body: 'oxdna-anchors-body',
  add: 'oxdna-anchors-add', clear: 'oxdna-anchors-clear', list: 'oxdna-anchors-list',
  status: 'oxdna-anchors-status', glow: 'oxdna-anchors-glow',
  // atoms: <id>  — opt-in; see the Hold-atoms column note above.
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
  const atomsEl  = id.atoms ? document.getElementById(id.atoms) : null

  // The four presets live ONCE, as <option>s on the Apply-to-all select; each row clones
  // them.  `_optByKey` maps a canonical atom set back to the option that represents it,
  // so a set no option offers simply leaves the select blank instead of lying.
  const _atomsOn  = !!atomsEl
  const _atomTpl  = atomsEl ? [...atomsEl.options].map(o => o.cloneNode(true)) : []
  const _optByKey = atomOptionByKey(_atomTpl)

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
    // One labeller per repaint, not per row: it indexes the design once so a large
    // origami doesn't get re-scanned for every anchor. `getSelection()` returns the whole
    // store state (anchorSelectionState spreads it), so all seven cards get real helix
    // numbers with no call-site change.
    const label = makeAnchorLabeller(getSelection?.()?.currentDesign ?? null)
    listEl.innerHTML = ''
    // An empty card stays a genuinely EMPTY box — no stray table element. Callers count
    // listEl.children to mean "how many anchors", and the click-off-to-unfocus handler
    // needs listEl itself to be the event target over blank space.
    if (!_anchors.length) return
    const table = document.createElement('table')
    // FIXED layout: the columns get the widths declared below instead of being sized by
    // their content, so a long label can never squeeze the select out of existence.
    table.style.cssText =
      'width:100%;table-layout:fixed;border-collapse:separate;border-spacing:0 2px'
    if (_atomsOn) {
      const cols = document.createElement('colgroup')
      for (const w of ['auto', _ATOMS_COL_W, '16px']) {
        const c = document.createElement('col')
        if (w !== 'auto') c.style.width = w
        cols.appendChild(c)
      }
      table.appendChild(cols)
    }
    // No header row: the box is ~110px tall, and its textContent is read as the anchor
    // list by e2e — a header would eat both.
    for (const a of _anchors) {
      const key = anchorKey(a)
      const isLit = lit.has(key)
      const row = document.createElement('tr')
      row.dataset.key = key
      if (isLit) row.dataset.hl = '1'                     // e2e/console handle
      if (_focusKey === key) row.dataset.focused = '1'
      row.style.cssText = _ROW_BASE + (isLit ? _ROW.on : _ROW.off)
      row.title = _focusKey === key ? 'Click again to show all anchors' : 'Click to show only this anchor'
      // Click = focus this one (rest go dark); click the focused one again = back to the
      // toggle.  Clicks inside the atoms <select> are the user opening a dropdown, not
      // choosing a row — let them through untouched.
      row.addEventListener('click', (e) => {
        if (e.target?.closest?.('select')) return
        _setFocus(_focusKey === key ? null : key)
      })

      // Label cell takes the slack the fixed columns leave, and ellipsis-truncates
      // rather than growing, so a centre-click still lands here and the select survives.
      const lbl = document.createElement('td')
      lbl.style.cssText = _LABEL_CELL
      const text = label(a)
      lbl.textContent = text                               // bare text, no wrapper span
      lbl.title = text                                     // full name on hover
      row.appendChild(lbl)

      if (_atomsOn) row.appendChild(_atomsCell(a, key))

      const rm = document.createElement('td')
      rm.style.cssText = `${_CELL};text-align:right`
      const x = document.createElement('span')
      x.dataset.role = 'remove'
      x.textContent = '×'; x.style.cssText = 'cursor:pointer;color:#8b949e;font-weight:700'
      x.addEventListener('click', (e) => {
        e.stopPropagation()                                // don't let × also focus the row
        _anchors = removeAnchor(_anchors, key)
        if (_focusKey === key) _focusKey = null            // never keep focus on a deleted anchor
        _renderAnchors()
        _syncApplyAll()
        _emit()
      })
      rm.appendChild(x)
      row.appendChild(rm)
      table.appendChild(row)
    }
    listEl.appendChild(table)
  }

  /** One row's Hold-atoms cell. */
  function _atomsCell(a, key) {
    const cell = document.createElement('td')
    cell.style.cssText = _CELL
    const sel = document.createElement('select')
    sel.style.cssText = _SELECT_CSS
    sel.title = 'Which atoms of this anchor’s bases to hold'
    for (const o of _atomTpl) sel.appendChild(o.cloneNode(true))
    const opt = _optByKey.get(_atomsKeyOf(a))
    // A set no option offers (a headless caller's own names) leaves the row blank rather
    // than silently showing a choice it does not have.
    if (opt === undefined) sel.selectedIndex = -1
    else sel.value = opt
    sel.addEventListener('change', () => {
      // Mutate + resync the group select ONLY — a full re-render would replace this
      // <select> out from under its own change event.
      _anchors = withAnchorAtoms(_anchors, key, atomNamesFromValue(sel.value))
      _syncApplyAll()
      // Not _dispatch: unlike focus, the held atoms are part of the run, so a live
      // session that recomposes on the anchor set genuinely needs this.
      _emit()
    })
    cell.appendChild(sel)
    return cell
  }

  const _atomsKeyOf = (a) => {
    const names = anchorAtoms(a)
    return names ? names.slice().sort().join(',') : ''
  }

  /** Paint "Apply hold to all" from the rows: their shared value, or BLANK when they
   *  disagree.  Blank is the honest rendering of a mixed set — any concrete value there
   *  would claim rows hold something they don't. */
  function _syncApplyAll() {
    if (!atomsEl) return
    const key = commonAnchorAtomsKey(_anchors)
    const value = key === null ? undefined : _optByKey.get(key)
    if (value === undefined) atomsEl.selectedIndex = -1
    else atomsEl.value = value
  }

  // Focus is a DISPLAY choice: repaint the rows + the halo, never onChange (which would
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
    // Picked bases that resolve to nothing — a key whose helix was deleted, or an
    // unparseable one. Normally empty (extra crossover bases and extension tails ARE
    // addressable, via the extra_base/extension kinds), but a stale pick must not be
    // dropped silently: a user reading "added" over an empty anchor set is the failure.
    const skipped = unsupportedBaseKeys(sel)
    if (!found.length) {
      _setStatus(skipped.length
        ? `${skipped.length} picked base${skipped.length === 1 ? '' : 's'} no longer exist${skipped.length === 1 ? 's' : ''} in the design.`
        : 'Select an overhang, binding strand, domain, cluster, or base first.', _C.warn)
      return 0
    }
    const before = _anchors.length
    // New rows inherit whatever "Apply hold to all" currently shows, so adding to a
    // uniform card keeps it uniform. Only when the column exists — the other six cards
    // must keep emitting descriptors byte-identical to what they always have.
    // addAnchors dedupes FIRST-SEEN, so re-adding an existing anchor preserves the atom
    // choice already on its row rather than resetting it.
    _anchors = addAnchors(_anchors, _atomsOn ? found.map(a => _stampAtoms(a)) : found)
    _renderAnchors()
    _syncApplyAll()
    _emit()
    const added = _anchors.length - before
    if (skipped.length) {
      _setStatus(`Added ${added}; skipped ${skipped.length} stale base${skipped.length === 1 ? '' : 's'}.`, _C.warn)
    }
    return added
  }

  /** Stamp a descriptor with an atom choice it doesn't already carry. Key PRESENCE is the
   *  signal, so a descriptor that explicitly says `atoms: null` (all heavy atoms) is left
   *  alone rather than overwritten by the group value. */
  function _stampAtoms(a, names = atomNamesFromValue(atomsEl?.value)) {
    return hasAnchorAtoms(a) ? a : { ...a, atoms: names }
  }

  function clear() { _anchors = []; _focusKey = null; _renderAnchors(); _syncApplyAll(); _emit() }

  /**
   * Replace the anchor set from a stored list of descriptors so selecting a job shows
   * exactly the scopes that run held fixed (rows + 3D glow via onChange).  Deduped
   * through addAnchors; an empty/missing list clears.
   *
   * ``defaultAtoms`` is the job-level atom filter (manifest ``anchors.atom_names``): rows
   * that carry no ``atoms`` of their own are stamped with it, so a job saved before
   * per-anchor holds existed still repopulates its Hold-atoms column correctly instead of
   * reading as all-heavy.
   */
  function applyConfig(anchors, { defaultAtoms = null } = {}) {
    const list = anchors || []
    _anchors = addAnchors([], _atomsOn ? list.map(a => _stampAtoms(a, defaultAtoms)) : list)
    _focusKey = null                 // a new anchor set starts unfocused (toggle governs)
    _renderAnchors()
    _syncApplyAll()
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
  // "Apply hold to all" — write the one value onto every row. A full re-render is safe
  // here (unlike a row select's own handler) because this element lives outside listEl.
  atomsEl?.addEventListener('change', () => {
    _anchors = withAllAnchorAtoms(_anchors, atomNamesFromValue(atomsEl.value))
    _renderAnchors()
    _emit()
  })
  // Clicking the empty space below the rows also drops focus (the other reading of
  // "click off the selected entry"; row clicks never reach here — they hit the row).
  listEl?.addEventListener('click', (e) => { if (e.target === listEl) _setFocus(null) })
  _renderAnchors()
  _syncApplyAll()

  return {
    getAnchors, addSelectedAnchors, clear, refresh: _renderAnchors, applyConfig,
    isGlowOn, getFocusKey, getHighlighted,
  }
}
