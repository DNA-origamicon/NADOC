/**
 * Overhangs Manager popup.
 *
 * Lets the user define metadata-only linker records between two overhangs of
 * the currently open Part, plus auto-generated complement strands paired with
 * each overhang. Persisted in design.overhang_connections.
 *
 * Opened from:
 *   - Tools → Overhangs Manager
 *   - Right-click on a strand while 1–2 overhangs are selected
 * Auto-prepopulates lists from the current overhang selection (up to 2).
 */

import * as api from '../api/client.js'
import {
  patchSubDomain,
  recomputeSubDomainAnnotations,
  generateSubDomainRandom,
  splitSubDomain,
  mergeSubDomains,
  patchTmSettings,
  createOverhangBinding,
  patchOverhangBinding,
  deleteOverhangBinding,
  resizeOverhangFreeEnd,
} from '../api/overhang_endpoints.js'
import { setDomainDesignerSelection, setDomainDesignerModalActive } from '../state/store.js'
import { initOverhangPathview }      from './overhang_pathview.js'
import { initDomainDesignerPanel }   from './domain_designer_panel.js'

// ── Debug instrumentation (Phase 3 fix-up) ───────────────────────────────────
// Flip to `false` to silence the Domain Designer console traces. The same
// pattern lives in each Domain Designer module — toggle each one independently
// when narrowing a bug.
const DEBUG = true
const _debug = (...args) => { if (DEBUG) console.debug('[DD-tab]', ...args) }

let _store    = null
let _modal    = null
let _modalContent = null
let _closeBtn = null
let _listA    = null
let _listB    = null
let _genBtn   = null
let _errorEl  = null
let _lengthEl = null
let _tableBody = null

// ── Tab controller state (Phase 3 overhang revamp) ────────────────────────────
const _OHC_TABS = ['linker-generator', 'domain-designer']
const _OHC_TAB_STORAGE = 'nadoc.overhangsManager.activeTab'
let _activeTab = 'linker-generator'
let _ddPathview = null
let _ddPanel    = null
let _ddInited   = false

const _state = {
  selectedA: null,        // overhang id
  selectedB: null,        // overhang id
  attachA:   'free_end',  // 'root' | 'free_end'
  attachB:   'root',
  linkerType: 'ss',       // 'ss' | 'ds'
  lengthUnit: 'bp',       // 'bp' | 'nm'
}

// ── Public API ────────────────────────────────────────────────────────────────

export function initOverhangsManagerPopup({ store }) {
  _store = store

  _modal     = document.getElementById('overhangs-manager-modal')
  _modalContent = document.getElementById('ohc-modal-content')
  _closeBtn  = document.getElementById('ohc-close')
  _listA     = document.getElementById('ohc-list-a')
  _listB     = document.getElementById('ohc-list-b')
  _genBtn    = document.getElementById('ohc-generate')
  _errorEl   = document.getElementById('ohc-error')
  _lengthEl  = document.getElementById('ohc-length')
  _tableBody = document.getElementById('ohc-table-body')
  if (!_modal) return

  _closeBtn.addEventListener('click', close)
  _modal.addEventListener('click', (e) => { if (e.target === _modal) close() })

  // ── Tab strip wiring (Phase 3 overhang revamp) ──────────────────────────
  // Inline closure mirroring the left-sidebar tab pattern at main.js#L8619.
  // DOM contract: `data-tab="id"` buttons + `id="tab-content-{id}"` panes.
  const tabStrip = _modal.querySelector('#ohc-tab-strip')
  if (tabStrip) {
    // Restore last-used tab from localStorage.
    try {
      const saved = localStorage.getItem(_OHC_TAB_STORAGE)
      if (saved && _OHC_TABS.includes(saved)) _activeTab = saved
    } catch { /* ignore */ }

    tabStrip.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.ohc-tab')
      if (!btn) return
      const id = btn.dataset.tab
      if (!id || !_OHC_TABS.includes(id)) return
      _switchTab(id)
    })
  }

  // Toggle groups: clicks switch is-checked among siblings within the same group.
  _modal.querySelectorAll('.ohc-toggle-group').forEach((group) => {
    const name = group.dataset.name
    group.addEventListener('click', (e) => {
      const btn = e.target.closest('.ohc-toggle')
      if (!btn || btn.classList.contains('is-checked')) return
      group.querySelectorAll('.ohc-toggle').forEach(b => b.classList.remove('is-checked'))
      btn.classList.add('is-checked')
      const v = btn.dataset.value
      if (name === 'attach-a')      _state.attachA    = v
      else if (name === 'attach-b') _state.attachB    = v
      else if (name === 'linker-type') _state.linkerType = v
      else if (name === 'length-unit') _state.lengthUnit = v
      _validate()
    })
  })

  _genBtn.addEventListener('click', _onGenerate)
  _lengthEl.addEventListener('input', _validate)
}

