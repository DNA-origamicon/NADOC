/**
 * The workspace colour-scale widget — ONE adjustable legend shared by every
 * scalar-coloured simulation output (oxDNA / MD flexibility-RMSF maps, deviation
 * maps, CanDo RMSF / deviation / cylinder heat maps).
 *
 * A floating legend pinned to the middle-right of the 3D workspace, shown only
 * while a colour-mapped output is active.  It draws the active colormap's ramp with
 * two draggable handles selecting the upper/lower bounds of the colour window over
 * the data's value range; dragging a handle re-colours the structure in real time
 * via the active map's onRecolor callback.  A colormap-picker button opens a popup
 * of common colormaps (viridis, turbo, jet, …); the pick is remembered per map-type
 * (flexibility, deviation, CanDo) so each map keeps its "respective colours" by
 * default.  Number readouts allow precise entry, and Reset returns to the full
 * data min→max.
 *
 * Each activation is driven by `show({ title, min, max, mapType, onRecolor })` — the
 * caller (a display controller) hands the widget the map's range + a recolour
 * callback `onRecolor(lo, hi, colormapName)`.  So the widget is decoupled from any
 * one panel: whichever map is active owns the legend.
 *
 * Display-state only — bounds + colormap never touch topology.
 *
 * Factory: initFlexScale() → { show, hide, isVisible, getBounds, getColormap, setColormap }.
 */

import {
  COLORMAPS, COLORMAP_LIST, colormapGradientCss, loadColormap, saveColormap, normalizeColormap,
} from './colormaps.js'

export function chimeraxPalette(name) {
  return COLORMAPS[normalizeColormap(name)].lut
    .map(([r, g, b]) => `#${[r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')}`)
    .join(':')
}

export function chimeraxColorCommand(name, lo, hi) {
  return `color byattribute bfactor palette "${chimeraxPalette(name)}" range ${Number(lo).toPrecision(6)},${Number(hi).toPrecision(6)} target as`
}

/**
 * Pure: normalise a (lo, hi) pair to a valid, ordered range.  Swaps if reversed
 * and nudges hi above lo when they collapse, so the colour span is never zero.
 */
export function clampBounds(lo, hi) {
  let a = Number.isFinite(lo) ? lo : 0
  let b = Number.isFinite(hi) ? hi : 0
  if (a > b) { const t = a; a = b; b = t }
  if (b - a < 1e-6) b = a + 1e-6
  return { lo: a, hi: b }
}

/** Pure: value → [0,1] track fraction (0 = bottom/dataMin, 1 = top/dataMax). */
export function valueToFraction(val, dataMin, dataMax) {
  const span = dataMax - dataMin
  if (!(span > 0)) return 0
  return Math.max(0, Math.min(1, (val - dataMin) / span))
}

/** Pure: [0,1] track fraction → value within [dataMin, dataMax]. */
export function fractionToValue(frac, dataMin, dataMax) {
  const f = Math.max(0, Math.min(1, Number.isFinite(frac) ? frac : 0))
  return dataMin + f * (dataMax - dataMin)
}

