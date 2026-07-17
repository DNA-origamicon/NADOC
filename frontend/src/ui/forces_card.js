/**
 * forces_card.js — the ONE shared Electric-field card factory (U2, "unified panel"
 * track).  It collapses the three previously-triplicated field cards into a single
 * `initForcesCard({ engine, ... })`:
 *   • efield_setup.js        — oxDNA (in-scene direction-arrow gizmo)
 *   • cando_efield_setup.js  — CanDo FEM + NAMD (numeric, no gizmo)
 *   • the field third of lammps_forces_setup.js — LAMMPS (gizmo)
 *
 * Every engine emits the SAME canonical field payload — getFieldSpec() →
 * { field_pN, dir, enabled } — over the shared, unit-tested scene/efield_math.js
 * physics (pN↔V/m, normalize, arrow-length↔pN, colour/zone).  This module is pure
 * DOM wiring; nothing here mutates topology (Three-Layer Law: display/Physical only).
 *
 * The per-engine divergences are DATA, not separate code paths:
 *   - gizmo         : passed → arrow card (oxDNA/LAMMPS); omitted → numeric (CanDo/NAMD)
 *   - V/m sub-panel : wired iff its DOM ids exist (oxDNA/CanDo/NAMD have it; LAMMPS doesn't)
 *   - readyStyle    : 'apply' (oxDNA/CanDo/NAMD "needs ≥1 anchor") vs 'lammps'
 *                     (weak-warn + a contextual anchor note read from getAnchorCount)
 *   - gizmoGate     : 'open-or-job' (oxDNA — arrow stays for a selected field job) vs
 *                     'open-and-enabled' (LAMMPS)
 *   - defaultDir    : [0,1,0] (oxDNA/CanDo/NAMD) vs [1,0,0] (LAMMPS)
 *
 * Factory: initForcesCard({ engine, ids?, gizmo?, getBaseCount?, getAnchorCount?,
 *   onChange? }) → { getFieldSpec, isEnabled, refresh, applyConfig, detachGizmo }.
 *   getFieldSpec() → { field_pN, dir, enabled }.
 */

import {
  DEFAULT_Q_EFF, fieldVpmToPn, pnToFieldVpm,
  arrowLenForPn, nmPerPnForN, scaleVec, normalize, vecLen,
  fieldColorHex, fieldZone, EFIELD_PN_LOW,
} from '../scene/efield_math.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', dim: '#8b949e', accent: '#4a9eff', err: '#d9534f' }