/**
 * Open the manager. If `preselect` is given, it's an array of up to 2
 * overhang ids to drop into sides A and B (in order). When omitted, the
 * popup pulls the current overhang selection from the store
 * (`multiSelectedOverhangIds`, then any single selectedObject overhang).
 */
export function open(preselect) {
  if (!_modal) return
  const state = _store?.getState()
  if (!state?.currentDesign) {
    alert('No design loaded.')
    return
  }
  const ids = _resolvePreselect(state, preselect)
  _state.selectedA = ids[0] ?? null
  _state.selectedB = ids[1] ?? null
  _renderLists()
  _renderTable()
  _validate()
  _modal.style.display = 'flex'
  // Apply persisted active tab (default 'linker-generator'). Domain Designer
  // is lazily inited inside `_switchTab` on first activation so its 3D context
  // isn't created until the user clicks the tab.
  _switchTab(_activeTab, { preselect: ids })
}

function _resolvePreselect(state, explicit) {
  const all = state.currentDesign?.overhangs ?? []
  const valid = (id) => id && all.some(o => o.id === id)
  // Caller-supplied ids win.
  if (Array.isArray(explicit) && explicit.length > 0) {
    return explicit.filter(valid).slice(0, 2)
  }
  // Multi-overhang selection (lasso / ctrl+click) — first 2.
  const multi = (state.multiSelectedOverhangIds ?? []).filter(valid).slice(0, 2)
  if (multi.length > 0) return multi
  // Single-selected overhang via domain-mode click.
  const single = state.selectedObject?.data?.overhang_id
  return valid(single) ? [single] : []
}

export function close() {
  if (_modal) _modal.style.display = 'none'
  // Clear the modal-active flag — design_renderer now flushes its single
  // deferred rebuild against the latest design + geometry.
  setDomainDesignerModalActive(false)
  // Tear down the Domain Designer panel + pathview so listeners detach.
  if (_ddInited) {
    try { _ddPanel?.close?.() } catch (err) { _debug('panel close threw', err) }
    try { _ddPathview?.destroy?.() } catch (err) { _debug('pathview destroy threw', err) }
    _ddPanel = _ddPathview = null
    _ddInited = false
  }
}

// ── Tab controller (Phase 3 overhang revamp) ──────────────────────────────────

function _switchTab(id, { preselect } = {}) {
  if (!_OHC_TABS.includes(id)) return
  const oldTab = _activeTab
  _activeTab = id
  try { localStorage.setItem(_OHC_TAB_STORAGE, id) } catch { /* ignore */ }

  // Update button visual state.
  const strip = _modal.querySelector('#ohc-tab-strip')
  if (strip) {
    for (const btn of strip.querySelectorAll('.ohc-tab')) {
      const active = btn.dataset.tab === id
      btn.classList.toggle('active', active)
      // Inline-style swap matches the dark Primer palette in index.html.
      btn.style.background = active ? '#0d1117' : '#161b22'
      btn.style.color      = active ? '#c9d1d9' : '#8b949e'
    }
  }

  // Toggle panes via the `hidden` attribute (DOM contract).
  for (const tabId of _OHC_TABS) {
    const pane = document.getElementById(`tab-content-${tabId}`)
    if (pane) pane.hidden = (tabId !== id)
  }

  // Modal-content width swap.
  const newWidth = (id === 'domain-designer') ? '1000px' : '760px'
  if (_modalContent) _modalContent.style.width = newWidth
  _debug('tab activate', oldTab, '→', id, 'modal width →', newWidth)

  if (id === 'domain-designer') {
    // Set the modal-active flag so design_renderer defers main-scene rebuilds
    // until the user closes the popup (or switches back to Linker Generator).
    setDomainDesignerModalActive(true)
    // Defer panel/pathview init to the next macrotask so the modal visibly
    // switches tabs before the panel render runs.
    setTimeout(() => {
      const t0 = (typeof performance !== 'undefined') ? performance.now() : Date.now()
      _debug('lazy-init start')
      try {
        _ensureDomainDesignerInited()
        _ddPanel?.open?.(preselect)
      } catch (err) {
        _debug('lazy-init threw', err)
        console.error('[DD-tab] lazy-init failed', err)
      }
      const t1 = (typeof performance !== 'undefined') ? performance.now() : Date.now()
      _debug('lazy-init done', (t1 - t0).toFixed(1), 'ms')
    }, 0)
  } else {
    // Clear the flag and flush any deferred rebuild as the user leaves DD.
    setDomainDesignerModalActive(false)
    if (_ddPanel) _ddPanel.close()
  }
}

