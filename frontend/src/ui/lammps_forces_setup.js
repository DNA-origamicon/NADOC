/**
 * LAMMPS external-forces setup UI — three independent collapsible cards in the
 * LAMMPS (parallel-oxDNA) section, mirroring the oxDNA panel's separate cards:
 *   • Electric field — a uniform force per nucleotide (pN) + direction (scene arrow gizmo)
 *   • Anchors        — overhangs / strands / domains / clusters / bases held fixed
 *   • Surface        — an axis-aligned hard wall (substrate) the structure can't cross
 *
 * A field REQUIRES ≥1 anchor — an unanchored uniform force nets a COM drift that
 * streams the whole structure across the box (oxDNA GOTCHA 1).  Enforced here (the
 * panel's client gate) and by the backend (400).
 *
 * All physics/geometry math is REUSED from the oxDNA modules — scene/efield_math.js
 * (field + anchor helpers) and scene/oxdna_floor_math.js (surface spec) — so this is
 * pure DOM wiring; the arrow is the same efield_gizmo (a separate instance, group
 * 'lammps-efield-gizmo').  Display-layer only — nothing here mutates topology.
 *
 * Factory: initLammpsForcesSetup({ gizmo, getSelection, getBaseCount, onChange }) →
 *   { getForces, fieldNeedsAnchor, detachGizmo, refresh }.
 *   getForces() → { field: {field_pN, dir} | null, anchors: [...], wall: {dir, offset_nm, stiff} | null }.
 */

import {
  arrowLenForPn, pnForArrowLen, nmPerPnForN, scaleVec, normalize, vecLen,
  fieldColorHex, fieldZone, EFIELD_PN_LOW,
  resolveSelectionAnchors, anchorKey, anchorLabel, addAnchors, removeAnchor,
} from '../scene/efield_math.js'
import { floorSurfaceSpec, formatOffsetNm } from '../scene/oxdna_floor_math.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', dim: '#8b949e', err: '#d9534f' }

function _fmtPn(p) {
  const n = Number(p) || 0
  if (n === 0) return '0'
  return n.toPrecision(4).replace(/\.?0+$/, '')
}

/** Wire a collapsible card (toggle/body/arrow) → { isOpen, open, close }. */
function _card($, toggleId, bodyId, arrowId, { onOpen = null, onClose = null } = {}) {
  const toggle = $(toggleId), body = $(bodyId), arrow = $(arrowId)
  if (!toggle || !body) return { isOpen: () => false, open: () => {}, close: () => {}, present: false }
  let open = false
  const doOpen = () => { open = true; body.style.display = ''; arrow?.classList.remove('is-collapsed'); onOpen?.() }
  const doClose = () => { open = false; body.style.display = 'none'; arrow?.classList.add('is-collapsed'); onClose?.() }
  toggle.addEventListener('click', () => (open ? doClose() : doOpen()))
  doClose()
  return { isOpen: () => open, open: doOpen, close: doClose, present: true }
}

