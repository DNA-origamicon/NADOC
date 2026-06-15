/**
 * Workspace colour-scale widget for the oxDNA flexibility (RMSF) map.
 *
 * A floating legend pinned to the middle-right of the 3D workspace, shown only
 * while the flexibility map is active.  It draws the viridis ramp with two
 * draggable handles selecting the upper/lower bounds of the colour window over
 * the data's RMSF range; dragging a handle re-colours the structure in real time
 * via the onBoundsChange callback.  Number readouts above/below allow precise
 * entry, and a Reset returns to the full data min→max.
 *
 * Display-state only — bounds never touch topology.
 *
 * Factory: initFlexScale({ onBoundsChange }) → { show, hide, isVisible, getBounds }.
 */

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

export function initFlexScale({ onBoundsChange = null } = {}) {
  const root     = document.getElementById('flex-scale')
  const track    = document.getElementById('flex-scale-track')
  const handleHi = document.getElementById('flex-scale-handle-hi')
  const handleLo = document.getElementById('flex-scale-handle-lo')
  const maxInput = document.getElementById('flex-scale-max')
  const minInput = document.getElementById('flex-scale-min')
  const resetBtn = document.getElementById('flex-scale-reset')

  let _dataMin = 0
  let _dataMax = 1
  let _lo = 0
  let _hi = 1

  function _gap() { return Math.max(1e-6, (_dataMax - _dataMin) * 0.01) }

  function _render() {
    if (maxInput) maxInput.value = _hi.toFixed(2)
    if (minInput) minInput.value = _lo.toFixed(2)
    // Handle top as a % of the track (0% = top = dataMax).
    if (handleHi) handleHi.style.top = `${(1 - valueToFraction(_hi, _dataMin, _dataMax)) * 100}%`
    if (handleLo) handleLo.style.top = `${(1 - valueToFraction(_lo, _dataMin, _dataMax)) * 100}%`
  }

  function _emit() { onBoundsChange?.(_lo, _hi) }

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

  return {
    /** Show the scale, seeding the window with the full data min→max RMSF. */
    show(min, max) {
      const b = clampBounds(min, max)
      _dataMin = b.lo; _dataMax = b.hi
      _setBounds(b.lo, b.hi, { emit: false })
      if (root) root.style.display = ''
    },
    hide() { if (root) root.style.display = 'none' },
    isVisible: () => !!root && root.style.display !== 'none',
    getBounds: () => ({ lo: _lo, hi: _hi }),
  }
}