function _ensureDomainDesignerInited() {
  if (_ddInited) return
  const pathCanvas = document.getElementById('dd-pathview-canvas')
  const pathWrap   = document.getElementById('dd-pathview-wrap')
  const resetBtn   = document.getElementById('dd-pathview-reset')
  if (!pathCanvas) {
    _debug('init aborted — #dd-pathview-canvas missing from DOM')
    return
  }

  const ddApi = {
    patchSubDomain,
    recomputeSubDomainAnnotations,
    generateSubDomainRandom,
    splitSubDomain,
    mergeSubDomains,
    patchTmSettings,
    createOverhangBinding,
    patchOverhangBinding,
    deleteOverhangBinding,
  }

  _ddPathview = initOverhangPathview(pathCanvas, {
    store: _store,
    wrapEl: pathWrap,
    onSelectSubDomain: (sdId, _ovhgId) => {
      // PERSPECTIVE LOCK: only the listing changes the perspective anchor
      // (`selectedOverhangId`). Pathview clicks update ONLY `selectedSubDomainId`
      // so the user can edit the partner overhang's sub-domain without
      // flipping the multi-grid stack. The annotations panel resolves the
      // owning overhang by walking design.overhangs.
      setDomainDesignerSelection({ subDomainId: sdId })
    },
    onSplit: (ovhgId, { sub_domain_id, split_at_offset }) => {
      // ovhgId is the OWNING overhang from the hit-test, NOT necessarily the
      // listing-selected one. Routes the split to the correct overhang.
      if (!ovhgId) return
      _debug('split', ovhgId, sub_domain_id, '@', split_at_offset)
      splitSubDomain(ovhgId, { sub_domain_id, split_at_offset })
    },
    onResizeFreeEnd: (ovhgId, { end, delta_bp }) => {
      if (!ovhgId) return
      _debug('resize-free-end', ovhgId, end, delta_bp)
      resizeOverhangFreeEnd(ovhgId, { end, deltaBp: delta_bp })
        .catch(err => console.warn('[DD-tab] resize failed', err))
    },
    onResizeLinker: (connId, lengthDelta) => {
      // Bridge length resize. Read the current length and PATCH with the
      // delta applied. Backend keeps unit unchanged AND preserves the
      // existing complement-domain bp ranges across the regeneration.
      if (!connId) return
      const conn = _store.getState().currentDesign?.overhang_connections
        ?.find(c => c.id === connId)
      if (!conn) return
      const newLen = Math.max(1, (conn.length_value ?? 0) + lengthDelta)
      _debug('resize-linker', connId, 'lenΔ', lengthDelta, 'newLen', newLen)
      api.patchOverhangConnection(connId, { length_value: newLen })
        .catch(err => console.warn('[DD-tab] linker resize failed', err))
    },
    onResizeBinding: ({ strand_id, helix_id, end, delta_bp }) => {
      // Resize the linker strand's binding-domain 3' end by hitting the
      // generic strand-end-resize endpoint. The backend's persistence in
      // patch_overhang_connection ensures the resized binding survives any
      // subsequent linker bridge resize.
      _debug('resize-binding', strand_id, helix_id, end, delta_bp)
      api.resizeStrandEnds([{ strand_id, helix_id, end, delta_bp }])
        .catch(err => console.warn('[DD-tab] binding resize failed', err))
    },
  })

  if (resetBtn && _ddPathview?.resetView) {
    resetBtn.addEventListener('click', () => {
      _debug('reset view click')
      _ddPathview.resetView()
    })
  }
  _ddPanel = initDomainDesignerPanel(_modalContent, {
    store: _store,
    api: ddApi,
    pathview: _ddPathview,
  })
  _ddInited = true
}

