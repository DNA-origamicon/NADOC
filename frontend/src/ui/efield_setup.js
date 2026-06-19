/**
 * Electric-field setup UI — the "Electric field" sub-section of the oxDNA panel
 * (Dynamics tab).  Lets the user set a field magnitude + direction and mark
 * clusters / domains / overhangs as anchors (the parts held fixed while the rest
 * deflects).  It drives the in-scene direction/magnitude gizmo and exposes the
 * assembled field spec via getFieldSpec() for the later run-wiring phase.
 *
 * Display-layer only: nothing here mutates topology.  All physics math lives in
 * scene/efield_math.js (pure, unit-tested); this module is DOM wiring.
 *
 * Factory: initEfieldSetup({ store, gizmo, getSelection }) → { getFieldSpec,
 *   getAnchors, addSelectedAnchors, refresh }.
 *   - gizmo: an initEfieldGizmo(...) instance (direction/magnitude arrow).
 *   - getSelection: () => store-state snapshot (passed to resolveSelectionAnchors).
 */

import {
  DEFAULT_Q_EFF, fieldVpmToPn, pnToFieldVpm,
  arrowLenForPn, pnForArrowLen, scaleVec, normalize, vecLen,
  resolveSelectionAnchors, anchorKey, anchorLabel, addAnchors, removeAnchor,
  buildFieldSpec, fieldSpecReady, fieldColorHex, fieldZone,
} from '../scene/efield_math.js'
import { showToast } from './toast.js'
import * as api from '../api/client.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', dim: '#8b949e', accent: '#4a9eff', err: '#d9534f' }

const _fmtPn = (p) => {
  const n = Number(p) || 0
  if (n === 0) return '0'
  return n.toPrecision(4).replace(/\.?0+$/, '')
}