/** Per-engine field-card DOM id bags (the toggle/body/inputs the card mounts onto). */
export const FORCES_FIELD_IDS = {
  oxdna: {
    toggle: 'efield-toggle', arrow: 'efield-arrow', body: 'efield-body',
    enable: 'efield-enable', mag: 'efield-mag',
    vpmToggle: 'efield-vpm-toggle', vpmArrow: 'efield-vpm-arrow', vpmBody: 'efield-vpm-body',
    vpm: 'efield-vpm', qeff: 'efield-qeff', vpmApply: 'efield-vpm-apply',
    dirX: 'efield-dir-x', dirY: 'efield-dir-y', dirZ: 'efield-dir-z', ready: 'efield-ready',
  },
  cando: {
    toggle: 'cando-efield-toggle', arrow: 'cando-efield-arrow', body: 'cando-efield-body',
    enable: 'cando-efield-enable', mag: 'cando-efield-mag',
    vpmToggle: 'cando-efield-vpm-toggle', vpmArrow: 'cando-efield-vpm-arrow', vpmBody: 'cando-efield-vpm-body',
    vpm: 'cando-efield-vpm', qeff: 'cando-efield-qeff', vpmApply: 'cando-efield-vpm-apply',
    dirX: 'cando-efield-dir-x', dirY: 'cando-efield-dir-y', dirZ: 'cando-efield-dir-z', ready: 'cando-efield-ready',
  },
  snupi: {
    toggle: 'snupi-efield-toggle', arrow: 'snupi-efield-arrow', body: 'snupi-efield-body',
    enable: 'snupi-efield-enable', mag: 'snupi-efield-mag',
    vpmToggle: 'snupi-efield-vpm-toggle', vpmArrow: 'snupi-efield-vpm-arrow', vpmBody: 'snupi-efield-vpm-body',
    vpm: 'snupi-efield-vpm', qeff: 'snupi-efield-qeff', vpmApply: 'snupi-efield-vpm-apply',
    dirX: 'snupi-efield-dir-x', dirY: 'snupi-efield-dir-y', dirZ: 'snupi-efield-dir-z', ready: 'snupi-efield-ready',
  },
  mrdna: {
    toggle: 'mrdna-efield-toggle', arrow: 'mrdna-efield-arrow', body: 'mrdna-efield-body',
    enable: 'mrdna-efield-enable', mag: 'mrdna-efield-mag',
    vpmToggle: 'mrdna-efield-vpm-toggle', vpmArrow: 'mrdna-efield-vpm-arrow', vpmBody: 'mrdna-efield-vpm-body',
    vpm: 'mrdna-efield-vpm', qeff: 'mrdna-efield-qeff', vpmApply: 'mrdna-efield-vpm-apply',
    dirX: 'mrdna-efield-dir-x', dirY: 'mrdna-efield-dir-y', dirZ: 'mrdna-efield-dir-z', ready: 'mrdna-efield-ready',
  },
  namd: {
    toggle: 'md-efield-toggle', arrow: 'md-efield-arrow', body: 'md-efield-body',
    enable: 'md-efield-enable', mag: 'md-efield-mag',
    vpmToggle: 'md-efield-vpm-toggle', vpmArrow: 'md-efield-vpm-arrow', vpmBody: 'md-efield-vpm-body',
    vpm: 'md-efield-vpm', qeff: 'md-efield-qeff', vpmApply: 'md-efield-vpm-apply',
    dirX: 'md-efield-dir-x', dirY: 'md-efield-dir-y', dirZ: 'md-efield-dir-z', ready: 'md-efield-ready',
  },
  lammps: {
    toggle: 'lammps-field-toggle', arrow: 'lammps-field-arrow', body: 'lammps-field-body',
    enable: 'lammps-field-enable', mag: 'lammps-field-mag',
    // LAMMPS has no V/m helper sub-panel — these ids are absent in index.html, so the
    // vpm block auto-skips (element lookups return null). Direction defaults to +x.
    dirX: 'lammps-field-dir-x', dirY: 'lammps-field-dir-y', dirZ: 'lammps-field-dir-z', ready: 'lammps-field-ready',
  },
}

/** Per-engine behaviour that isn't inferable from the DOM. */
const FORCES_FIELD_VARIANTS = {
  oxdna:  { defaultDir: [0, 1, 0], readyStyle: 'apply', verb: 'run',   gizmoGate: 'open-or-job',      jobArrow: true,  closeOnLeaveTab: true },
  cando:  { defaultDir: [0, 1, 0], readyStyle: 'apply', verb: 'solve', gizmoGate: 'open-or-job',      jobArrow: true,  closeOnLeaveTab: true },
  snupi:  { defaultDir: [0, 1, 0], readyStyle: 'apply', verb: 'solve', gizmoGate: 'open-or-job',      jobArrow: true,  closeOnLeaveTab: true },
  mrdna:  { defaultDir: [0, 1, 0], readyStyle: 'apply', verb: 'run',   gizmoGate: 'open-or-job',      jobArrow: true,  closeOnLeaveTab: true },
  namd:   { defaultDir: [0, 1, 0], readyStyle: 'apply', verb: 'solve', gizmoGate: 'open-or-job',      jobArrow: true,  closeOnLeaveTab: true },
  lammps: { defaultDir: [1, 0, 0], readyStyle: 'lammps', verb: 'run',  gizmoGate: 'open-and-enabled', jobArrow: false, closeOnLeaveTab: false },
}

function _fmtPn(p) {
  const n = Number(p) || 0
  if (n === 0) return '0'
  return n.toPrecision(4).replace(/\.?0+$/, '')
}

