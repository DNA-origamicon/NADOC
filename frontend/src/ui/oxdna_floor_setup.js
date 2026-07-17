/**
 * Hard-surface (oxDNA repulsion plane) setup UI — the "Hard surface" sub-section
 * of the oxDNA panel (Dynamics tab).  An independently-addable element of the
 * consolidated production run: an "Apply" checkbox + an axis-aligned floor side
 * (reusing photo-mode's six-axis convention) + offset + repulsion stiffness.
 *
 * The structure rests on the side the chosen normal points toward; the plane's
 * absolute height is derived backend-side from the structure's extent.  Anchors
 * (tethers) are a SEPARATE element (the Anchors card) — a bare surface is a valid
 * steric wall on its own.
 *
 * Display-layer only.  Geometry/spec math lives in scene/oxdna_floor_math.js
 * (pure, unit-tested); this module is DOM wiring.
 *
 * Factory: initOxdnaFloorSetup({ onChange, ids }) → { getSurfaceSpec, isEnabled,
 *   refresh }.  getSurfaceSpec() → { dir, offsetNm, positionNm, stiff, enabled }.  The `ids`
 *   bag lets a sibling engine (mrDNA, M8) mount the SAME card onto its own DOM ids
 *   with zero behaviour change — default ids are the oxDNA panel's.
 */

import {
  floorSurfaceSpec, formatOffsetNm, axisForNormal,
  floorContactCoordinate, floorClearanceFromAbsolute, floorAbsoluteFromClearance,
} from '../scene/oxdna_floor_math.js'

// Default DOM ids (the oxDNA "Hard surface" card). A sibling panel passes its own
// `ids` bag (e.g. mrdna-surface-*) to mount an identical card — same math, same
// {dir, offset_nm, stiff} descriptor.
const DEFAULT_IDS = {
  toggle: 'oxdna-floor-toggle', arrow: 'oxdna-floor-arrow', body: 'oxdna-floor-body',
  enable: 'oxdna-floor-enable', controls: 'oxdna-floor-controls', axis: 'oxdna-floor-axis',
  offset: 'oxdna-floor-offset', offsetLabel: 'oxdna-floor-offset-label',
  stiff: 'oxdna-floor-stiff', ready: 'oxdna-floor-ready',
}

export function initOxdnaFloorSetup({ onChange = null, setSurfaceGrid = null, getStructureBounds = null, ids = null } = {}) {
  const id = { ...DEFAULT_IDS, ...(ids || {}) }
  const toggle = document.getElementById(id.toggle)
  const arrow  = document.getElementById(id.arrow)
  const bodyEl = document.getElementById(id.body)
  const noop = { getSurfaceSpec: () => null, isEnabled: () => false, refresh: () => {} }
  if (!toggle || !bodyEl) return noop

  const enableChk = document.getElementById(id.enable)
  const controls  = document.getElementById(id.controls)
  const axisSel   = document.getElementById(id.axis)
  const offsetIn  = document.getElementById(id.offset)
  const offsetLbl = document.getElementById(id.offsetLabel)
  const stiffIn   = document.getElementById(id.stiff)
  const statusEl  = document.getElementById(id.ready)

  let _open    = false
  let _enabled = false
  const _bounds = () => getStructureBounds?.() || null

  function _absolutePosition() { return parseFloat(offsetIn?.value || '0') || 0 }
  function _setAbsolutePosition(value) {
    if (offsetIn) {
      offsetIn.value = String(value)
    }
    if (offsetLbl) offsetLbl.textContent = formatOffsetNm(value)
  }

  function getSurfaceSpec() {
    const spec = floorSurfaceSpec({
      axis: axisSel?.value || '-y',
      offsetNm: floorClearanceFromAbsolute(axisSel?.value || '-y', _absolutePosition(), _bounds()),
      stiff: parseFloat(stiffIn?.value || '0'),
    })
    return spec ? { ...spec, positionNm: _absolutePosition(), enabled: _enabled } : null
  }
  function isEnabled() { return _enabled }

  function _setStatus(text, color = '#8b949e') {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }
  function _syncControlsVisibility() {
    if (controls) controls.style.display = _enabled ? 'flex' : 'none'
  }
  // Drive the shared View grid to render (and visually represent) the surface.
  function _pushGrid() {
    setSurfaceGrid?.({
      enabled: _enabled,
      axis: axisSel?.value || '-y',
      offsetNm: 0,
      positionNm: _absolutePosition(),
    })
  }

  function _renderStatus() {
    onChange?.()
    _pushGrid()
    if (!_enabled) { _setStatus('Off — tick "Apply" to add a surface to the run.'); return }
    const spec = getSurfaceSpec()
    if (!spec || !(spec.stiff > 0)) { _setStatus('Set a stiffness > 0.'); return }
    const side = axisSel?.options?.[axisSel.selectedIndex]?.textContent?.trim() || ''
    _setStatus(`Surface on · ${side} · absolute ${formatOffsetNm(_absolutePosition())}.`, '#e0a800')
  }

  // ── Section open/close ───────────────────────────────────────────────────────
  function _open_() {
    _open = true
    bodyEl.style.display = ''
    if (arrow) arrow.classList.remove('is-collapsed')
    _syncControlsVisibility(); _renderStatus()
  }
  function _close_() {
    _open = false
    bodyEl.style.display = 'none'
    if (arrow) arrow.classList.add('is-collapsed')
  }
  toggle.addEventListener('click', () => { _open ? _close_() : _open_() })
  _close_()

  // ── Inputs ───────────────────────────────────────────────────────────────────
  enableChk?.addEventListener('change', () => {
    _enabled = !!enableChk.checked; _syncControlsVisibility(); _renderStatus()
  })
  axisSel?.addEventListener('change', () => {
    const contact = floorContactCoordinate(axisSel.value, _bounds())
    if (contact != null) _setAbsolutePosition(contact)
    _renderStatus()
  })
  offsetIn?.addEventListener('input', () => {
    if (offsetLbl) offsetLbl.textContent = formatOffsetNm(offsetIn.value)
    _renderStatus()
  })
  stiffIn?.addEventListener('input', _renderStatus)

  // Repopulate the card from a stored surface spec ({dir, offset_nm, stiff} or
  // null) so selecting an oxDNA job shows the hard surface that run used.  A null
  // spec turns the surface off.  Maps the stored normal back to an axis side.
  function applyConfig(surface) {
    _enabled = !!surface
    if (enableChk) enableChk.checked = _enabled
    if (surface) {
      const axis = axisForNormal(surface.dir)
      if (axis && axisSel) axisSel.value = axis
      const absolute = surface.position_nm != null && Number.isFinite(Number(surface.position_nm))
        ? Number(surface.position_nm)
        : floorAbsoluteFromClearance(axis || '-y', surface.offset_nm, _bounds())
      _setAbsolutePosition(absolute)
      if (stiffIn && surface.stiff != null) stiffIn.value = String(surface.stiff)
    }
    _syncControlsVisibility()
    _renderStatus()
  }

  return { getSurfaceSpec, isEnabled, refresh: _renderStatus, applyConfig }
}
