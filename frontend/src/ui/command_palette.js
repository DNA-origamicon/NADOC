/**
 * Command palette — Ctrl+K fuzzy-search command launcher.
 *
 * Actions: add helix, add strand, set scaffold, delete selected, load file, save file.
 * Arrow keys navigate; Enter selects; Escape closes.
 *
 * Staple crossovers are placed via the always-on proximity markers in
 * crossover_markers.js — no explicit command palette action is needed.
 */

import * as api from '../api/client.js'
import { store } from '../state/store.js'
import { BDNA_RISE_PER_BP } from '../constants.js'

// ── Action registry ───────────────────────────────────────────────────────────

function _buildActions(onAddHelixConfirm, onDeleteSelected) {
  return [
    {
      label:    'Add Helix',
      keywords: ['add', 'helix', 'new', 'create'],
      handler:  () => _openAddHelixForm(onAddHelixConfirm),
    },
    {
      label:    'Set As Scaffold',
      keywords: ['scaffold', 'set', 'mark'],
      handler:  () => _setSelectedAsScaffold(),
    },
    {
      label:    'Delete Selected',
      keywords: ['delete', 'remove', 'destroy'],
      handler:  () => { close(); onDeleteSelected() },
    },
    {
      label:    'Load File',
      keywords: ['load', 'open', 'file', 'import'],
      handler:  () => _openFileForm('load'),
    },
    {
      label:    'Save File',
      keywords: ['save', 'export', 'file'],
      handler:  () => _openFileForm('save'),
    },
    {
      label:    'New Design',
      keywords: ['new', 'design', 'create', 'reset'],
      handler:  () => _openNewDesignForm(),
    },
  ]
}

// ── Fuzzy match ───────────────────────────────────────────────────────────────

function _matches(query, action) {
  if (!query) return true
  const q = query.toLowerCase()
  const text = (action.label + ' ' + action.keywords.join(' ')).toLowerCase()
  // Check if every character in the query appears in order (subsequence).
  let i = 0
  for (const ch of text) {
    if (ch === q[i]) i++
    if (i === q.length) return true
  }
  return false
}

// ── DOM helpers ───────────────────────────────────────────────────────────────

let _overlay, _box, _input, _results, _paramForm
let _actions, _filteredActions, _selectedIdx
let _open = false

function _ensureDOM() {
  _overlay = document.getElementById('cmd-palette-overlay')
  _box     = document.getElementById('cmd-palette-box')
  _input   = document.getElementById('cmd-input')
  _results = document.getElementById('cmd-results')
  _paramForm = document.getElementById('cmd-param-form')
}

function _renderResults() {
  _results.innerHTML = ''
  _filteredActions = _actions.filter(a => _matches(_input.value, a))
  _selectedIdx = Math.min(_selectedIdx, _filteredActions.length - 1)
  _selectedIdx = Math.max(0, _selectedIdx)

  _filteredActions.forEach((action, i) => {
    const li = document.createElement('div')
    li.className = 'cmd-result' + (i === _selectedIdx ? ' selected' : '')
    li.textContent = action.label
    li.addEventListener('mousedown', e => { e.preventDefault(); _execute(i) })
    _results.appendChild(li)
  })
}

function _execute(idx) {
  const action = _filteredActions[idx]
  if (!action) return
  action.handler()
}

function open() {
  _ensureDOM()
  _input.value = ''
  _selectedIdx = 0
  _paramForm.innerHTML = ''
  _paramForm.style.display = 'none'
  _renderResults()
  _overlay.style.display = 'flex'
  _input.focus()
  _open = true
}

function close() {
  if (!_open) return
  _overlay.style.display = 'none'
  _open = false
}

// ── Inline parameter forms ────────────────────────────────────────────────────

function _openAddHelixForm(onConfirm) {
  _results.style.display = 'none'
  _paramForm.style.display = 'block'

  const DEFAULT_BP = 42
  const DEFAULT_X  = 0.0
  const DEFAULT_Y  = 0.0
  const DEFAULT_Z  = 0.0

  _paramForm.innerHTML = `
    <div class="param-title">Add Helix</div>
    <div class="param-row">
      <label>Length (bp)</label>
      <input id="pf-bp" type="number" value="${DEFAULT_BP}" min="2" max="1000" step="1">
    </div>
    <div class="param-row">
      <label>Axis start X Y Z (nm)</label>
      <div class="param-xyz">
        <input id="pf-sx" type="number" value="${DEFAULT_X}" step="0.1">
        <input id="pf-sy" type="number" value="${DEFAULT_Y}" step="0.1">
        <input id="pf-sz" type="number" value="${DEFAULT_Z}" step="0.1">
      </div>
    </div>
    <div class="param-row">
      <label>Axis end Z (nm) <span id="pf-end-z-preview" class="dim"></span></label>
      <input id="pf-ez" type="number" value="${(DEFAULT_BP * BDNA_RISE_PER_BP).toFixed(3)}" step="0.001" readonly>
    </div>
    <div class="param-actions">
      <button id="pf-cancel">Cancel</button>
      <button id="pf-confirm" class="primary">Add Helix</button>
    </div>
  `

  const bpInput = _paramForm.querySelector('#pf-bp')
  const ezInput = _paramForm.querySelector('#pf-ez')

  bpInput.addEventListener('input', () => {
    const bp = parseInt(bpInput.value) || 2
    ezInput.value = (parseFloat(_paramForm.querySelector('#pf-sz').value || 0) + bp * BDNA_RISE_PER_BP).toFixed(3)
  })

  _paramForm.querySelector('#pf-sz').addEventListener('input', () => {
    const bp = parseInt(bpInput.value) || 2
    ezInput.value = (parseFloat(_paramForm.querySelector('#pf-sz').value || 0) + bp * BDNA_RISE_PER_BP).toFixed(3)
  })

  _paramForm.querySelector('#pf-cancel').addEventListener('click', close)

  _paramForm.querySelector('#pf-confirm').addEventListener('click', async () => {
    const bp = parseInt(bpInput.value) || 2
    const sx = parseFloat(_paramForm.querySelector('#pf-sx').value) || 0
    const sy = parseFloat(_paramForm.querySelector('#pf-sy').value) || 0
    const sz = parseFloat(_paramForm.querySelector('#pf-sz').value) || 0
    const ez = parseFloat(ezInput.value)
    close()
    await onConfirm({ axisStart: { x: sx, y: sy, z: sz }, axisEnd: { x: sx, y: sy, z: ez }, lengthBp: bp })
  })
}