export function initForcesCard({
  engine = 'oxdna', ids = {}, gizmo = null,
  getBaseCount = null, getAnchorCount = null, onChange = null,
} = {}) {
  const V = FORCES_FIELD_VARIANTS[engine] || FORCES_FIELD_VARIANTS.oxdna
  const id = { ...(FORCES_FIELD_IDS[engine] || FORCES_FIELD_IDS.oxdna), ...ids }

  const toggle = document.getElementById(id.toggle)
  const arrow  = document.getElementById(id.arrow)
  const bodyEl = document.getElementById(id.body)
  const noop = {
    getFieldSpec: () => ({ field_pN: 0, dir: V.defaultDir.slice(), enabled: false }),
    isEnabled: () => false, refresh: () => {}, applyConfig: () => {}, detachGizmo: () => {},
  }
  if (!toggle || !bodyEl) return noop

  const enableChk = document.getElementById(id.enable)
  const magInput  = document.getElementById(id.mag)
  const vpmToggle = document.getElementById(id.vpmToggle)
  const vpmArrow  = document.getElementById(id.vpmArrow)
  const vpmBody   = document.getElementById(id.vpmBody)
  const vpmInput  = document.getElementById(id.vpm)
  const qeffInput = document.getElementById(id.qeff)
  const vpmApply  = document.getElementById(id.vpmApply)
  const dirX = document.getElementById(id.dirX)
  const dirY = document.getElementById(id.dirY)
  const dirZ = document.getElementById(id.dirZ)
  const readyEl = document.getElementById(id.ready)

  // The legacy DOM supplied three Cartesian boxes. Reuse the first two as a
  // spherical angle editor, and add a display-only arrow-offset disclosure.
  // Building this small shared fragment here keeps every engine card identical.
  let offsetInputs = []
  let gizmoControlsToggle = null
  if (dirX && dirY) {
    const row = dirX.parentElement
    const insertAfterDirection = element => {
      if (row === document.body) row.appendChild(element)
      else row?.insertAdjacentElement('afterend', element)
    }
    const label = row?.querySelector('span')
    if (label) label.textContent = 'Direction (°)'
    dirX.title = 'Azimuth (degrees)'; dirX.step = '5'; dirX.style.width = '62px'
    dirY.title = 'Elevation (degrees)'; dirY.step = '5'; dirY.style.width = '62px'
    dirX.setAttribute('aria-label', 'E-field azimuth in degrees')
    dirY.setAttribute('aria-label', 'E-field elevation in degrees')
    if (dirZ) dirZ.style.display = 'none'
    if (gizmo && row && !row.parentElement?.querySelector('.efield-controls-toggle')) {
      const controlsRow = document.createElement('label')
      controlsRow.className = 'efield-controls-toggle'
      controlsRow.style.cssText = 'display:flex;align-items:center;gap:6px;color:#8b949e;font-size:var(--text-xs);cursor:pointer;margin-top:5px'
      controlsRow.innerHTML = '<input type="checkbox" checked> Show rotation controls'
      insertAfterDirection(controlsRow)
      gizmoControlsToggle = controlsRow.querySelector('input')
    }
    if (row && !row.querySelector('.efield-angle-label')) {
      for (const [input, text] of [[dirX, 'Az'], [dirY, 'El']]) {
        const tag = document.createElement('span')
        tag.className = 'efield-angle-label'
        tag.textContent = text
        tag.style.cssText = 'font-size:10px;color:#6a737d;margin-left:2px'
        row.insertBefore(tag, input)
      }
      const prefix = id.dirX.replace(/dir-x$/, '')
      const section = document.createElement('div')
      section.style.marginTop = '5px'
      section.innerHTML = `<div class="efield-offset-toggle" role="button" tabindex="0" aria-expanded="false" style="cursor:pointer;user-select:none;font-size:var(--text-xs);color:#8b949e;display:flex;align-items:center;gap:4px"><span class="efield-offset-arrow" style="display:inline-block;transition:transform .15s">▸</span><span>Arrow offset (nm)</span></div><div class="efield-offset-body" style="display:none;margin-top:4px;align-items:center;gap:4px"><span style="font-size:10px;color:#6a737d">X</span><input id="${prefix}offset-x" aria-label="Arrow X offset in nm" type="number" value="0" step="2"><span style="font-size:10px;color:#6a737d">Y</span><input id="${prefix}offset-y" aria-label="Arrow Y offset in nm" type="number" value="0" step="2"><span style="font-size:10px;color:#6a737d">Z</span><input id="${prefix}offset-z" aria-label="Arrow Z offset in nm" type="number" value="0" step="2"></div>`
      insertAfterDirection(section)
      offsetInputs = [...section.querySelectorAll('input')]
      for (const input of offsetInputs) input.style.cssText = 'width:52px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:2px 4px;font-size:var(--text-xs)'
      const toggleOffset = () => {
        const body = section.querySelector('.efield-offset-body')
        const open = body.style.display !== 'none'
        body.style.display = open ? 'none' : 'flex'
        section.querySelector('.efield-offset-arrow').style.transform = open ? '' : 'rotate(90deg)'
        section.querySelector('.efield-offset-toggle').setAttribute('aria-expanded', String(!open))
      }
      section.querySelector('.efield-offset-toggle').addEventListener('click', toggleOffset)
      section.querySelector('.efield-offset-toggle').addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleOffset() }
      })
    }
  }

  // ── State (canonical values; the gizmo mirrors them) ───────────────────────
  let _open    = false
  let _pN      = 0
  let _qEff    = DEFAULT_Q_EFF
  let _enabled = false
  let _offset = [0, 0, 0]
  let _showGizmoControls = true
  // oxDNA/CanDo/NAMD: stays true while a selected job applied a field, so the arrow
  // (oxDNA) or the enabled state persists with the card collapsed.
  let _jobFieldActive = false

  if (qeffInput) qeffInput.value = String(DEFAULT_Q_EFF)
  function _anglesFromDir(d) {
    const n = normalize(d)
    return [Math.atan2(n[2], n[0]) * 180 / Math.PI, Math.asin(Math.max(-1, Math.min(1, n[1]))) * 180 / Math.PI]
  }
  function _dirFromAngles(azimuth, elevation) {
    const az = azimuth * Math.PI / 180, el = elevation * Math.PI / 180
    const c = Math.cos(el)
    return normalize([c * Math.cos(az), Math.sin(el), c * Math.sin(az)])
      .map(v => Math.abs(v) < 1e-12 ? 0 : v)
  }
  const [az0, el0] = _anglesFromDir(V.defaultDir)
  if (dirX) dirX.value = String(+az0.toFixed(1))
  if (dirY) dirY.value = String(+el0.toFixed(1))
  if (dirZ) dirZ.value = '0'

  // ── Direction helpers ──────────────────────────────────────────────────────
  function _dirFromInputs() {
    return _dirFromAngles(
      parseFloat(dirX?.value ?? String(az0)) || 0,
      Math.max(-90, Math.min(90, parseFloat(dirY?.value ?? String(el0)) || 0)),
    )
  }
  function _currentDir() {
    if (gizmo?.isActive?.()) {
      const v = gizmo.getVector()
      if (vecLen(v) > 1e-6) return normalize(v)
    }
    return _dirFromInputs()
  }
  // nm-per-pN grows ∝ base count → the arrow encodes total force; a given drag is a
  // smaller per-nt force on a big origami (finer control). Flat fallback w/o geometry.
  function _nmPerPn() { return nmPerPnForN(getBaseCount?.() ?? 0) }
  function _gizmoOrigin() { return _offset.slice() }

  function _pushToGizmo() {
    if (!gizmo) return
    const direction = _dirFromInputs()
    const arrowLength = arrowLenForPn(_pN, _nmPerPn())
    if (gizmo.setDirection) {
      gizmo.setDirection(direction)
      gizmo.setArrowLength?.(arrowLength)
      gizmo.setOffset?.(_gizmoOrigin())
    } else gizmo.setVector(scaleVec(direction, arrowLength))
    gizmo.setColor?.(fieldColorHex(_pN))
  }
  function _syncInputsFromGizmo() {
    if (magInput) magInput.value = _fmtPn(_pN)
    const d = _currentDir()
    const [az, el] = _anglesFromDir(d)
    if (dirX) dirX.value = String(+az.toFixed(1))
    if (dirY) dirY.value = String(+el.toFixed(1))
  }

  // ── Spec (the identical payload across every engine) ────────────────────────
  function getFieldSpec() { return { field_pN: _pN, dir: _currentDir(), enabled: _enabled } }
  function isEnabled() { return _enabled && _pN > 0 }

  // ── Ready line ──────────────────────────────────────────────────────────────
  function _setReady(text, color = _C.dim) {
    if (readyEl) { readyEl.textContent = text; readyEl.style.color = color }
  }
  function _renderReady() {
    if (gizmo) _syncGizmo()
    onChange?.()
    if (V.readyStyle === 'lammps') { _renderReadyLammps(); return }
    // 'apply' style (oxDNA / CanDo / NAMD).  An anchor is recommended but no longer
    // required — a field with no anchor drifts the whole structure (COM drift), which
    // we surface as a WARNING notice here; the run is not blocked.
    if (!_enabled) { _setReady(`Off — tick "Apply" to add a field to the ${V.verb}.`, _C.dim); return }
    if (!(_pN > 0)) { _setReady('Set a force per nucleotide (pN).', _C.dim); return }
    if (!(vecLen(_dirFromInputs()) > 0.5)) { _setReady('Set a field direction.', _C.dim); return }
    const zone = fieldZone(_pN)
    const strengthWarn = zone === 'disrupt' ? '⚠ strong enough to disrupt the DNA — ' : (zone === 'strong' ? '⚠ strong field — ' : '')
    if ((getAnchorCount?.() ?? 0) === 0) {
      _setReady(`${strengthWarn}⚠ no anchor — the whole structure will drift down-field; `
        + `add a fixed strand in the Anchors card to hold it (or run as-is). ${_fmtPn(_pN)} pN/nt.`,
        zone === 'disrupt' ? _C.err : _C.warn)
      return
    }
    _setReady(`${strengthWarn}${_fmtPn(_pN)} pN/nt.`, zone === 'disrupt' ? _C.err : (strengthWarn ? _C.warn : _C.dim))
  }
  function _renderReadyLammps() {
    if (!_enabled) { _setReady('Off — tick to add a uniform E-field to the run.', _C.dim); return }
    if (!(_pN > 0)) { _setReady('Set a force per nucleotide (pN).', _C.dim); return }
    if (!(vecLen(_dirFromInputs()) > 0.5)) { _setReady('Set a field direction.', _C.dim); return }
    const zone = fieldZone(_pN)
    const anchorNote = (getAnchorCount?.() ?? 0) ? '' : ' — add ≥1 anchor'
    if (_pN < EFIELD_PN_LOW) {   // below the useful floor: warn it won't visibly deform
      _setReady(`⚠ very weak (${_fmtPn(_pN)} pN/nt) — unlikely to visibly deform${anchorNote}.`, _C.warn)
      return
    }
    const warn = zone === 'disrupt' ? '⚠ strong enough to disrupt the DNA — ' : (zone === 'strong' ? '⚠ strong field — ' : '')
    _setReady(`${warn}${_fmtPn(_pN)} pN/nt${anchorNote}.`,
      zone === 'disrupt' ? _C.err : (warn || anchorNote ? _C.warn : _C.dim))
  }

  // ── V/m helper sub-panel (present iff its DOM ids exist) ─────────────────────
  function _syncVpm() {
    if (vpmInput && document.activeElement !== vpmInput) vpmInput.value = _pN > 0 ? pnToFieldVpm(_pN, _qEff).toPrecision(3) : ''
  }

  // ── Inputs ────────────────────────────────────────────────────────────────
  enableChk?.addEventListener('change', () => { _enabled = !!enableChk.checked; _renderReady() })
  magInput?.addEventListener('input', () => { _pN = Math.max(0, parseFloat(magInput.value || '0') || 0); _renderReady(); _syncVpm() })
  for (const d of [dirX, dirY, dirZ]) d?.addEventListener('input', () => { _renderReady() })
  for (const [i, input] of offsetInputs.entries()) input.addEventListener('input', () => {
    _offset[i] = parseFloat(input.value || '0') || 0
    gizmo?.setOffset?.(_gizmoOrigin())
  })
  gizmoControlsToggle?.addEventListener('change', () => {
    _showGizmoControls = !!gizmoControlsToggle.checked
    gizmo?.setControlsVisible?.(_showGizmoControls)
  })
  qeffInput?.addEventListener('input', () => { _qEff = parseFloat(qeffInput.value || String(DEFAULT_Q_EFF)) || DEFAULT_Q_EFF; _syncVpm() })
  vpmApply?.addEventListener('click', () => {
    const e = parseFloat(vpmInput?.value || '0') || 0
    _pN = Math.max(0, fieldVpmToPn(e, _qEff))
    if (magInput) magInput.value = _fmtPn(_pN)
    _renderReady()
  })
  vpmToggle?.addEventListener('click', () => {
    const o = vpmBody && vpmBody.style.display !== 'none'
    // Re-open as `grid` explicitly: the sub-panel layout IS a two-column grid, and a
    // cleared inline display ('') falls back to `block` and mangles it.
    if (vpmBody) vpmBody.style.display = o ? 'none' : 'grid'
    if (vpmArrow) vpmArrow.style.transform = o ? '' : 'rotate(90deg)'
    if (!o) _syncVpm()
  })

  // Ring drag changes direction only. Magnitude remains exclusively controlled by
  // the force input and therefore still controls the rendered arrow length.
  gizmo?.setOnChange?.((vec) => {
    _syncInputsFromGizmo(); _syncVpm(); _renderReady()
  })

  // ── Gizmo visibility ────────────────────────────────────────────────────────
  function _syncGizmo() {
    if (!gizmo) return
    const show = V.gizmoGate === 'open-and-enabled'
      ? (_open && _enabled)
      : (_open || _jobFieldActive)
    if (show) { gizmo.attach?.(_gizmoOrigin()); _pushToGizmo() }
    else gizmo.detach?.()
    if (show) gizmo.setControlsVisible?.(_showGizmoControls)
  }

  // ── Section open/close ────────────────────────────────────────────────────--
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
    _syncGizmo()   // keep the arrow if a field job is still selected (oxDNA gate)
  }
  toggle.addEventListener('click', () => { _open ? _close_() : _open_() })
  _close_()   // start collapsed (no _renderReady → no onChange during construction)

  // Drop the gizmo when leaving the Dynamics tab so it never lingers in other tabs.
  // Both bespoke cards ALWAYS detached on leave (oxDNA cleared _jobFieldActive then
  // _syncGizmo → detach; LAMMPS detached unconditionally). Reproduce that: close the
  // card where it closes on leave (oxDNA), else detach directly — never re-attach.
  if (gizmo) {
    window.addEventListener('nadoc:left-tab-change', (e) => {
      if (e.detail?.activeTab !== 'dynamics') {
        _jobFieldActive = false
        if (V.closeOnLeaveTab && _open) _close_()
        else gizmo.detach?.()
      }
    })
  }

  function refresh() { _renderReady() }
  function detachGizmo() { gizmo?.detach?.() }

  // Repopulate the card from a stored field record ({field_pN, dir} or null) so
  // selecting a completed field job reflects that run's magnitude + direction (and,
  // with {open:true}, reveals the direction arrow for engines that have a gizmo).
  // A null record turns the field off (plain/surface/relax jobs).
  function applyConfig(field, { open = false } = {}) {
    _enabled = !!field
    if (V.jobArrow) _jobFieldActive = !!field   // arrow stays visible for a field job
    if (enableChk) enableChk.checked = _enabled
    if (field) {
      _pN = Math.max(0, parseFloat(field.field_pN) || 0)
      if (magInput) magInput.value = _fmtPn(_pN)
      const d = normalize(Array.isArray(field.dir) && field.dir.length === 3 ? field.dir : V.defaultDir)
      const [az, el] = _anglesFromDir(d)
      if (dirX) dirX.value = String(+az.toFixed(1))
      if (dirY) dirY.value = String(+el.toFixed(1))
    }
    if (open && field && !_open) _open_()
    else { _syncGizmo(); _renderReady() }
    _syncVpm()
  }

  return { getFieldSpec, isEnabled, refresh, applyConfig, detachGizmo }
}