// ── Internal ──────────────────────────────────────────────────────────────────

function _design() {
  return _store?.getState()?.currentDesign
}

function _overhangs() {
  return _design()?.overhangs ?? []
}

function _connections() {
  return _design()?.overhang_connections ?? []
}

/** Parse 5p/3p suffix from id. */
function _endTag(ovhgId) {
  if (ovhgId.endsWith('_5p')) return "5'"
  if (ovhgId.endsWith('_3p')) return "3'"
  return ''
}

function _displayName(ovhg) {
  return ovhg.label || ovhg.id
}

function _renderLists() {
  const overhangs = _overhangs()
  _listA.innerHTML = ''
  _listB.innerHTML = ''

  if (overhangs.length === 0) {
    const empty = '<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No overhangs in this design.</div>'
    _listA.innerHTML = empty
    _listB.innerHTML = empty
    return
  }

  // Sort by label (OH1, OH2, … fall back to id)
  const sorted = [...overhangs].sort((a, b) => _displayName(a).localeCompare(_displayName(b), undefined, { numeric: true }))
  for (const ovhg of sorted) {
    _listA.appendChild(_makeListRow(ovhg, 'A'))
    _listB.appendChild(_makeListRow(ovhg, 'B'))
  }
  _refreshSelectionUI()
}

function _makeListRow(ovhg, side) {
  const row = document.createElement('div')
  row.className = 'ohc-list-row'
  row.dataset.ovhgId = ovhg.id
  row.dataset.side = side

  const nameEl = document.createElement('span')
  nameEl.textContent = _displayName(ovhg)

  const tagEl = document.createElement('span')
  tagEl.className = 'ohc-end-tag'
  tagEl.textContent = _endTag(ovhg.id)

  row.append(nameEl, tagEl)
  row.addEventListener('click', () => _onPickRow(side, ovhg.id))
  return row
}

function _onPickRow(side, ovhgId) {
  const opposite = side === 'A' ? _state.selectedB : _state.selectedA
  if (ovhgId === opposite) return  // can't pick the same overhang on both sides
  if (side === 'A') _state.selectedA = ovhgId
  else              _state.selectedB = ovhgId
  _refreshSelectionUI()
  _validate()
}

function _refreshSelectionUI() {
  _refreshOneList(_listA, _state.selectedA, _state.selectedB)
  _refreshOneList(_listB, _state.selectedB, _state.selectedA)
}

function _refreshOneList(listEl, selectedId, oppositeId) {
  for (const row of listEl.querySelectorAll('.ohc-list-row')) {
    row.classList.toggle('is-selected', row.dataset.ovhgId === selectedId)
    row.classList.toggle('is-disabled', row.dataset.ovhgId === oppositeId && oppositeId != null)
  }
}

