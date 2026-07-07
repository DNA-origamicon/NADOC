/**
 * CanDo E-field setup UI — the "Electric field" collapsible card of the CanDo FEM
 * panel (Dynamics tab).  A numeric mimic of the oxDNA field card (ui/efield_setup.js):
 * a uniform force per nucleotide (pN) + direction that the FEM solve applies as a body
 * load, exposed via getFieldSpec() → { field_pN, dir, enabled }.
 *
 * Why a separate module (not the oxDNA factory reused): the CanDo panel shares the
 * Dynamics tab with the oxDNA panel, whose field card already owns the ONE in-scene
 * direction-arrow gizmo — a second gizmo would double-draw.  So this card is numeric
 * only (magnitude + x/y/z + V/m helper); all the field PHYSICS is still the shared,
 * unit-tested scene/efield_math.js (identical pN↔V/m + normalize), so there is no
 * duplicated math.  Display-layer only: nothing here mutates topology.
 *
 * Factory: initCandoEfieldSetup({ onChange }) → { getFieldSpec, isEnabled, refresh,
 *   applyConfig }.  getFieldSpec() → { field_pN, dir, enabled }.
 */

import {
  DEFAULT_Q_EFF, fieldVpmToPn, pnToFieldVpm, normalize, vecLen, fieldZone,
} from '../scene/efield_math.js'

const _C = { dim: '#8b949e', warn: '#e0a800', err: '#d9534f' }

function _fmtPn(p) {
  const n = Number(p) || 0
  if (n === 0) return '0'
  return n.toPrecision(4).replace(/\.?0+$/, '')
}

export function initCandoEfieldSetup({ onChange = null } = {}) {
  const toggle = document.getElementById('cando-efield-toggle')
  const arrow  = document.getElementById('cando-efield-arrow')
  const bodyEl = document.getElementById('cando-efield-body')
  const noop = { getFieldSpec: () => ({ field_pN: 0, dir: [0, 1, 0], enabled: false }), isEnabled: () => false, refresh: () => {}, applyConfig: () => {} }
  if (!toggle || !bodyEl) return noop

  const enableChk = document.getElementById('cando-efield-enable')
  const magInput  = document.getElementById('cando-efield-mag')
  const vpmToggle = document.getElementById('cando-efield-vpm-toggle')
  const vpmArrow  = document.getElementById('cando-efield-vpm-arrow')
  const vpmBody   = document.getElementById('cando-efield-vpm-body')
  const vpmInput  = document.getElementById('cando-efield-vpm')
  const qeffInput = document.getElementById('cando-efield-qeff')
  const vpmApply  = document.getElementById('cando-efield-vpm-apply')
  const dirX = document.getElementById('cando-efield-dir-x')
  const dirY = document.getElementById('cando-efield-dir-y')
  const dirZ = document.getElementById('cando-efield-dir-z')
  const readyEl = document.getElementById('cando-efield-ready')

  let _open    = false
  let _pN      = 0
  let _qEff    = DEFAULT_Q_EFF
  let _enabled = false

  if (qeffInput) qeffInput.value = String(DEFAULT_Q_EFF)
  if (dirX) dirX.value = '0'
  if (dirY) dirY.value = '1'
  if (dirZ) dirZ.value = '0'

  function _dir() {
    return normalize([parseFloat(dirX?.value || '0'), parseFloat(dirY?.value || '1'), parseFloat(dirZ?.value || '0')])
  }

  function getFieldSpec() { return { field_pN: _pN, dir: _dir(), enabled: _enabled } }
  function isEnabled() { return _enabled && _pN > 0 }

  function _setReady(text, color = _C.dim) {
    if (readyEl) { readyEl.textContent = text; readyEl.style.color = color }
  }
  function _renderReady() {
    onChange?.()
    if (!_enabled) { _setReady('Off — tick "Apply" to add a field to the solve.', _C.dim); return }
    if (!(_pN > 0)) { _setReady('Set a force per nucleotide (pN).', _C.dim); return }
    if (!(vecLen(_dir()) > 0.5)) { _setReady('Set a field direction.', _C.dim); return }
    const zone = fieldZone(_pN)
    const warn = zone === 'disrupt' ? '⚠ strong enough to disrupt the DNA — ' : (zone === 'strong' ? '⚠ strong field — ' : '')
    const tail = `${_fmtPn(_pN)} pN/nt — needs ≥1 anchor (add a fixed strand in the Anchors card).`
    _setReady(warn + tail, zone === 'disrupt' ? _C.err : (warn ? _C.warn : _C.dim))
  }

  function _syncVpm() {
    if (vpmInput && document.activeElement !== vpmInput) vpmInput.value = _pN > 0 ? pnToFieldVpm(_pN, _qEff).toPrecision(3) : ''
  }

  enableChk?.addEventListener('change', () => { _enabled = !!enableChk.checked; _renderReady() })
  magInput?.addEventListener('input', () => { _pN = Math.max(0, parseFloat(magInput.value || '0') || 0); _renderReady(); _syncVpm() })
  for (const d of [dirX, dirY, dirZ]) d?.addEventListener('input', () => { _renderReady() })
  qeffInput?.addEventListener('input', () => { _qEff = parseFloat(qeffInput.value || String(DEFAULT_Q_EFF)) || DEFAULT_Q_EFF; _syncVpm() })
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

  function _open_()  { _open = true;  bodyEl.style.display = ''; if (arrow) arrow.classList.remove('is-collapsed'); _renderReady() }
  function _close_() { _open = false; bodyEl.style.display = 'none'; if (arrow) arrow.classList.add('is-collapsed') }
  toggle.addEventListener('click', () => { _open ? _close_() : _open_() })
  _close_()

  function refresh() { _renderReady() }

  // Repopulate from a stored field record ({field_pN, dir} or null) so selecting a
  // completed CanDo field job reflects that solve's magnitude + direction.
  function applyConfig(field, { open = false } = {}) {
    _enabled = !!field
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
    else _renderReady()
    _syncVpm()
  }

  return { getFieldSpec, isEnabled, refresh, applyConfig }
}