export function initLammpsForcesSetup({
  gizmo = null, getSelection = null, getBaseCount = null, onChange = null, setSurfaceGrid = null,
} = {}) {
  const $ = (id) => document.getElementById(id)
  const noop = {
    getForces: () => ({ field: null, anchors: [], wall: null }), getAnchors: () => [],
    fieldNeedsAnchor: () => false, detachGizmo: () => {}, refresh: () => {},
  }
  // Require at least one of the three cards to exist.
  if (!$('lammps-field-toggle') && !$('lammps-anchors-toggle') && !$('lammps-surface-toggle')) return noop

  // onChange / surface-grid pushes are external side effects (anchor glow, View grid)
  // that reference consts created after this factory in main.js — never fire them
  // during construction (would TDZ), only after the initial render settles.
  let _ready = false
  const _notify = () => { if (_ready) onChange?.() }

  // ── Field card ────────────────────────────────────────────────────────────
  const enableChk = $('lammps-field-enable')
  const magInput  = $('lammps-field-mag')
  const dirX = $('lammps-field-dir-x'), dirY = $('lammps-field-dir-y'), dirZ = $('lammps-field-dir-z')
  const fieldReady = $('lammps-field-ready')
  let _pN = 0, _fieldEnabled = false
  let fieldCard = null                 // assigned below; _syncGizmo reads it (null-safe)
  if (dirX) dirX.value = '1'
  if (dirY) dirY.value = '0'
  if (dirZ) dirZ.value = '0'

  function _dirFromInputs() {
    return normalize([parseFloat(dirX?.value || '0'), parseFloat(dirY?.value || '0'), parseFloat(dirZ?.value || '0')])
  }
  function _currentDir() {
    if (gizmo?.isActive?.()) {
      const v = gizmo.getVector()
      if (vecLen(v) > 1e-6) return normalize(v)
    }
    return _dirFromInputs()
  }
  function _nmPerPn() { return nmPerPnForN(getBaseCount?.() ?? 0) }
  function _pushToGizmo() {
    if (!gizmo) return
    gizmo.setVector(scaleVec(_dirFromInputs(), arrowLenForPn(_pN, _nmPerPn())))
    gizmo.setColor?.(fieldColorHex(_pN))
  }
  function _syncGizmo() {
    // fieldCard is assigned after this fn (its own _card init calls back here) → guard.
    if (fieldCard?.isOpen?.() && _fieldEnabled) { gizmo?.attach?.([0, 0, 0]); _pushToGizmo() }
    else gizmo?.detach?.()
  }
  function _setFieldReady(text, color = _C.dim) {
    if (fieldReady) { fieldReady.textContent = text; fieldReady.style.color = color }
  }
  function _renderFieldReady() {
    _syncGizmo()
    _notify()
    if (!_fieldEnabled) { _setFieldReady('Off — tick to add a uniform E-field to the run.'); return }
    if (!(_pN > 0)) { _setFieldReady('Set a force per nucleotide (pN).'); return }
    if (!(vecLen(_dirFromInputs()) > 0.5)) { _setFieldReady('Set a field direction.'); return }
    const zone = fieldZone(_pN)
    const anchorNote = _anchors.length ? '' : ' — add ≥1 anchor'
    if (_pN < EFIELD_PN_LOW) {   // below the useful floor: warn it won't visibly deform
      _setFieldReady(`⚠ very weak (${_fmtPn(_pN)} pN/nt) — unlikely to visibly deform${anchorNote}.`, _C.warn)
      return
    }
    const warn = zone === 'disrupt' ? '⚠ strong enough to disrupt the DNA — '
      : (zone === 'strong' ? '⚠ strong field — ' : '')
    _setFieldReady(`${warn}${_fmtPn(_pN)} pN/nt${anchorNote}.`,
      zone === 'disrupt' ? _C.err : (warn || anchorNote ? _C.warn : _C.dim))
  }
  enableChk?.addEventListener('change', () => { _fieldEnabled = !!enableChk.checked; _renderFieldReady() })
  magInput?.addEventListener('input', () => { _pN = Math.max(0, parseFloat(magInput.value || '0') || 0); _renderFieldReady() })
  for (const d of [dirX, dirY, dirZ]) d?.addEventListener('input', () => _renderFieldReady())
  gizmo?.setOnChange?.((vec) => {
    _pN = pnForArrowLen(vecLen(vec), _nmPerPn())
    gizmo.setColor?.(fieldColorHex(_pN))
    if (magInput) magInput.value = _fmtPn(_pN)
    const d = _currentDir()
    if (dirX) dirX.value = String(+d[0].toFixed(3))
    if (dirY) dirY.value = String(+d[1].toFixed(3))
    if (dirZ) dirZ.value = String(+d[2].toFixed(3))
    _renderFieldReady()
  })
  fieldCard = _card($, 'lammps-field-toggle', 'lammps-field-body', 'lammps-field-arrow',
    { onOpen: _syncGizmo, onClose: _syncGizmo })

  // ── Anchors card ──────────────────────────────────────────────────────────
  const addBtn = $('lammps-anchors-add'), clearBtn = $('lammps-anchors-clear')
  const listEl = $('lammps-anchors-list'), anchorStatus = $('lammps-anchors-status')
  let _anchors = []
  function _renderAnchors() {
    if (anchorStatus) {
      const n = _anchors.length
      anchorStatus.textContent = n
        ? `${n} anchored element${n === 1 ? '' : 's'} held fixed.`
        : 'No anchors — a field needs at least one.'
      anchorStatus.style.color = _C.dim
    }
    if (listEl) {
      listEl.innerHTML = ''
      for (const a of _anchors) {
        const chip = document.createElement('span')
        chip.dataset.key = anchorKey(a)
        chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;margin:2px 4px 2px 0;padding:2px 6px;' +
          'background:#1c2733;border:1px solid #30363d;border-radius:10px;font-size:var(--text-xs);color:#c9d1d9'
        const lbl = document.createElement('span'); lbl.textContent = anchorLabel(a)
        const x = document.createElement('span')
        x.textContent = '×'; x.style.cssText = 'cursor:pointer;color:#8b949e;font-weight:700'
        x.addEventListener('click', () => { _anchors = removeAnchor(_anchors, anchorKey(a)); _renderAnchors(); _renderFieldReady() })
        chip.append(lbl, x)
        listEl.appendChild(chip)
      }
    }
    _renderFieldReady()
  }
  function _addSelected() {
    const found = resolveSelectionAnchors(getSelection ? getSelection() : null)
    if (!found.length) {
      if (anchorStatus) {
        anchorStatus.textContent = 'Select an overhang, strand, domain, cluster, or base first.'
        anchorStatus.style.color = _C.warn
      }
      return 0
    }
    const before = _anchors.length
    _anchors = addAnchors(_anchors, found)
    _renderAnchors()
    return _anchors.length - before
  }
  addBtn?.addEventListener('click', _addSelected)
  clearBtn?.addEventListener('click', () => { _anchors = []; _renderAnchors() })
  _card($, 'lammps-anchors-toggle', 'lammps-anchors-body', 'lammps-anchors-arrow', { onOpen: _renderAnchors })

  // ── Surface card ──────────────────────────────────────────────────────────
  const surfEnable = $('lammps-surface-enable')
  const surfControls = $('lammps-surface-controls')
  const axisSel = $('lammps-surface-axis')
  const offsetIn = $('lammps-surface-offset'), offsetLbl = $('lammps-surface-offset-label')
  const stiffIn = $('lammps-surface-stiff'), surfReady = $('lammps-surface-ready')
  let _surfaceEnabled = false
  function _surfaceSpec() {
    return floorSurfaceSpec({
      axis: axisSel?.value || '-y',
      offsetNm: parseFloat(offsetIn?.value || '0'),
      stiff: parseFloat(stiffIn?.value || '0'),
    })
  }
  function _pushGrid() {
    if (!_ready) return
    setSurfaceGrid?.({
      enabled: _surfaceEnabled,
      axis: axisSel?.value || '-y',
      offsetNm: parseFloat(offsetIn?.value || '0'),
    })
  }
  function _renderSurface() {
    if (surfControls) surfControls.style.display = _surfaceEnabled ? 'flex' : 'none'
    if (offsetLbl && offsetIn) offsetLbl.textContent = formatOffsetNm(parseFloat(offsetIn.value || '0'))
    _pushGrid()
    _notify()
    if (!surfReady) return
    if (!_surfaceEnabled) { surfReady.textContent = 'Off — tick to rest the structure on a hard wall.'; surfReady.style.color = _C.dim; return }
    const spec = _surfaceSpec()
    if (!spec || !(spec.stiff > 0)) { surfReady.textContent = 'Set a stiffness > 0.'; surfReady.style.color = _C.warn; return }
    surfReady.textContent = `Hard wall on the ${axisSel?.value || '-y'} side, ${formatOffsetNm(spec.offsetNm)} clearance.`
    surfReady.style.color = _C.dim
  }
  surfEnable?.addEventListener('change', () => { _surfaceEnabled = !!surfEnable.checked; _renderSurface() })
  axisSel?.addEventListener('change', _renderSurface)
  offsetIn?.addEventListener('input', _renderSurface)
  stiffIn?.addEventListener('input', _renderSurface)
  _card($, 'lammps-surface-toggle', 'lammps-surface-body', 'lammps-surface-arrow', { onOpen: _renderSurface })

  // ── public API ──────────────────────────────────────────────────────────--
  function getForces() {
    const field = (_fieldEnabled && _pN > 0) ? { field_pN: _pN, dir: _currentDir() } : null
    const spec = _surfaceEnabled ? _surfaceSpec() : null
    const wall = (spec && spec.stiff > 0)
      ? { dir: spec.dir, offset_nm: spec.offsetNm, stiff: spec.stiff } : null
    return { field, anchors: _anchors.slice(), wall }
  }
  function getAnchors() { return _anchors.slice() }
  function fieldNeedsAnchor() {
    const { field, anchors } = getForces()
    return !!field && anchors.length === 0
  }
  function detachGizmo() { gizmo?.detach?.() }
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.activeTab !== 'dynamics') detachGizmo()
  })

  _renderAnchors(); _renderSurface()
  _ready = true                        // now external side effects (glow / grid) may fire
  return { getForces, getAnchors, fieldNeedsAnchor, detachGizmo, refresh: () => { _renderAnchors(); _renderSurface() } }
}
