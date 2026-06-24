/**
 * Electric-field setup UI — the "Electric field" sub-section of the oxDNA panel
 * (Dynamics tab).  Lets the user enable a uniform field and set its magnitude
 * (force per nucleotide, pN) + direction, driving an in-scene direction/magnitude
 * arrow gizmo.  It is one independently-addable element of the consolidated
 * production run; it exposes the assembled field spec via getFieldSpec().
 *
 * Anchors are NOT owned here anymore — they live in the shared "Anchors" card
 * (ui/oxdna_anchors_setup.js).  The field still REQUIRES ≥1 anchor to run (an
 * unanchored uniform force drifts the whole structure across the box), but that
 * rule is enforced where the run is assembled (the panel) + by the backend.
 *
 * Display-layer only: nothing here mutates topology.  All physics math lives in
 * scene/efield_math.js (pure, unit-tested); this module is DOM wiring.
 *
 * Factory: initEfieldSetup({ gizmo, onChange }) → { getFieldSpec, isEnabled,
 *   refresh }.  getFieldSpec() → { field_pN, dir, enabled }.
 */

import {
  DEFAULT_Q_EFF, fieldVpmToPn, pnToFieldVpm,
  arrowLenForPn, pnForArrowLen, nmPerPnForN, scaleVec, normalize, vecLen,
  fieldColorHex, fieldZone,
} from '../scene/efield_math.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', dim: '#8b949e', accent: '#4a9eff', err: '#d9534f' }

function _fmtPn(p) {
  const n = Number(p) || 0
  if (n === 0) return '0'
  return n.toPrecision(4).replace(/\.?0+$/, '')
}