function _openFileForm(mode) {
  _results.style.display = 'none'
  _paramForm.style.display = 'block'

  const isLoad = mode === 'load'
  _paramForm.innerHTML = `
    <div class="param-title">${isLoad ? 'Load File' : 'Save File'}</div>
    <div class="param-row">
      <label>Path (.nadoc)</label>
      <input id="pf-path" type="text" placeholder="/path/to/design.nadoc" style="width:100%">
    </div>
    <div class="param-actions">
      <button id="pf-cancel">Cancel</button>
      <button id="pf-confirm" class="primary">${isLoad ? 'Load' : 'Save'}</button>
    </div>
  `

  _paramForm.querySelector('#pf-cancel').addEventListener('click', close)
  _paramForm.querySelector('#pf-confirm').addEventListener('click', async () => {
    const path = _paramForm.querySelector('#pf-path').value.trim()
    if (!path) return
    close()
    if (isLoad) await api.loadDesign(path)
    else        await api.saveDesign(path)
  })
}

function _openNewDesignForm() {
  _results.style.display = 'none'
  _paramForm.style.display = 'block'

  _paramForm.innerHTML = `
    <div class="param-title">New Design</div>
    <div class="param-row">
      <label>Name</label>
      <input id="pf-name" type="text" value="Untitled" style="width:100%">
    </div>
    <div class="param-row">
      <label>Lattice</label>
      <select id="pf-lattice">
        <option value="HONEYCOMB">Honeycomb</option>
        <option value="SQUARE">Square</option>
        <option value="FREE">Free</option>
      </select>
    </div>
    <div class="param-actions">
      <button id="pf-cancel">Cancel</button>
      <button id="pf-confirm" class="primary">Create</button>
    </div>
  `

  _paramForm.querySelector('#pf-cancel').addEventListener('click', close)
  _paramForm.querySelector('#pf-confirm').addEventListener('click', async () => {
    const name    = _paramForm.querySelector('#pf-name').value.trim() || 'Untitled'
    const lattice = _paramForm.querySelector('#pf-lattice').value
    close()
    await api.createDesign(name, lattice)
  })
}

async function _setSelectedAsScaffold() {
  const { selectedObject, currentDesign } = store.getState()
  if (!selectedObject) { close(); return }

  const strandId = selectedObject.data?.strand_id
  if (!strandId) { close(); return }

  const strand = currentDesign?.strands?.find(s => s.id === strandId)
  if (!strand) { close(); return }

  close()
  await api.updateStrand(strandId, {
    domains:    strand.domains,
    isScaffold: true,
    sequence:   strand.sequence,
  })
}

// ── Public init ───────────────────────────────────────────────────────────────

export function initCommandPalette({ onAddHelix, onDeleteSelected }) {
  _actions = _buildActions(onAddHelix, onDeleteSelected)
  _filteredActions = _actions
  _selectedIdx = 0

  document.addEventListener('keydown', e => {
    if (e.key === 'k' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      _open ? close() : open()
      return
    }
    if (!_open) return
    if (e.key === 'Escape')     { close(); return }
    if (e.key === 'ArrowDown')  { e.preventDefault(); _selectedIdx = Math.min(_selectedIdx + 1, _filteredActions.length - 1); _renderResults() }
    if (e.key === 'ArrowUp')    { e.preventDefault(); _selectedIdx = Math.max(_selectedIdx - 1, 0); _renderResults() }
    if (e.key === 'Enter')      { e.preventDefault(); _execute(_selectedIdx) }
  })

  _ensureDOM()
  _input?.addEventListener('input', () => { _selectedIdx = 0; _renderResults() })

  // Close on backdrop click
  _overlay?.addEventListener('click', e => {
    if (e.target === _overlay) close()
  })
}