function _renderTable() {
  _tableBody.innerHTML = ''
  const conns = _connections()
  if (conns.length === 0) {
    const tr = document.createElement('tr')
    tr.innerHTML = '<td colspan="5" style="padding:10px;color:#6e7681;text-align:center;font-size:11px">No linkers defined.</td>'
    _tableBody.appendChild(tr)
    return
  }

  // Build a label lookup for overhang ids → display names
  const labelById = new Map(_overhangs().map(o => [o.id, _displayName(o)]))

  // Display L1, L2, ... in order
  const sorted = [...conns].sort((a, b) => (a.name ?? '').localeCompare(b.name ?? '', undefined, { numeric: true }))
  for (const c of sorted) {
    const tr = document.createElement('tr')

    // Name — editable
    const nameTd = document.createElement('td')
    _attachEditableText(nameTd, c.name ?? '', async (v) => {
      const newName = v.trim()
      if (!newName || newName === c.name) return
      try { await api.patchOverhangConnection(c.id, { name: newName }); _renderTable() }
      catch (err) { alert(err?.message || String(err)); _renderTable() }
    })

    // Type — read-only (editing type would change validity rules; force delete+recreate)
    const typeTd = document.createElement('td')
    typeTd.textContent = c.linker_type === 'ds' ? 'dsDNA' : 'ssDNA'

    // Length — editable (number + unit)
    const lenTd = document.createElement('td')
    _attachEditableLength(lenTd, c.length_value, c.length_unit, async (newVal, newUnit) => {
      const patch = {}
      if (newVal !== c.length_value)  patch.length_value = newVal
      if (newUnit !== c.length_unit)  patch.length_unit  = newUnit
      if (!Object.keys(patch).length) return
      try { await api.patchOverhangConnection(c.id, patch); _renderTable() }
      catch (err) { alert(err?.message || String(err)); _renderTable() }
    })

    // Overhangs — read-only
    const ohTd = document.createElement('td')
    const aLabel = labelById.get(c.overhang_a_id) ?? c.overhang_a_id
    const bLabel = labelById.get(c.overhang_b_id) ?? c.overhang_b_id
    ohTd.textContent = `${aLabel} (${_attachLabel(c.overhang_a_attach)}) ↔ ${bLabel} (${_attachLabel(c.overhang_b_attach)})`

    // Delete
    const delTd = document.createElement('td')
    const delBtn = document.createElement('button')
    delBtn.className = 'ohc-row-delete'
    delBtn.textContent = '×'
    delBtn.title = 'Delete linker'
    delBtn.addEventListener('click', () => _onDelete(c))
    delTd.appendChild(delBtn)

    tr.append(nameTd, typeTd, lenTd, ohTd, delTd)
    _tableBody.appendChild(tr)
  }
}

function _attachLabel(attach) {
  return attach === 'free_end' ? 'free' : 'root'
}

function _fmtLength(v) {
  return Number.isInteger(v) ? String(v) : String(v)
}

// ── Inline-editing helpers ────────────────────────────────────────────────────

function _attachEditableText(td, value, onCommit) {
  td.textContent = value || '—'
  td.style.cursor = 'text'
  td.title = 'Click to edit'
  td.addEventListener('click', () => _swapToTextInput(td, value, onCommit))
}

function _swapToTextInput(td, value, onCommit) {
  td.textContent = ''
  const input = document.createElement('input')
  input.type = 'text'
  input.value = value
  input.style.cssText = 'background:#0d1117;border:1px solid #1f6feb;border-radius:3px;color:#fff;font:inherit;padding:3px 4px;width:80px;outline:none'
  td.appendChild(input)
  input.focus()
  input.select()
  let done = false
  const finish = (commit) => {
    if (done) return
    done = true
    if (commit) onCommit(input.value)
    else td.textContent = value || '—'
  }
  input.addEventListener('blur',    () => finish(true))
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur() }
    if (e.key === 'Escape') { e.preventDefault(); finish(false) }
  })
}

function _attachEditableLength(td, value, unit, onCommit) {
  td.textContent = `${_fmtLength(value)} ${unit}`
  td.style.cursor = 'text'
  td.title = 'Click to edit length'
  td.addEventListener('click', () => _swapToLengthInputs(td, value, unit, onCommit))
}

function _swapToLengthInputs(td, value, unit, onCommit) {
  td.textContent = ''
  const wrap = document.createElement('span')
  wrap.style.cssText = 'display:inline-flex;gap:3px;align-items:center'
  const numInput = document.createElement('input')
  numInput.type = 'number'; numInput.min = '0'; numInput.step = 'any'
  numInput.value = value
  numInput.style.cssText = 'background:#0d1117;border:1px solid #1f6feb;border-radius:3px;color:#fff;font:inherit;padding:3px 4px;width:54px;outline:none'
  const unitSel = document.createElement('select')
  unitSel.innerHTML = '<option value="bp">bp</option><option value="nm">nm</option>'
  unitSel.value = unit
  unitSel.style.cssText = 'background:#0d1117;border:1px solid #30363d;border-radius:3px;color:#c9d1d9;font:inherit;padding:3px 2px;outline:none'
  wrap.append(numInput, unitSel)
  td.appendChild(wrap)
  numInput.focus(); numInput.select()
  let done = false
  const finish = (commit) => {
    if (done) return
    done = true
    if (commit) {
      const v = parseFloat(numInput.value)
      if (Number.isFinite(v) && v > 0) onCommit(v, unitSel.value)
      else td.textContent = `${_fmtLength(value)} ${unit}`
    } else {
      td.textContent = `${_fmtLength(value)} ${unit}`
    }
  }
  // Commit when focus leaves the wrapper entirely.
  wrap.addEventListener('focusout', (e) => {
    if (!wrap.contains(e.relatedTarget)) finish(true)
  })
  numInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); finish(true) }
    if (e.key === 'Escape') { e.preventDefault(); finish(false) }
  })
}

