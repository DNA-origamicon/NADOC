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
 * The Electric-field card is now the SHARED `initForcesCard` factory (ui/forces_card.js,
 * U2) — the same one that drives the oxDNA/CanDo/NAMD field cards — bound with
 * `engine: 'lammps'` (its own gizmo, +x default dir, weak-warn readout, contextual
 * anchor note read from getAnchorCount).  Anchors + Surface stay inline here; their
 * math is REUSED from scene/efield_math.js + scene/oxdna_floor_math.js.  Display-layer
 * only — nothing here mutates topology.
 *
 * Factory: initLammpsForcesSetup({ gizmo, getSelection, getBaseCount, onChange }) →
 *   { getForces, getAnchors, fieldNeedsAnchor, detachGizmo, refresh }.
 *   getForces() → { field: {field_pN, dir} | null, anchors: [...], wall: {dir, offset_nm, stiff} | null }.
 */

import {
  resolveSelectionAnchors, anchorKey, anchorLabel, addAnchors, removeAnchor,
} from '../scene/efield_math.js'
import { floorSurfaceSpec, formatOffsetNm } from '../scene/oxdna_floor_math.js'
import { initForcesCard } from './forces_card.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', dim: '#8b949e', err: '#d9534f' }

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

  // ── Field card (the SHARED forces factory, LAMMPS-flavoured) ────────────────
  // The card owns the gizmo, magnitude/direction inputs, and the ready line; it reads
  // the live anchor count for its "add ≥1 anchor" note and pushes changes via onChange.
  const _fieldCard = initForcesCard({
    engine: 'lammps',
    gizmo,
    getBaseCount,
    getAnchorCount: () => _anchors.length,
    onChange: _notify,
  })

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
        x.addEventListener('click', () => { _anchors = removeAnchor(_anchors, anchorKey(a)); _renderAnchors() })
        chip.append(lbl, x)
        listEl.appendChild(chip)
      }
    }
    _fieldCard.refresh()   // the field ready line's anchor note depends on the count
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
    const fs = _fieldCard.getFieldSpec()
    const field = (fs.enabled && fs.field_pN > 0) ? { field_pN: fs.field_pN, dir: fs.dir } : null
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
  function detachGizmo() { _fieldCard.detachGizmo() }

  _renderAnchors(); _renderSurface()
  _ready = true                        // now external side effects (glow / grid) may fire
  return { getForces, getAnchors, fieldNeedsAnchor, detachGizmo, refresh: () => { _renderAnchors(); _renderSurface() } }
}