export function initEfieldSetup({ gizmo, onChange = null, getBaseCount = null } = {}) {
  const toggle = document.getElementById('efield-toggle')
  const arrow  = document.getElementById('efield-arrow')
  const bodyEl = document.getElementById('efield-body')
  if (!toggle || !bodyEl) {
    return { getFieldSpec: () => ({ field_pN: 0, dir: [0, 1, 0], enabled: false }), isEnabled: () => false, refresh: () => {}, applyConfig: () => {} }
  }

  const enableChk  = document.getElementById('efield-enable')
  const magInput   = document.getElementById('efield-mag')
  const vpmToggle  = document.getElementById('efield-vpm-toggle')
  const vpmArrow   = document.getElementById('efield-vpm-arrow')
  const vpmBody    = document.getElementById('efield-vpm-body')
  const vpmInput   = document.getElementById('efield-vpm')
  const qeffInput  = document.getElementById('efield-qeff')
  const vpmApply   = document.getElementById('efield-vpm-apply')
  const dirX = document.getElementById('efield-dir-x')
  const dirY = document.getElementById('efield-dir-y')
  const dirZ = document.getElementById('efield-dir-z')
  const readyEl  = document.getElementById('efield-ready')

  // ── State (canonical values; the gizmo mirrors them) ───────────────────────
  let _open    = false
  let _pN      = 0
  let _qEff    = DEFAULT_Q_EFF
  let _enabled = false
  // True while a selected oxDNA job applied (or is applying) a field — keeps the
  // direction arrow visible even when the card is collapsed.
  let _jobFieldActive = false

  if (qeffInput) qeffInput.value = String(DEFAULT_Q_EFF)
  if (dirX) dirX.value = '0'
  if (dirY) dirY.value = '1'
  if (dirZ) dirZ.value = '0'

  // ── Direction helpers ──────────────────────────────────────────────────────
  function _dirFromInputs() {
    return normalize([parseFloat(dirX?.value || '0'), parseFloat(dirY?.value || '1'), parseFloat(dirZ?.value || '0')])
  }
  function _currentDir() {
    if (gizmo?.isActive?.()) {
      const v = gizmo.getVector()
      if (vecLen(v) > 1e-6) return normalize(v)
    }
    return _dirFromInputs()
  }
  // Arrow length ⇄ pN scale for THIS design: nm-per-pN grows ∝ base count, so the
  // arrow encodes total force and a given drag is a smaller per-nt force on a big
  // origami (finer control). Falls back to the flat constant with no geometry.
  function _nmPerPn() { return nmPerPnForN(getBaseCount?.() ?? 0) }

  function _pushToGizmo() {
    if (!gizmo) return
    gizmo.setVector(scaleVec(_dirFromInputs(), arrowLenForPn(_pN, _nmPerPn())))
    gizmo.setColor?.(fieldColorHex(_pN))           // absolute field-strength grade
  }
  function _syncInputsFromGizmo() {
    if (magInput) magInput.value = _fmtPn(_pN)
    const d = _currentDir()
    if (dirX) dirX.value = String(+d[0].toFixed(3))
    if (dirY) dirY.value = String(+d[1].toFixed(3))
    if (dirZ) dirZ.value = String(+d[2].toFixed(3))
  }

  // ── Spec ───────────────────────────────────────────────────────────────────
  function getFieldSpec() {
    return { field_pN: _pN, dir: _currentDir(), enabled: _enabled }
  }
  function isEnabled() { return _enabled && _pN > 0 }

  // ── Ready line ───────────────────────────────────────────────────────────────
  function _setReady(text, color = _C.dim) {
    if (readyEl) { readyEl.textContent = text; readyEl.style.color = color }
  }
  function _renderReady() {
    _pushToGizmo()
    onChange?.()
    if (!_enabled) { _setReady('Off — tick "Apply" to add a field to the run.', _C.dim); return }
    if (!(_pN > 0)) { _setReady('Set a force per nucleotide (pN).', _C.dim); return }
    if (!(vecLen(_dirFromInputs()) > 0.5)) { _setReady('Set a field direction.', _C.dim); return }
    const zone = fieldZone(_pN)
    const warn = zone === 'disrupt' ? '⚠ strong enough to disrupt the DNA — ' : (zone === 'strong' ? '⚠ strong field — ' : '')
    const tail = `${_fmtPn(_pN)} pN/nt — needs ≥1 anchor (add a fixed strand in the Anchors card).`
    _setReady(warn + tail, zone === 'disrupt' ? _C.err : (warn ? _C.warn : _C.dim))
  }

  // ── Inputs ───────────────────────────────────────────────────────────────────
  enableChk?.addEventListener('change', () => { _enabled = !!enableChk.checked; _renderReady() })
  magInput?.addEventListener('input', () => { _pN = Math.max(0, parseFloat(magInput.value || '0') || 0); _renderReady() })
  for (const d of [dirX, dirY, dirZ]) d?.addEventListener('input', () => { _renderReady() })
  qeffInput?.addEventListener('input', () => { _qEff = parseFloat(qeffInput.value || String(DEFAULT_Q_EFF)) || DEFAULT_Q_EFF; _syncVpm() })

  function _syncVpm() {
    if (vpmInput && document.activeElement !== vpmInput) vpmInput.value = _pN > 0 ? pnToFieldVpm(_pN, _qEff).toPrecision(3) : ''
  }
  vpmApply?.addEventListener('click', () => {
    const e = parseFloat(vpmInput?.value || '0') || 0
    _pN = Math.max(0, fieldVpmToPn(e, _qEff))
    if (magInput) magInput.value = _fmtPn(_pN)
    _renderReady()
  })
  vpmToggle?.addEventListener('click', () => {
    const o = vpmBody && vpmBody.style.display !== 'none'
    if (vpmBody) vpmBody.style.display = o ? 'none' : ''
    if (vpmArrow) vpmArrow.style.transform = o ? '' : 'rotate(90deg)'
    if (!o) _syncVpm()
  })

  // Gizmo drag → update magnitude (length) + direction inputs live.
  gizmo?.setOnChange?.((vec) => {
    _pN = pnForArrowLen(vecLen(vec), _nmPerPn())
    gizmo.setColor?.(fieldColorHex(_pN))
    _syncInputsFromGizmo(); _syncVpm(); _renderReady()
  })

  // ── Gizmo visibility ───────────────────────────────────────────────────────
  // Show the arrow when the card is open (editing) OR a selected job applied a
  // field — so clicking a field run reveals its direction arrow even with the
  // card collapsed.  Detach only when neither holds.
  function _syncGizmo() {
    if (_open || _jobFieldActive) {
      gizmo?.attach?.([0, 0, 0])
      _pushToGizmo()
    } else {
      gizmo?.detach?.()
    }
  }

  // ── Section open/close (the body; the gizmo follows _syncGizmo) ─────────────
  function _open_() {
    _open = true
    bodyEl.style.display = ''
    if (arrow) arrow.classList.remove('is-collapsed')
    _syncGizmo(); _renderReady()
  }
  function _close_() {
    _open = false
    bodyEl.style.display = 'none'
    if (arrow) arrow.classList.add('is-collapsed')
    _syncGizmo()   // keep the arrow if a field job is still selected
  }
  toggle.addEventListener('click', () => { _open ? _close_() : _open_() })
  _close_()   // start collapsed

  // Drop the gizmo when leaving the Dynamics tab so it never lingers in other tabs
  // (including the job-selected arrow shown with the card collapsed).
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.activeTab !== 'dynamics') {
      _jobFieldActive = false
      if (_open) _close_()
      else _syncGizmo()
    }
  })

  function refresh() { _renderReady() }

  // Repopulate the card from a stored field record ({field_pN, dir} or null) so
  // selecting an oxDNA field run shows that run's magnitude + direction (and, with
  // {open:true}, reveals the direction arrow gizmo).  A null record turns the field
  // off (the card reflects "no field" for plain/surface/relax jobs).
  function applyConfig(field, { open = false } = {}) {
    _enabled = !!field
    _jobFieldActive = !!field          // arrow stays visible for a field job, card open or not
    if (enableChk) enableChk.checked = _enabled
    if (field) {
      _pN = Math.max(0, parseFloat(field.field_pN) || 0)
      if (magInput) magInput.value = _fmtPn(_pN)
      const d = normalize(Array.isArray(field.dir) && field.dir.length === 3 ? field.dir : [0, 1, 0])
      if (dirX) dirX.value = String(+d[0].toFixed(3))
      if (dirY) dirY.value = String(+d[1].toFixed(3))
      if (dirZ) dirZ.value = String(+d[2].toFixed(3))
    }
    if (open && field && !_open) _open_()
    else { _syncGizmo(); _renderReady() }
    _syncVpm()
  }

  return { getFieldSpec, isEnabled, refresh, applyConfig }
}