export function initEfieldSetup({ store, gizmo, getSelection, getSelectedJob = null, onRan = null } = {}) {
  const toggle = document.getElementById('efield-toggle')
  const arrow  = document.getElementById('efield-arrow')
  const bodyEl = document.getElementById('efield-body')
  if (!toggle || !bodyEl) return { getFieldSpec: () => null, getAnchors: () => [], addSelectedAnchors: () => 0, runField: async () => false, refresh: () => {} }

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
  const addBtn   = document.getElementById('efield-anchor-add')
  const clearBtn = document.getElementById('efield-anchor-clear')
  const listEl   = document.getElementById('efield-anchors-list')
  const readyEl  = document.getElementById('efield-ready')
  const stepsInput = document.getElementById('efield-steps')
  const runBtn   = document.getElementById('efield-run-btn')

  // ── State (canonical values; the gizmo mirrors them) ───────────────────────
  let _open    = false
  let _pN      = 0
  let _qEff    = DEFAULT_Q_EFF
  let _anchors = []

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
  function _pushToGizmo() {
    if (!gizmo) return
    gizmo.setVector(scaleVec(_dirFromInputs(), arrowLenForPn(_pN)))
    gizmo.setColor?.(fieldColorHex(_pN))   // magnitude grade: blue → green → red
  }
  function _syncInputsFromGizmo() {
    if (magInput) magInput.value = _fmtPn(_pN)
    const d = _currentDir()
    if (dirX) dirX.value = String(+d[0].toFixed(3))
    if (dirY) dirY.value = String(+d[1].toFixed(3))
    if (dirZ) dirZ.value = String(+d[2].toFixed(3))
  }

  // ── Anchors ────────────────────────────────────────────────────────────────
  function _renderAnchors() {
    if (!listEl) return
    listEl.innerHTML = ''
    if (!_anchors.length) {
      listEl.innerHTML = `<div style="color:${_C.dim};font-size:var(--text-xs);padding:2px 0">No anchors — select an overhang, domain, or cluster and "Add".</div>`
      return
    }
    for (const a of _anchors) {
      const chip = document.createElement('span')
      chip.dataset.key = anchorKey(a)
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;margin:2px 4px 2px 0;padding:2px 6px;' +
        'background:#1c2733;border:1px solid #30363d;border-radius:10px;font-size:var(--text-xs);color:#c9d1d9'
      const lbl = document.createElement('span'); lbl.textContent = anchorLabel(a)
      const x = document.createElement('span')
      x.textContent = '×'; x.style.cssText = 'cursor:pointer;color:#8b949e;font-weight:700'
      x.addEventListener('click', () => { _anchors = removeAnchor(_anchors, anchorKey(a)); _renderAnchors(); _renderReady() })
      chip.append(lbl, x)
      listEl.appendChild(chip)
    }
  }

  function addSelectedAnchors() {
    const found = resolveSelectionAnchors(getSelection ? getSelection() : store?.getState?.())
    if (!found.length) {
      _setReady('Select an overhang, domain, or cluster first (overhang recommended).', _C.warn)
      return 0
    }
    const before = _anchors.length
    _anchors = addAnchors(_anchors, found)
    _renderAnchors(); _renderReady()
    return _anchors.length - before
  }

  // ── Ready gate ───────────────────────────────────────────────────────────
  function _setReady(text, color = _C.dim) {
    if (readyEl) { readyEl.textContent = text; readyEl.style.color = color }
  }
  function _renderReady() {
    const spec = getFieldSpec()
    const job = getSelectedJob ? getSelectedJob() : null
    const specOk = fieldSpecReady(spec)
    // A field run branches from a completed RELAXED job, not from another field run.
    const jobOk = !!job && job.status === 'completed' && !job.parent_job_id
    const runnable = specOk && jobOk
    if (runBtn) {
      runBtn.disabled = !runnable
      runBtn.style.cursor = runnable ? 'pointer' : 'not-allowed'
      runBtn.style.background = runnable ? '#1a3a4a' : '#122117'
      runBtn.style.borderColor = runnable ? '#4a9eff' : '#30363d'
      runBtn.style.color = runnable ? '#4a9eff' : '#484f58'
    }

    if (!specOk) {
      const why = []
      if (!(spec.field_pN > 0)) why.push('set a magnitude')
      if (!(vecLen(spec.dir) > 0.5)) why.push('set a direction')
      if (!spec.anchors.length) why.push('add ≥1 anchor (else the field just drifts the whole structure)')
      _setReady('Not ready — ' + why.join(', ') + '.', _C.dim)
      return
    }
    // Magnitude warning: a field strong enough to disrupt the DNA.
    const warn = fieldZone(spec.field_pN) === 'disrupt'
      ? '⚠ field strong enough to disrupt the DNA — ' : ''
    const summary = `${_fmtPn(spec.field_pN)} pN/nt · ${spec.anchors.length} anchor${spec.anchors.length === 1 ? '' : 's'}`
    if (job && job.parent_job_id) {
      _setReady(`${warn}Field set (${summary}) — select the parent relaxed job (not a field run) to branch from.`, warn ? _C.err : _C.warn); return
    }
    if (!job) { _setReady(`${warn}Field set (${summary}) — select a completed oxDNA job above to run.`, warn ? _C.err : _C.warn); return }
    if (!jobOk) { _setReady(`${warn}Field set (${summary}) — selected job is "${job.status}"; finish relaxation first.`, warn ? _C.err : _C.warn); return }
    _setReady(`${warn}Ready · ${summary} · job ${String(job.job_id).slice(0, 8)} — Run field.`, warn ? _C.err : _C.ok)
  }

  async function runField() {
    const spec = getFieldSpec()
    const job = getSelectedJob ? getSelectedJob() : null
    if (!fieldSpecReady(spec) || !job || job.status !== 'completed' || job.parent_job_id) {
      _renderReady(); return false
    }
    if (runBtn) runBtn.disabled = true
    _setReady('Starting field run…', _C.accent)
    const steps = parseInt(stepsInput?.value || '2000000', 10)
    const r = await api.appendOxdnaField(job.job_id, {
      field_pN: spec.field_pN, dir: spec.dir, anchors: spec.anchors, steps,
    }).catch(() => null)
    // Success = a child field job was created (its dict carries job_id); the run
    // starts in the background (its status is "queued"/"running", never an `ok`
    // envelope), so check for job_id, not a status string.
    if (r && (r.job_id || r.ok)) {
      showToast('E-field run started', 'ok')
      const childId = String(r.job_id || '').slice(0, 8)
      const nAnch = r.efield?.n_anchored ?? r.n_anchored ?? spec.anchors.length
      _setReady(`Field run started${childId ? ` (${childId})` : ''} · ${nAnch} anchored — see the ⚡ sub-item above.`, _C.warn)
      onRan?.()
      return true
    }
    _setReady(api.lastErrorMessage?.() || 'Failed to start field run (see console).', _C.err)
    if (runBtn) runBtn.disabled = false
    return false
  }

  function getFieldSpec() {
    return buildFieldSpec({ pN: _pN, dir: _currentDir(), anchors: _anchors })
  }
  function getAnchors() { return _anchors.slice() }

  // ── Inputs ───────────────────────────────────────────────────────────────
  magInput?.addEventListener('input', () => { _pN = Math.max(0, parseFloat(magInput.value || '0') || 0); _pushToGizmo(); _renderReady() })
  for (const d of [dirX, dirY, dirZ]) d?.addEventListener('input', () => { _pushToGizmo(); _renderReady() })
  qeffInput?.addEventListener('input', () => { _qEff = parseFloat(qeffInput.value || String(DEFAULT_Q_EFF)) || DEFAULT_Q_EFF; _syncVpm() })

  function _syncVpm() {
    if (vpmInput && document.activeElement !== vpmInput) vpmInput.value = _pN > 0 ? pnToFieldVpm(_pN, _qEff).toPrecision(3) : ''
  }
  vpmApply?.addEventListener('click', () => {
    const e = parseFloat(vpmInput?.value || '0') || 0
    _pN = Math.max(0, fieldVpmToPn(e, _qEff))
    if (magInput) magInput.value = _fmtPn(_pN)
    _pushToGizmo(); _renderReady()
  })
  vpmToggle?.addEventListener('click', () => {
    const o = vpmBody && vpmBody.style.display !== 'none'
    if (vpmBody) vpmBody.style.display = o ? 'none' : ''
    if (vpmArrow) vpmArrow.style.transform = o ? '' : 'rotate(90deg)'
    if (!o) _syncVpm()
  })

  addBtn?.addEventListener('click', addSelectedAnchors)
  clearBtn?.addEventListener('click', () => { _anchors = []; _renderAnchors(); _renderReady() })
  runBtn?.addEventListener('click', runField)
  // Re-evaluate run-eligibility just-in-time (the selected job may have changed in
  // the panel since the last E-field interaction).
  runBtn?.addEventListener('pointerenter', _renderReady)

  // Gizmo drag → update magnitude (length) + direction inputs live.
  gizmo?.setOnChange?.((vec) => {
    _pN = pnForArrowLen(vecLen(vec))
    gizmo.setColor?.(fieldColorHex(_pN))
    _syncInputsFromGizmo(); _syncVpm(); _renderReady()
  })

  // ── Section open/close (mounts the gizmo only while editing) ───────────────
  function _open_() {
    _open = true
    bodyEl.style.display = ''
    if (arrow) arrow.classList.remove('is-collapsed')
    gizmo?.attach?.([0, 0, 0])
    _pushToGizmo()
    _renderAnchors(); _renderReady()
  }
  function _close_() {
    _open = false
    bodyEl.style.display = 'none'
    if (arrow) arrow.classList.add('is-collapsed')
    gizmo?.detach?.()
  }
  toggle.addEventListener('click', () => { _open ? _close_() : _open_() })
  _close_()   // start collapsed

  // Drop the gizmo when leaving the Dynamics tab so it never lingers in other tabs.
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.activeTab !== 'dynamics' && _open) _close_()
  })

  // Re-evaluate the Run button whenever the panel's selected job (or its status)
  // changes — so clicking a completed relaxed job immediately enables "Run field"
  // (and a relaxation completing while selected enables it without a re-click).
  window.addEventListener('nadoc:oxdna-job-selected', _renderReady)

  function refresh() { _renderAnchors(); _renderReady() }

  return { getFieldSpec, getAnchors, addSelectedAnchors, runField, refresh }
}
