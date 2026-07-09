/**
 * md_plan_run.js — the "Plan Run" overlay (P4, job-planner track).  It lets the user
 * author a linear MULTI-STAGE chain that runs UNATTENDED: an ordered list of stages, each
 * with its own forces (E-field) + anchors, seeded from a completed root job, queued as one
 * `MdPipeline` via `POST /md/chains` and advanced stage-to-stage by the MD supervisor.
 *
 * ALL list/payload logic lives in the PURE `stage_planner_model.js` (unit-tested); this
 * module is thin DOM glue that renders that model + reuses the SHARED cards:
 *   • the Forces card (`initForcesCard`, U2) edits the ACTIVE stage's E-field, and
 *   • the Anchors card (`initOxdnaAnchorsSetup`) edits the active stage's anchors,
 * both mounted on private `plan-*` ids so no per-engine markup is duplicated.
 *
 * Three-Layer Law: a stage's field/anchors are job-request annotations, never `Design`
 * edits.  The overlay reads the 3D selection only to resolve anchor scopes.
 *
 * Factory: initMdPlanRun({ getSelectedJob, getSelection, getBaseCount }) → { openModal }.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { initForcesCard } from './forces_card.js'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import * as model from './stage_planner_model.js'
import * as api from '../api/client.js'

const _C = { ok: '#5cb85c', warn: '#e0a800', dim: '#8b949e', accent: '#4a9eff', err: '#d9534f' }

function _el(tag, props = {}, children = []) {
  const e = document.createElement(tag)
  for (const [k, v] of Object.entries(props)) {
    if (k === 'style') Object.assign(e.style, v)
    else if (k === 'class') e.className = v
    else if (k === 'text') e.textContent = v
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v)
    else if (v != null) e.setAttribute(k, String(v))
  }
  for (const c of [].concat(children)) if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c)
  return e
}

// Private DOM-id bag for the active-stage Forces card (the `namd` variant, numeric).
const _FIELD_IDS = {
  toggle: 'plan-efield-toggle', arrow: 'plan-efield-arrow', body: 'plan-efield-body',
  enable: 'plan-efield-enable', mag: 'plan-efield-mag',
  dirX: 'plan-efield-dir-x', dirY: 'plan-efield-dir-y', dirZ: 'plan-efield-dir-z',
  ready: 'plan-efield-ready',
}
const _ANCHOR_IDS = {
  toggle: 'plan-anchors-toggle', arrow: 'plan-anchors-arrow', body: 'plan-anchors-body',
  add: 'plan-anchors-add', clear: 'plan-anchors-clear', list: 'plan-anchors-list',
  status: 'plan-anchors-status',
}

export function initMdPlanRun({ getSelectedJob = null, getSelection = null, getBaseCount = null } = {}) {
  let _model = model.newPlan()
  let _activeIndex = -1
  let _chain = null       // last created / polled chain dict
  let _pollTimer = null
  let _busy = false

  // ── Build the modal body (constructed once, kept alive so the shared cards' cached
  //    element refs survive the modal detach/re-attach) ─────────────────────────────
  const rootSel = _el('select', { id: 'plan-root-select', style: { width: '100%' } })
  const stageListEl = _el('div', { id: 'plan-stage-list', style: { display: 'flex', flexDirection: 'column', gap: '4px' } })
  const editorTitle = _el('div', { style: { fontWeight: '600', margin: '4px 0', color: _C.accent } }, 'No stage selected')
  const labelInput = _el('input', { id: 'plan-stage-label', type: 'text', placeholder: 'stage label', style: { width: '100%' } })
  const targetSel = _el('select', { id: 'plan-stage-target' }, [
    _el('option', { value: 'local' }, 'Local'),
    _el('option', { value: 'alpine' }, 'Alpine'),
  ])
  const lengthInput = _el('input', { id: 'plan-stage-length', type: 'number', min: '0', step: '0.5', placeholder: 'ns', style: { width: '80px' } })

  const fieldCard = _fieldCardMarkup()
  const anchorCard = _anchorCardMarkup()
  const editorBox = _el('div', {
    id: 'plan-stage-editor',
    style: { border: `1px solid ${_C.dim}`, borderRadius: '4px', padding: '8px', marginTop: '6px', display: 'none' },
  }, [
    editorTitle,
    _el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', margin: '4px 0' } }, [
      _el('span', { style: { color: _C.dim, fontSize: '12px' } }, 'Engine: NAMD'),
      _el('label', { style: { fontSize: '12px' } }, ['Run on ', targetSel]),
      _el('label', { style: { fontSize: '12px' } }, ['Length ', lengthInput]),
    ]),
    _el('label', { style: { fontSize: '12px', display: 'block', margin: '2px 0' } }, ['Label ', labelInput]),
    anchorCard,
    fieldCard,
  ])

  const statusEl = _el('div', { id: 'plan-chain-status', style: { marginTop: '8px', fontSize: '12px', color: _C.dim } })
  const resumeBtn = createButton({ label: '↻ Resume from failed stage', variant: 'default', size: 'sm', onClick: _resumeChain })
  resumeBtn.style.display = 'none'

  const body = _el('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px', minWidth: '420px' } }, [
    _el('div', {}, [_el('div', { style: { fontSize: '12px', color: _C.dim } }, 'Seed the chain from a completed job:'), rootSel]),
    _el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' } }, [
      _el('strong', {}, 'Stages'),
      _el('div', { style: { display: 'flex', gap: '4px' } }, [
        createButton({ label: '+ Stage', size: 'sm', onClick: () => _addStage() }),
        createButton({ label: '⧉ Field sweep', size: 'sm', title: 'Duplicate the selected stage (rotate its field for a sweep)', onClick: _duplicateActive }),
      ]),
    ]),
    stageListEl,
    editorBox,
    _el('div', { id: 'plan-ready', style: { fontSize: '12px', color: _C.dim } }),
    statusEl,
    resumeBtn,
  ])
  // Keep it in the document (hidden) so the shared cards' getElementById lookups resolve
  // at init time and their cached refs stay valid across modal detach/re-attach.
  body.style.display = 'none'
  document.body.appendChild(body)

  // ── Shared cards on the private plan ids (reuse, no markup duplication) ────────────
  const _forces = initForcesCard({
    engine: 'namd', ids: _FIELD_IDS,
    getBaseCount: () => getBaseCount?.() ?? 0,
    onChange: _syncActiveForces,
  })
  const _anchors = initOxdnaAnchorsSetup({
    getSelection: () => (getSelection ? getSelection() : null),
    ids: _ANCHOR_IDS,
    onChange: _syncActiveAnchors,
  })

  const readyEl = () => document.getElementById('plan-ready')

  // ── Modal shell ───────────────────────────────────────────────────────────────────
  const queueBtn = createButton({ label: 'Queue chain', variant: 'primary', onClick: _queue })
  const closeBtn = createButton({ label: 'Close', onClick: () => ctrl.close() })
  body.style.display = ''   // visible once inside the modal box
  const ctrl = createModal({
    title: 'Plan Run — multi-stage chain', size: 'lg', body,
    actions: [closeBtn, queueBtn],
    onClose: () => { _stopPolling() },
  })

  // ── Model → DOM render ──────────────────────────────────────────────────────────--
  function _renderStages() {
    stageListEl.replaceChildren()
    _model.stages.forEach((st, i) => {
      const active = i === _activeIndex
      const row = _el('div', {
        style: {
          display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 6px',
          borderRadius: '3px', cursor: 'pointer',
          background: active ? 'rgba(74,158,255,0.15)' : 'transparent',
          border: `1px solid ${active ? _C.accent : 'transparent'}`,
        },
        onClick: () => _selectStage(i),
      }, [
        _el('span', { style: { color: _C.dim, fontVariantNumeric: 'tabular-nums' } }, `${i + 1}.`),
        _el('span', { style: { flex: '1' } }, _stageSummary(st)),
        _iconBtn('↑', 'move up', (e) => { e.stopPropagation(); _reorder(i, i - 1) }),
        _iconBtn('↓', 'move down', (e) => { e.stopPropagation(); _reorder(i, i + 1) }),
        _iconBtn('⧉', 'duplicate', (e) => { e.stopPropagation(); _duplicate(i) }),
        _iconBtn('✕', 'remove', (e) => { e.stopPropagation(); _remove(i) }),
      ])
      stageListEl.appendChild(row)
    })
    if (!_model.stages.length) stageListEl.appendChild(_el('div', { style: { color: _C.dim, fontSize: '12px' } }, 'No stages yet — add one.'))
    _renderReady()
  }

  function _stageSummary(st) {
    const bits = [st.label || 'stage']
    if (st.field && Number(st.field.field_pN) > 0 && st.field.enabled !== false) {
      const d = st.field.dir || []
      bits.push(`field ${(+st.field.field_pN).toPrecision(2)}pN [${d.map((x) => +Number(x).toFixed(1)).join(',')}]`)
    }
    if (st.anchors && st.anchors.length) bits.push(`⚓${st.anchors.length}`)
    if (st.run_target === 'alpine') bits.push('alpine')
    return bits.join(' · ')
  }

  function _iconBtn(glyph, title, onClick) {
    return _el('button', {
      title, onClick,
      style: { background: 'none', border: 'none', color: _C.dim, cursor: 'pointer', padding: '0 2px', fontSize: '13px' },
    }, glyph)
  }

  function _renderEditor() {
    const st = _model.stages[_activeIndex]
    if (!st) { editorBox.style.display = 'none'; return }
    editorBox.style.display = ''
    editorTitle.textContent = `Editing stage ${_activeIndex + 1}: ${st.label || '(unlabelled)'}`
    labelInput.value = st.label || ''
    targetSel.value = st.run_target || 'local'
    lengthInput.value = st.length_ns != null ? String(st.length_ns) : ''
    _forces.applyConfig(st.field || null)
    _anchors.applyConfig(st.anchors || [])
  }

  function _renderReady() {
    const r = readyEl()
    if (!r) return
    if (!_model.rootJobId) { r.textContent = 'Pick a root job to seed the chain.'; r.style.color = _C.dim; queueBtn.disabled = true; return }
    if (!_model.stages.length) { r.textContent = 'Add at least one stage.'; r.style.color = _C.dim; queueBtn.disabled = true; return }
    const nField = _model.stages.filter((s) => s.field && Number(s.field.field_pN) > 0 && s.field.enabled !== false).length
    const unanchoredField = _model.stages.some((s) => s.field && Number(s.field.field_pN) > 0 && s.field.enabled !== false && !(s.anchors && s.anchors.length))
    if (unanchoredField) {
      r.textContent = '⚠ a field stage needs ≥1 anchor (add anchors to that stage) — the structure will drift otherwise.'
      r.style.color = _C.warn
    } else {
      r.textContent = `Ready: ${_model.stages.length} stage${_model.stages.length === 1 ? '' : 's'}${nField ? `, ${nField} with a field` : ''}.`
      r.style.color = _C.ok
    }
    queueBtn.disabled = _busy || !model.isQueueable(_model)
  }

  // ── Mutators (all through the pure model) ─────────────────────────────────────────
  function _addStage() {
    _model = model.addStage(_model, { label: `stage ${_model.stages.length + 1}` })
    _activeIndex = _model.stages.length - 1
    _renderStages(); _renderEditor()
  }
  function _duplicate(i) {
    _model = model.duplicateStage(_model, i)
    _activeIndex = i + 1
    _renderStages(); _renderEditor()
  }
  function _duplicateActive() { if (_activeIndex >= 0) _duplicate(_activeIndex) }
  function _remove(i) {
    _model = model.removeStage(_model, i)
    _activeIndex = model.activeIndexAfterRemove(_activeIndex, i, _model.stages.length)
    _renderStages(); _renderEditor()
  }
  function _reorder(from, to) {
    if (to < 0 || to >= _model.stages.length) return
    _model = model.reorderStage(_model, from, to)
    _activeIndex = model.activeIndexAfterReorder(_activeIndex, from, to)
    _renderStages(); _renderEditor()
  }
  function _selectStage(i) { _activeIndex = i; _renderStages(); _renderEditor() }

  function _syncActiveForces() {
    if (_activeIndex < 0) return
    _model = model.setStage(_model, _activeIndex, { field: _forces.getFieldSpec() })
    _renderStages()   // refresh the row summary (keep active selection)
  }
  function _syncActiveAnchors(anchors) {
    if (_activeIndex < 0) return
    _model = model.setStage(_model, _activeIndex, { anchors: anchors && anchors.length ? anchors : null })
    _renderStages()
  }
  labelInput.addEventListener('input', () => { if (_activeIndex >= 0) { _model = model.setStage(_model, _activeIndex, { label: labelInput.value }); _renderStages() } })
  targetSel.addEventListener('change', () => { if (_activeIndex >= 0) _model = model.setStage(_model, _activeIndex, { run_target: targetSel.value }) })
  lengthInput.addEventListener('input', () => {
    if (_activeIndex < 0) return
    const v = parseFloat(lengthInput.value)
    _model = model.setStage(_model, _activeIndex, { length_ns: Number.isFinite(v) && v > 0 ? v : null })
  })
  rootSel.addEventListener('change', () => {
    const [id, engine] = (rootSel.value || '::').split('::')
    _model = model.setRoot(_model, id || null, engine || null)
    _renderReady()
  })

  // ── Queue + live chain status ─────────────────────────────────────────────────────
  async function _queue() {
    if (_busy || !model.isQueueable(_model)) return
    _busy = true; queueBtn.disabled = true
    const payload = model.buildChainPayload(_model)
    const res = await api.createChain(payload)
    _busy = false
    if (!res || !res.chain) {
      statusEl.textContent = `Could not queue the chain: ${api.lastErrorMessage?.() || 'unknown error'}`
      statusEl.style.color = _C.err
      _renderReady()
      return
    }
    _chain = res.chain
    _renderChainStatus()
    _startPolling()
    _renderReady()
  }

  function _renderChainStatus() {
    if (!_chain) { statusEl.textContent = ''; resumeBtn.style.display = 'none'; return }
    const s = model.chainStatusSummary(_chain)
    statusEl.style.color = _chain.status === 'failed' ? _C.err : (_chain.status === 'completed' ? _C.ok : _C.accent)
    const badges = s.stageBadges.map((b) => `${b.index + 1}:${b.label}${b.queuedBehind ? '⏸' : ''}`).join('  ')
    statusEl.textContent = `${s.headline}  [${badges}]`
    resumeBtn.style.display = s.resumable ? '' : 'none'
  }

  async function _resumeChain() {
    if (!_chain?.chain_id) return
    const res = await api.resumeMdChain(_chain.chain_id)
    if (res?.chain) { _chain = res.chain; _renderChainStatus(); _startPolling() }
    else statusEl.textContent = `Resume failed: ${api.lastErrorMessage?.() || 'unknown'}`
  }

  function _startPolling() {
    _stopPolling()
    if (!_chain?.chain_id) return
    _pollTimer = setInterval(async () => {
      const res = await api.getMdChain(_chain.chain_id)
      if (res?.chain) { _chain = res.chain; _renderChainStatus() }
      if (_chain && (_chain.status === 'completed' || _chain.status === 'failed')) _stopPolling()
    }, 4000)
  }
  function _stopPolling() { if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null } }

  // ── Populate the root picker from completed jobs, default = the panel selection ────
  async function _loadRoots() {
    rootSel.replaceChildren(_el('option', { value: '::' }, '— select a completed job —'))
    const res = await api.listMdJobs()
    const jobs = (res?.jobs || res || []).filter((j) => j.status === 'completed')
    for (const j of jobs) {
      rootSel.appendChild(_el('option', { value: `${j.job_id}::namd` }, `${j.name || j.job_id} (NAMD)`))
    }
    const sel = getSelectedJob?.()
    if (sel && sel.status === 'completed') {
      rootSel.value = `${sel.job_id}::namd`
      _model = model.setRoot(_model, sel.job_id, 'namd')
    }
    _renderReady()
  }

  function openModal() {
    // Fresh plan each open (a chain, once queued, lives server-side).
    _model = model.newPlan()
    _activeIndex = -1
    _chain = null
    _stopPolling()
    statusEl.textContent = ''
    resumeBtn.style.display = 'none'
    _renderStages(); _renderEditor()
    ctrl.open()
    _loadRoots()
  }

  return { openModal }
}

// ── static markup helpers (the private card DOM the shared factories bind to) ─────────
function _fieldCardMarkup() {
  const row = (label, input) => _el('div', { style: { display: 'flex', gap: '4px', alignItems: 'center' } }, [_el('span', { style: { fontSize: '12px', width: '90px' } }, label), input])
  return _el('div', { style: { marginTop: '6px', borderTop: '1px solid rgba(139,148,158,0.3)', paddingTop: '4px' } }, [
    _el('div', { id: 'plan-efield-toggle', style: { cursor: 'pointer', fontWeight: '600', fontSize: '13px' } }, [
      _el('span', { id: 'plan-efield-arrow' }, '▸ '), 'Electric field',
    ]),
    _el('div', { id: 'plan-efield-body', style: { display: 'none', paddingLeft: '6px', marginTop: '4px' } }, [
      _el('label', { style: { fontSize: '12px' } }, [_el('input', { id: 'plan-efield-enable', type: 'checkbox' }), ' Apply a uniform E-field to this stage']),
      row('Force (pN/nt)', _el('input', { id: 'plan-efield-mag', type: 'number', min: '0', step: '0.1', style: { width: '80px' } })),
      row('Direction', _el('div', { style: { display: 'flex', gap: '2px' } }, [
        _el('input', { id: 'plan-efield-dir-x', type: 'number', step: '0.1', style: { width: '48px' } }),
        _el('input', { id: 'plan-efield-dir-y', type: 'number', step: '0.1', style: { width: '48px' } }),
        _el('input', { id: 'plan-efield-dir-z', type: 'number', step: '0.1', style: { width: '48px' } }),
      ])),
      _el('div', { id: 'plan-efield-ready', style: { fontSize: '11px', color: '#8b949e', marginTop: '3px' } }),
    ]),
  ])
}
function _anchorCardMarkup() {
  return _el('div', { style: { marginTop: '4px' } }, [
    _el('div', { id: 'plan-anchors-toggle', style: { cursor: 'pointer', fontWeight: '600', fontSize: '13px' } }, [
      _el('span', { id: 'plan-anchors-arrow' }, '▸ '), 'Anchors',
    ]),
    _el('div', { id: 'plan-anchors-body', style: { display: 'none', paddingLeft: '6px', marginTop: '4px' } }, [
      _el('div', { style: { display: 'flex', gap: '4px' } }, [
        _el('button', { id: 'plan-anchors-add' }, 'Anchor selection'),
        _el('button', { id: 'plan-anchors-clear' }, 'Clear'),
      ]),
      _el('div', { id: 'plan-anchors-list', style: { fontSize: '12px', marginTop: '3px' } }),
      _el('div', { id: 'plan-anchors-status', style: { fontSize: '11px', color: '#8b949e' } }),
    ]),
  ])
}