export function initFlexScale() {
  const root     = document.getElementById('flex-scale')
  const track    = document.getElementById('flex-scale-track')
  const titleEl  = document.getElementById('flex-scale-title')
  const handleHi = document.getElementById('flex-scale-handle-hi')
  const handleLo = document.getElementById('flex-scale-handle-lo')
  const maxInput = document.getElementById('flex-scale-max')
  const minInput = document.getElementById('flex-scale-min')
  const resetBtn = document.getElementById('flex-scale-reset')
  const cmapBtn  = document.getElementById('flex-scale-cmap')
  let helpBtn = document.getElementById('flex-scale-help')

  let _dataMin  = 0
  let _dataMax  = 1
  let _lo       = 0
  let _hi       = 1
  let _mapType  = 'flex'
  let _colormap = 'viridis'
  let _onRecolor = null      // active map's recolour callback (lo, hi, colormapName)
  let _popup    = null       // lazily-built colormap-picker popup

  if (!helpBtn && root) {
    helpBtn = document.createElement('button')
    helpBtn.id = 'flex-scale-help'; helpBtn.type = 'button'; helpBtn.textContent = '?'
    helpBtn.title = 'Show ChimeraX recoloring commands'
    helpBtn.style.cssText = 'position:absolute;right:-7px;top:-8px;width:17px;height:17px;padding:0;border-radius:50%;border:1px solid var(--color-border-default);background:var(--color-bg-inset);color:var(--color-text-secondary);font-size:10px;font-weight:700;cursor:pointer'
    root.appendChild(helpBtn)
  }

  function _showChimeraxHelp() {
    const overlay = document.createElement('div')
    overlay.className = 'modal-overlay'
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10002;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;padding:24px'
    const box = document.createElement('div')
    box.style.cssText = 'width:min(680px,100%);background:#1a2530;border:1px solid #455a64;border-radius:10px;padding:20px;color:#cfd8dc;box-shadow:0 12px 48px rgba(0,0,0,.7)'
    const h = document.createElement('h2'); h.textContent = `ChimeraX coloring — ${titleEl?.textContent || 'simulation map'}`; h.style.cssText = 'font-size:16px;margin:0 0 10px;color:#eceff1'
    const p = document.createElement('p'); p.textContent = 'Export the PDB with “Include current coloring” enabled, open it in ChimeraX, then enter:'; p.style.cssText = 'font-size:13px;line-height:1.45'
    const pre = document.createElement('textarea'); pre.readOnly = true; pre.value = chimeraxColorCommand(_colormap, _lo, _hi); pre.style.cssText = 'box-sizing:border-box;width:100%;height:72px;padding:10px;background:#111c24;color:#b0bec5;border:1px solid #37474f;border-radius:5px;font:12px monospace;resize:none'
    const row = document.createElement('div'); row.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px'
    const copy = document.createElement('button'); copy.textContent = 'Copy'; const close = document.createElement('button'); close.textContent = 'Close'
    for (const b of [copy, close]) b.style.cssText = 'padding:7px 14px;border-radius:5px;border:1px solid #546e7a;background:#263238;color:#fff;cursor:pointer'
    const done = () => overlay.remove(); close.onclick = done; overlay.onclick = e => { if (e.target === overlay) done() }
    copy.onclick = async () => { await navigator.clipboard?.writeText(pre.value); copy.textContent = 'Copied!' }
    row.append(copy, close); box.append(h, p, pre, row); overlay.appendChild(box); document.body.appendChild(overlay)
  }
  helpBtn?.addEventListener('click', _showChimeraxHelp)

  // Put the same help affordance beside every scalar-colour visualization choice.
  // The controls are static labels in the jobs panels; deriving these buttons here
  // keeps their command synchronized with this legend's currently adjusted state.
  for (const input of document.querySelectorAll(
    'input[type="radio"][value="flex"], input[type="radio"][value="rmsf"], input[type="radio"][value="deviation"]')) {
    const label = input.closest('label')
    if (!label || label.querySelector('.chimerax-color-help')) continue
    const button = document.createElement('button')
    button.type = 'button'; button.className = 'chimerax-color-help'; button.textContent = '?'
    button.title = 'Show ChimeraX recoloring commands'
    button.style.cssText = 'margin-left:5px;width:17px;height:17px;padding:0;border-radius:50%;border:1px solid var(--color-border-default);background:var(--color-bg-inset);color:var(--color-text-secondary);font-size:10px;font-weight:700;cursor:pointer'
    button.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); _showChimeraxHelp() })
    label.appendChild(button)
  }

  function _gap() { return Math.max(1e-6, (_dataMax - _dataMin) * 0.01) }

  function _render() {
    if (maxInput) maxInput.value = _hi.toFixed(2)
    if (minInput) minInput.value = _lo.toFixed(2)
    // Handle top as a % of the track (0% = top = dataMax).
    if (handleHi) handleHi.style.top = `${(1 - valueToFraction(_hi, _dataMin, _dataMax)) * 100}%`
    if (handleLo) handleLo.style.top = `${(1 - valueToFraction(_lo, _dataMin, _dataMax)) * 100}%`
    // Ramp reflects the active colormap (bottom = dataMin, top = dataMax).
    if (track) track.style.background = colormapGradientCss(_colormap, { dir: 'to top' })
    if (cmapBtn) cmapBtn.style.background = colormapGradientCss(_colormap, { dir: 'to right' })
  }

  function _emit() { _onRecolor?.(_lo, _hi, _colormap) }

  function _setBounds(lo, hi, { emit = true } = {}) {
    const b = clampBounds(lo, hi)
    _lo = b.lo; _hi = b.hi
    _render()
    if (emit) _emit()
  }

  // ── Number-input entry ──────────────────────────────────────────────────────
  maxInput?.addEventListener('change', () => _setBounds(_lo, parseFloat(maxInput.value)))
  minInput?.addEventListener('change', () => _setBounds(parseFloat(minInput.value), _hi))
  resetBtn?.addEventListener('click', () => _setBounds(_dataMin, _dataMax))

  // ── Handle dragging (real-time recolour) ────────────────────────────────────
  function _valueAt(clientY) {
    const rect = track?.getBoundingClientRect?.()
    if (!rect || !rect.height) return null
    const frac = 1 - (clientY - rect.top) / rect.height   // top = 1 = dataMax
    return fractionToValue(frac, _dataMin, _dataMax)
  }

  function _startDrag(which, ev) {
    ev.preventDefault?.()
    const move = (e) => {
      const v = _valueAt(e.clientY)
      if (v == null) return
      if (which === 'hi') _setBounds(_lo, Math.max(v, _lo + _gap()))
      else                _setBounds(Math.min(v, _hi - _gap()), _hi)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  handleHi?.addEventListener('pointerdown', (e) => _startDrag('hi', e))
  handleLo?.addEventListener('pointerdown', (e) => _startDrag('lo', e))

  // ── Colormap picker popup ───────────────────────────────────────────────────
  function _buildPopup() {
    if (_popup || !root) return
    const pop = document.createElement('div')
    pop.id = 'flex-scale-cmap-popup'
    pop.style.cssText = [
      'position:absolute', 'right:100%', 'top:0', 'margin-right:6px', 'display:none',
      'z-index:var(--z-overlay)', 'width:120px', 'padding:5px',
      'background:var(--color-bg-raised)', 'border:1px solid var(--color-border-default)',
      'border-radius:6px', 'box-shadow:var(--shadow-md)', 'font-family:var(--font-ui)',
    ].join(';')
    for (const { name, label } of COLORMAP_LIST) {
      const row = document.createElement('button')
      row.type = 'button'
      row.dataset.cmap = name
      row.title = label
      row.style.cssText = [
        'display:flex', 'align-items:center', 'gap:6px', 'width:100%',
        'padding:2px 3px', 'margin:0 0 2px 0', 'cursor:pointer',
        'background:transparent', 'border:1px solid transparent', 'border-radius:3px',
        'font-size:10px', 'color:var(--color-text-primary)', 'text-align:left',
      ].join(';')
      const sw = document.createElement('span')
      sw.style.cssText = 'flex:0 0 34px;height:12px;border-radius:2px;border:1px solid var(--color-border-default);' +
        `background:${colormapGradientCss(name, { dir: 'to right' })}`
      const lab = document.createElement('span')
      lab.textContent = label
      lab.style.cssText = 'flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'
      row.appendChild(sw); row.appendChild(lab)
      row.addEventListener('click', (e) => { e.stopPropagation(); _setColormap(name); _closePopup() })
      pop.appendChild(row)
    }
    root.appendChild(pop)
    _popup = pop
  }

  function _highlightPopup() {
    if (!_popup) return
    for (const row of _popup.querySelectorAll('[data-cmap]')) {
      const on = row.dataset.cmap === _colormap
      row.style.borderColor = on ? 'var(--color-accent, #58a6ff)' : 'transparent'
      row.style.background = on ? 'var(--color-bg-inset)' : 'transparent'
    }
  }

  function _openPopup() {
    _buildPopup()
    if (!_popup) return
    _highlightPopup()
    _popup.style.display = 'block'
    // Close on the next outside click / Escape.
    setTimeout(() => {
      window.addEventListener('pointerdown', _onOutside, true)
      window.addEventListener('keydown', _onKey, true)
    }, 0)
  }
  function _closePopup() {
    if (_popup) _popup.style.display = 'none'
    window.removeEventListener('pointerdown', _onOutside, true)
    window.removeEventListener('keydown', _onKey, true)
  }
  function _onOutside(e) {
    if (_popup && !_popup.contains(e.target) && e.target !== cmapBtn) _closePopup()
  }
  function _onKey(e) { if (e.key === 'Escape') _closePopup() }

  function _setColormap(name, { emit = true } = {}) {
    _colormap = normalizeColormap(name)
    saveColormap(_mapType, _colormap)
    _render()
    _highlightPopup()
    if (emit) _emit()
  }

  cmapBtn?.addEventListener('click', (e) => {
    e.stopPropagation()
    if (_popup && _popup.style.display === 'block') _closePopup()
    else _openPopup()
  })

  return {
    /**
     * Activate the scale for a map.  `onRecolor(lo, hi, colormapName)` is invoked
     * whenever the user drags a handle, edits a bound, resets, or picks a colormap
     * — and once here so the on-structure colours match the (possibly remembered)
     * colormap.  Seeds the window with the full data min→max.
     */
    show({ title = '', min = 0, max = 1, mapType = 'flex', colormap = null, onRecolor = null } = {}) {
      _onRecolor = onRecolor
      _mapType = mapType
      _colormap = colormap ? normalizeColormap(colormap) : loadColormap(mapType)
      const b = clampBounds(min, max)
      _dataMin = b.lo; _dataMax = b.hi
      if (titleEl) titleEl.textContent = title
      _setBounds(b.lo, b.hi, { emit: true })   // reconcile colours to the active colormap
      if (root) root.style.display = ''
    },
    hide() { _closePopup(); if (root) root.style.display = 'none' },
    isVisible: () => !!root && root.style.display !== 'none',
    getBounds: () => ({ lo: _lo, hi: _hi }),
    getColormap: () => _colormap,
    getChimeraxPalette: () => chimeraxPalette(_colormap),
    getChimeraxCommand: () => chimeraxColorCommand(_colormap, _lo, _hi),
    setColormap: (name) => _setColormap(name),
  }
}