// ── Validation (mirrors backend _check_linker_compatibility) ──────────────────

function _endOf(ovhgId) {
  if (!ovhgId) return null
  if (ovhgId.endsWith('_5p')) return '5p'
  if (ovhgId.endsWith('_3p')) return '3p'
  return null
}

// "Comp-first" polarity: the linker strand traverses [complement, bridge]
// (vs [bridge, complement]). Holds when the bridge attaches at the
// complement's 3' end. See backend `_comp_first_polarity` for the derivation.
function _compFirst(end, attach) {
  if (end === '5p') return attach === 'free_end'
  if (end === '3p') return attach === 'root'
  return null
}

/** Returns null if combination is valid, else an error message.
 *
 * Watson-Crick polarity test, applied uniformly across all four end-pair
 * categories. ds requires matched polarity (antiparallel bridge halves on
 * the virtual helix); ss requires opposite polarity (single strand
 * 5'→3' through both complements via the bridge).
 */
function _checkRules() {
  const endA = _endOf(_state.selectedA)
  const endB = _endOf(_state.selectedB)
  if (endA == null || endB == null) return null
  const cfA = _compFirst(endA, _state.attachA)
  const cfB = _compFirst(endB, _state.attachB)
  if (cfA == null || cfB == null) return null
  const same_end   = (endA === endB)
  if (_state.linkerType === 'ds' && cfA !== cfB) {
    return same_end
      ? `dsDNA between two ${endA} ends needs matching attach (both root or both free) so the bridge halves pair antiparallel.`
      : `dsDNA between a ${endA} and a ${endB} end needs OPPOSITE attach (one root, one free) so the bridge halves pair antiparallel.`
  }
  if (_state.linkerType === 'ss' && cfA === cfB) {
    return same_end
      ? `ssDNA between two ${endA} ends needs OPPOSITE attach (one root, one free) so the bridge can be one continuous 5'→3' strand.`
      : `ssDNA between a ${endA} and a ${endB} end needs matching attach (both root or both free) so the bridge can be one continuous 5'→3' strand.`
  }
  return null
}

function _validate() {
  // Selection must be complete and length valid before we can even run the rule check.
  const length = parseFloat(_lengthEl.value)
  if (!_state.selectedA || !_state.selectedB) {
    _setError(''); _genBtn.disabled = true; return
  }
  if (!Number.isFinite(length) || length <= 0) {
    _setError('Length must be a positive number.'); _genBtn.disabled = true; return
  }
  const ruleErr = _checkRules()
  if (ruleErr) {
    _setError(ruleErr); _genBtn.disabled = true; return
  }
  _setError(''); _genBtn.disabled = false
}

function _setError(msg) {
  _errorEl.textContent = msg || ''
  _errorEl.style.display = msg ? 'block' : 'none'
}

function _clearError() { _setError('') }

async function _onGenerate() {
  if (_genBtn.disabled) return  // _validate gates the button
  const payload = {
    overhang_a_id:     _state.selectedA,
    overhang_a_attach: _state.attachA,
    overhang_b_id:     _state.selectedB,
    overhang_b_attach: _state.attachB,
    linker_type:       _state.linkerType,
    length_value:      parseFloat(_lengthEl.value),
    length_unit:       _state.lengthUnit,
  }

  _genBtn.disabled = true
  try {
    await api.createOverhangConnection(payload)
    _state.selectedA = null
    _state.selectedB = null
    _refreshSelectionUI()
    _renderTable()
    // window stays open by design
  } catch (err) {
    _setError(err?.message || String(err))
  } finally {
    _validate()  // re-evaluate disabled state
  }
}

async function _onDelete(conn) {
  if (!confirm(`Delete linker "${conn.name ?? conn.id}"?`)) return
  try {
    await api.deleteOverhangConnection(conn.id)
    _renderTable()
    _refreshSelectionUI()  // labels in lists may have changed if overhangs were renamed elsewhere
  } catch (err) {
    _setError(err?.message || String(err))
  }
}
