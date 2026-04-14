/**
 * NADOC Origami Editor — main entry point.
 *
 * Initialises the sliceview (SVG lattice picker) and pathview (Canvas strand
 * editor), fetches the current design, and keeps both views in sync with the
 * backend via BroadcastChannel + direct API polls.
 */

import { editorStore }   from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import {
  fetchDesign, addHelixAtCell, deleteHelix, extendHelixBounds,
  autoScaffold, scaffoldDomainPaint,
  paintStapleDomain, deleteStrand, deleteDomain, nickStrand, ligateStrand, forcedLigation,
  deleteForcedLigation, batchDeleteForcedLigations,
  patchStrand, patchStrandsColor, undoDesign, redoDesign, placeCrossover, moveCrossover, batchMoveCrossovers,
  deleteCrossover, batchDeleteCrossovers, patchCrossoverExtraBases, batchCrossoverExtraBases,
  resizeStrandEnds, insertLoopSkip,
  // menu bar operations
  createDesign, importDesign, importCadnanoDesign, importScadnanoDesign, importPdbDesign,
  exportDesign, exportCadnano, exportSequenceCsv,
  addAutoCrossover, addAutoBreak,
  scaffoldExtrudeNear, scaffoldExtrudeFar, autoScaffoldSeamless,
  assignScaffoldSequence, syncScaffoldSequenceResponse, assignStapleSequences,
  applyAllDeformations,
} from './api.js'
import { showToast, showCursorToast } from '../ui/toast.js'
import { initSliceview }  from './sliceview.js'
import { initPathview }   from './pathview.js'
import { initLigationDebug } from './ligation_debug.js'
import { initStrandsSpreadsheet } from './strands_spreadsheet.js'

// ── DOM refs ────────────────────────────────────────────────────────────────
const loadingOverlay  = document.getElementById('loading-overlay')
const origamiNameEl   = document.getElementById('origami-name')
const statusStrandEl  = document.getElementById('status-strand-info')
const statusRightEl   = document.getElementById('status-right')
const sliceSvg        = document.getElementById('sliceview-svg')
const pathCanvas      = document.getElementById('pathview-canvas')
const pathContainer   = document.getElementById('pathview-container')

// ── File handle (File System Access API) ─────────────────────────────────────
let _fileHandle = null

// ── Progress / toast helpers ─────────────────────────────────────────────────
function _showProgress(msg) { statusRightEl.textContent = msg }
function _hideProgress()    { statusRightEl.textContent = '' }

// ── Menu toggle helpers ───────────────────────────────────────────────────────
function _setMenuToggle(id, on) {
  document.getElementById(id)?.classList.toggle('is-on', on)
}

const _routingIdMap = {
  scaffoldEnds: 'menu-routing-scaffold-ends',
}
function _setRoutingCheck(key, val) {
  const id = _routingIdMap[key]
  if (!id) return
  document.getElementById(id)?.classList.toggle('is-checked', val)
}
function _clearRoutingChecks() {
  for (const id of Object.values(_routingIdMap)) {
    document.getElementById(id)?.classList.remove('is-checked')
  }
}

// ── File helpers ──────────────────────────────────────────────────────────────
async function _getDesignContent() {
  const r = await fetch('/api/design/export')
  if (!r.ok) return null
  return r.text()
}

async function _saveToHandle(handle) {
  const content = await _getDesignContent()
  if (!content) { alert('Failed to read design from server.'); return false }
  try {
    const writable = await handle.createWritable()
    await writable.write(content)
    await writable.close()
  } catch (e) {
    alert(`Save failed: ${e.message}`)
    return false
  }
  return true
}

async function _saveAs() {
  const design = editorStore.getState().design
  if (!design) { alert('No design to save.'); return }
  const suggestedName = `${design.metadata?.name ?? 'design'}.nadoc`
  if ('showSaveFilePicker' in window) {
    let handle
    try {
      handle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: 'NADOC Design', accept: { 'application/json': ['.nadoc'] } }],
      })
    } catch (e) {
      if (e.name === 'AbortError') return
      throw e
    }
    const ok = await _saveToHandle(handle)
    if (ok) _fileHandle = handle
  } else {
    await exportDesign()
  }
}

async function _pickOpenFile() {
  if ('showOpenFilePicker' in window) {
    let handles
    try {
      handles = await window.showOpenFilePicker({
        types: [{ description: 'NADOC Design', accept: { 'application/json': ['.nadoc'] } }],
        multiple: false,
      })
    } catch (e) {
      if (e.name === 'AbortError') return null
      throw e
    }
    const handle = handles[0]
    const file = await handle.getFile()
    return { content: await file.text(), handle }
  }
  return new Promise(resolve => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.nadoc,application/json'
    input.onchange = async () => {
      const file = input.files[0]
      if (!file) { resolve(null); return }
      resolve({ content: await file.text(), handle: null })
    }
    input.oncancel = () => resolve(null)
    input.click()
  })
}

// ── Scaffold sequence lengths ─────────────────────────────────────────────────
const _SCAFFOLD_LENGTHS = { M13mp18: 7249, p7560: 7560, p8064: 8064 }

function _openScaffoldModal() {
  const design = editorStore.getState().design
  if (!design) { alert('No design loaded.'); return }

  // Count scaffold nt (honouring loop/skip deltas)
  const lsMap = new Map()
  for (const helix of design.helices ?? []) {
    for (const ls of helix.loop_skips ?? []) {
      lsMap.set(`${helix.id}:${ls.bp_index}`, ls.delta)
    }
  }
  const scaffold = design.strands?.find(s => s.strand_type === 'scaffold')
  let totalNt = 0
  if (scaffold) {
    for (const d of scaffold.domains) {
      const isFwd = d.direction === 'FORWARD'
      const step  = isFwd ? 1 : -1
      for (let bp = d.start_bp; isFwd ? bp <= d.end_bp : bp >= d.end_bp; bp += step) {
        const delta = lsMap.get(`${d.helix_id}:${bp}`) ?? 0
        if (delta <= -1) continue
        totalNt += delta + 1
      }
    }
  }

  const modal       = document.getElementById('assign-scaffold-modal')
  const lengthEl    = document.getElementById('asc-length-line')
  const warnEl      = document.getElementById('asc-warning')
  const customSeqEl = document.getElementById('asc-custom-seq')
  const charCountEl = document.getElementById('asc-custom-char-count')
  const customErrEl = document.getElementById('asc-custom-error')

  if (customSeqEl) customSeqEl.value = ''
  if (charCountEl) charCountEl.textContent = '0 nt'
  if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }

  lengthEl.textContent = `Scaffold length: ${totalNt} nt`
  modal.style.display = 'flex'

  function _updateWarning() {
    const customRaw = customSeqEl?.value?.replace(/\s/g, '').toUpperCase() ?? ''
    if (customRaw) {
      if (customRaw.length < totalNt) {
        warnEl.textContent = `⚠ Custom sequence (${customRaw.length} nt) is shorter than scaffold (${totalNt} nt). `
          + `${totalNt - customRaw.length} bases will be assigned 'N'.`
        warnEl.style.display = 'block'
      } else {
        warnEl.style.display = 'none'
      }
      return
    }
    const sel    = modal.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
    const seqLen = _SCAFFOLD_LENGTHS[sel] ?? 0
    if (totalNt > seqLen) {
      warnEl.textContent = `⚠ Scaffold (${totalNt} nt) exceeds ${sel} (${seqLen} nt). `
        + `${totalNt - seqLen} bases will be assigned 'N'.`
      warnEl.style.display = 'block'
    } else {
      warnEl.style.display = 'none'
    }
  }
  _updateWarning()
  modal.querySelectorAll('input[name="asc-scaffold"]').forEach(r => r.addEventListener('change', _updateWarning))

  if (customSeqEl) {
    customSeqEl.addEventListener('input', () => {
      const raw = customSeqEl.value.replace(/\s/g, '').toUpperCase()
      if (charCountEl) charCountEl.textContent = `${raw.length} nt`
      const bad = [...new Set(raw.replace(/[ATGCN]/g, ''))]
      if (bad.length > 0) {
        if (customErrEl) { customErrEl.textContent = `Invalid: ${bad.join(', ')}`; customErrEl.style.display = 'inline' }
      } else {
        if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }
      }
      _updateWarning()
    })
  }
}

// ── Slice/path panel resize ──────────────────────────────────────────────────
const resizeHandle = document.getElementById('resize-handle')
const slicePanel   = document.getElementById('sliceview-panel')

let _resizing = false, _resizeStartX = 0, _resizeStartW = 0

resizeHandle.addEventListener('pointerdown', (e) => {
  _resizing    = true
  _resizeStartX = e.clientX
  _resizeStartW = slicePanel.offsetWidth
  resizeHandle.classList.add('dragging')
  resizeHandle.setPointerCapture(e.pointerId)
  e.preventDefault()
})
resizeHandle.addEventListener('pointermove', (e) => {
  if (!_resizing) return
  const w = Math.max(80, Math.min(600, _resizeStartW + (e.clientX - _resizeStartX)))
  slicePanel.style.width = `${w}px`
})
resizeHandle.addEventListener('pointerup', () => {
  if (!_resizing) return
  _resizing = false
  resizeHandle.classList.remove('dragging')
})

// ── Tool buttons ────────────────────────────────────────────────────────────
const toolBtns = {
  select: document.getElementById('tool-select'),
  pencil: document.getElementById('tool-pencil'),
  nick:   document.getElementById('tool-nick'),
  paint:  document.getElementById('tool-paint'),
  skip:   document.getElementById('tool-skip'),
  loop:   document.getElementById('tool-loop'),
}
for (const [tool, btn] of Object.entries(toolBtns)) {
  btn.addEventListener('click', () => {
    editorStore.setState({ selectedTool: tool })
  })
}

// ── Paint palette ────────────────────────────────────────────────────────────
// caDNAno2 canonical solid colours.
const CADNANO_PALETTE = [
  '#cc0000', '#f74308', '#f7931e', '#aaaa00',
  '#57bb00', '#007200', '#03b6a2', '#1700de',
  '#7300de', '#b8056c', '#333333', '#888888',
]

/** Returns the currently active paint colour (custom overrides palette). */
function _getActivePaintColor() {
  const s = editorStore.getState()
  return s.paintCustomColor ?? CADNANO_PALETTE[s.paintColorIdx]
}

const paintPaletteEl = document.getElementById('paint-palette')
CADNANO_PALETTE.forEach((color, idx) => {
  const swatch = document.createElement('button')
  swatch.className = 'paint-swatch'
  swatch.style.background = color
  swatch.title = color
  swatch.addEventListener('click', () => {
    editorStore.setState({ paintColorIdx: idx, paintCustomColor: null })
  })
  paintPaletteEl.appendChild(swatch)
})

// ── Custom colour row ─────────────────────────────────────────────────────────
const _customRow = document.createElement('div')
_customRow.className = 'paint-custom-row'

const _customNativePicker = document.createElement('input')
_customNativePicker.type  = 'color'
_customNativePicker.id    = 'paint-native-picker'
_customNativePicker.value = CADNANO_PALETTE[0]
_customNativePicker.title = 'Pick a custom colour'

const _customTextInput = document.createElement('input')
_customTextInput.type        = 'text'
_customTextInput.id          = 'paint-custom-text'
_customTextInput.placeholder = '#rrggbb or r,g,b'
_customTextInput.spellcheck  = false
_customTextInput.maxLength   = 20

_customRow.appendChild(_customNativePicker)
_customRow.appendChild(_customTextInput)
paintPaletteEl.appendChild(_customRow)

/** Parse a user-typed colour string — hex or rgb — to '#rrggbb', or null. */
function _parseCustomColor(str) {
  str = str.trim()
  if (/^#?[0-9a-f]{6}$/i.test(str))
    return str.startsWith('#') ? str.toLowerCase() : '#' + str.toLowerCase()
  const m = str.match(/^(?:rgb\s*\()?\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)?$/)
  if (m) {
    const [r, g, b] = [+m[1], +m[2], +m[3]]
    if (r <= 255 && g <= 255 && b <= 255)
      return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')
  }
  return null
}

_customNativePicker.addEventListener('input', () => {
  const hex = _customNativePicker.value
  _customTextInput.value = hex
  editorStore.setState({ paintCustomColor: hex })
})

_customTextInput.addEventListener('input', () => {
  const hex = _parseCustomColor(_customTextInput.value)
  if (hex) {
    _customNativePicker.value = hex
    editorStore.setState({ paintCustomColor: hex })
  }
})
_customTextInput.addEventListener('keydown', e => e.stopPropagation())

function _syncPaletteSwatches(idx, customColor) {
  paintPaletteEl.querySelectorAll('.paint-swatch').forEach((el, i) => {
    el.classList.toggle('active', !customColor && i === idx)
  })
  _customRow.classList.toggle('active', !!customColor)
  if (customColor) _customNativePicker.value = customColor
}
// Seed initial active swatch
_syncPaletteSwatches(0, null)

const colorPickerEl = document.getElementById('strand-color-picker')
let _colorPickerStrandId = null

colorPickerEl.addEventListener('input', async () => {
  if (_colorPickerStrandId) {
    await patchStrand(_colorPickerStrandId, { color: colorPickerEl.value })
  }
})

document.getElementById('btn-autoscaffold').addEventListener('click', async () => {
  await autoScaffold()
})

// ── Selectable filter strip ──────────────────────────────────────────────────
const selectFilterEl = document.getElementById('select-filter')
const sfBtns = selectFilterEl.querySelectorAll('.sf-btn')
const _tabCycleKeys = [...selectFilterEl.querySelectorAll('.sf-btn[data-tab-cycle]')].map(b => b.dataset.key)

/** Build a selectFilter patch that activates a single tab-cycle key,
 *  or all of them when the key is 'strand'. */
function _selectFilterFor(key) {
  const patch = {}
  for (const k of _tabCycleKeys) patch[k] = (key === 'strand') ? true : (k === key)
  return patch
}

sfBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.key
    const cur = editorStore.getState().selectFilter
    if (btn.hasAttribute('data-tab-cycle')) {
      editorStore.setState({ selectFilter: { ...cur, ..._selectFilterFor(key) } })
    } else {
      // skip / loop — simple toggle, not part of exclusive cycle
      editorStore.setState({ selectFilter: { ...cur, [key]: !cur[key] } })
    }
  })
})

function _syncFilterButtons(filter) {
  sfBtns.forEach(btn => {
    btn.classList.toggle('active', !!filter[btn.dataset.key])
  })
}

// ── View tool buttons ───────────────────────────────────────────────────────
const viewToolsEl = document.getElementById('view-tools')
const vtBtns = viewToolsEl.querySelectorAll('.vt-btn')
vtBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.vt
    const cur = editorStore.getState().viewTools
    editorStore.setState({ viewTools: { ...cur, [key]: !cur[key] } })
  })
})

function _syncViewToolButtons(viewTools) {
  vtBtns.forEach(btn => {
    btn.classList.toggle('active', !!viewTools[btn.dataset.vt])
  })
}

// Native-orientation toggle — default ON (cadnano2 convention).
const nativeOrientBtn = document.getElementById('btn-native-orientation')
let _nativeOrient = true
nativeOrientBtn.classList.toggle('native-off', !_nativeOrient)
nativeOrientBtn.addEventListener('click', () => {
  _nativeOrient = !_nativeOrient
  nativeOrientBtn.classList.toggle('native-off', !_nativeOrient)
  nativeOrientBtn.title = _nativeOrient
    ? 'cadnano native orientation ON — row 0 at top, matches cadnano2 SVG convention'
    : 'cadnano native orientation OFF — row 0 at bottom, matches 3D viewport (Y-up)'
  sliceview.setNativeOrientation(_nativeOrient)
  pathview.setNativeOrientation(_nativeOrient)
})

document.getElementById('btn-sidebar-undo')?.addEventListener('click', () => undoDesign())
document.getElementById('btn-sidebar-redo')?.addEventListener('click', () => redoDesign())

const open3dBtn = document.getElementById('open-3d-btn')

open3dBtn.addEventListener('click', () => {
  if (window.opener && !window.opener.closed) {
    window.opener.focus()
  } else {
    window.open('/', '_blank')
  }
})

// Poll opener state every 2 s; update button + status bar non-intrusively.
let _isHovering = false
function _update3dConnectionStatus() {
  const connected = window.opener && !window.opener.closed
  open3dBtn.textContent = connected ? '↗ 3D' : '⊕ 3D'
  open3dBtn.title       = connected ? 'Focus 3D window' : '3D view disconnected — click to open new window'
  open3dBtn.style.color = connected ? '' : '#f5a623'
  if (!_isHovering) {
    statusRightEl.textContent = connected ? '' : '3D view disconnected'
  }
}
_update3dConnectionStatus()
setInterval(_update3dConnectionStatus, 2000)

// ── Menu bar — File ──────────────────────────────────────────────────────────
document.getElementById('menu-file-new')?.addEventListener('click', () => {
  const modal   = document.getElementById('new-design-modal')
  if (!modal) { createDesign('Untitled'); return }
  const hasDesign = !!(editorStore.getState().design?.helices?.length)
  const warn = document.getElementById('new-design-unsaved-warn')
  if (warn) warn.style.display = hasDesign ? 'block' : 'none'
  const nameInput = document.getElementById('new-design-name')
  if (nameInput) nameInput.value = 'Untitled'
  modal.style.display = 'flex'
  setTimeout(() => nameInput?.select(), 50)
})
document.getElementById('new-design-cancel')?.addEventListener('click', () => {
  document.getElementById('new-design-modal').style.display = 'none'
})
document.getElementById('new-design-modal')?.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('new-design-modal').style.display = 'none'
  if (e.key === 'Enter')  document.getElementById('new-design-create')?.click()
})
document.getElementById('new-design-create')?.addEventListener('click', async () => {
  const modal   = document.getElementById('new-design-modal')
  const checked = modal.querySelector('input[name="new-lattice-type"]:checked')
  const lattice = checked?.value ?? 'HONEYCOMB'
  const name    = document.getElementById('new-design-name')?.value.trim() || 'Untitled'
  modal.style.display = 'none'
  _fileHandle = null
  await createDesign(name, lattice)
})

document.getElementById('menu-file-open')?.addEventListener('click', async () => {
  const picked = await _pickOpenFile()
  if (!picked) return
  const result = await importDesign(picked.content)
  if (!result) {
    alert('Failed to open design: ' + (editorStore.getState().lastError?.message ?? 'Unknown error'))
    return
  }
  _fileHandle = picked.handle
})

document.getElementById('menu-file-save')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { alert('No design to save.'); return }
  if (_fileHandle) { await _saveToHandle(_fileHandle) } else { await _saveAs() }
})
document.getElementById('menu-file-save-as')?.addEventListener('click', _saveAs)

// Paste Script
;(() => {
  const overlay    = document.getElementById('paste-script-overlay')
  const input      = document.getElementById('paste-script-input')
  const errorEl    = document.getElementById('paste-script-error')
  const runBtn     = document.getElementById('paste-script-run')
  const cancelBtn  = document.getElementById('paste-script-cancel')

  function _open()  { if (errorEl) errorEl.textContent = ''; overlay?.classList.add('visible'); input?.focus() }
  function _close() { overlay?.classList.remove('visible') }

  document.getElementById('menu-file-paste-script')?.addEventListener('click', _open)
  cancelBtn?.addEventListener('click', _close)
  overlay?.addEventListener('click', e => { if (e.target === overlay) _close() })
  input?.addEventListener('keydown', e => { if (e.key === 'Escape') _close() })

  runBtn?.addEventListener('click', async () => {
    if (errorEl) errorEl.textContent = ''
    let script
    try { script = JSON.parse(input?.value ?? '') }
    catch (e) { if (errorEl) errorEl.textContent = `JSON parse error: ${e.message}`; return }
    if (!Array.isArray(script?.steps)) {
      if (errorEl) errorEl.textContent = 'Script must have a "steps" array.'
      return
    }
    _close()
    alert('Paste Script is not available in the Origami Editor. Open the 3D view to run scripts.')
  })
})()

document.getElementById('menu-file-import-cadnano')?.addEventListener('click', () => {
  const input = document.createElement('input')
  input.type = 'file'; input.accept = '.json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    const content = await file.text()
    const result  = await importCadnanoDesign(content)
    if (!result) {
      alert('Failed to import caDNAno file: ' + (editorStore.getState().lastError?.message ?? 'Unknown error'))
      return
    }
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
    showToast('Note: caDNAno designs appear upside down due to the original caDNAno coordinate convention.', 8000)
  }
  input.click()
})

document.getElementById('menu-file-import-scadnano')?.addEventListener('click', () => {
  const input = document.createElement('input')
  input.type = 'file'; input.accept = '.sc'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    const content = await file.text()
    const result  = await importScadnanoDesign(content)
    if (!result) {
      alert('Failed to import scadnano file: ' + (editorStore.getState().lastError?.message ?? 'Unknown error'))
      return
    }
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
  }
  input.click()
})

document.getElementById('menu-file-import-pdb')?.addEventListener('click', () => {
  const input = document.createElement('input')
  input.type = 'file'; input.accept = '.pdb'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    const content = await file.text()
    const merge = !!editorStore.getState().design
    const result = await importPdbDesign(content, merge)
    if (!result) {
      alert('Failed to import PDB file: ' + (editorStore.getState().lastError?.message ?? 'Unknown error'))
      return
    }
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
  }
  input.click()
})

document.getElementById('menu-file-export-seq-csv')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { alert('No design loaded.'); return }
  const ok = await exportSequenceCsv()
  if (!ok) alert('Export failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'))
})
document.getElementById('menu-file-export-cadnano')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { alert('No design loaded.'); return }
  const ok = await exportCadnano()
  if (!ok) alert('Export failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'))
})
document.getElementById('menu-file-export-pdb')?.addEventListener('click', () => {
  if (!editorStore.getState().design) { alert('No design loaded.'); return }
  const a = document.createElement('a'); a.href = '/api/design/export/pdb'; a.download = ''; a.click()
})
document.getElementById('menu-file-export-psf')?.addEventListener('click', () => {
  if (!editorStore.getState().design) { alert('No design loaded.'); return }
  const a = document.createElement('a'); a.href = '/api/design/export/psf'; a.download = ''; a.click()
})
document.getElementById('menu-file-export-namd-complete')?.addEventListener('click', () => {
  if (!editorStore.getState().design) { alert('No design loaded.'); return }
  const a = document.createElement('a'); a.href = '/api/design/export/namd-complete'; a.download = ''; a.click()
})

// ── Menu bar — Edit ───────────────────────────────────────────────────────────
document.getElementById('menu-edit-undo')?.addEventListener('click', () => undoDesign())
document.getElementById('menu-edit-redo')?.addEventListener('click', () => redoDesign())

// ── Menu bar — Routing ────────────────────────────────────────────────────────

// Autoscaffold — seamed / seamless picker
;(() => {
  const modal = document.getElementById('autoscaffold-modal')
  const btnRun = document.getElementById('as-run')
  const btnCancel = document.getElementById('as-cancel')

  async function _runAutoscaffold() {
    if (!editorStore.getState().design) { alert('No design loaded.'); return }
    const seamless = modal.querySelector('input[name="as-mode"]:checked')?.value === 'seamless'
    modal.classList.remove('visible')
    if (seamless) {
      _showProgress('Seamless Scaffold — routing…')
      const ok = await autoScaffoldSeamless()
      _hideProgress()
      if (!ok) { alert('Seamless scaffold failed: ' + (editorStore.getState().lastError?.message ?? 'unknown')) }
      else { _setRoutingCheck('scaffoldEnds', true) }
    } else {
      _showProgress('Autoscaffold — routing…')
      const ok = await autoScaffold()
      _hideProgress()
      if (!ok) { alert('Autoscaffold failed: ' + (editorStore.getState().lastError?.message ?? 'unknown')) }
      else { _setRoutingCheck('scaffoldEnds', true) }
    }
  }

  document.getElementById('menu-routing-scaffold-ends')?.addEventListener('click', () => {
    if (!editorStore.getState().design) { alert('No design loaded.'); return }
    modal.classList.add('visible')
  })
  btnRun?.addEventListener('click', _runAutoscaffold)
  btnCancel?.addEventListener('click', () => modal.classList.remove('visible'))
  modal?.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('visible') })
})()

document.getElementById('menu-routing-auto-crossover')?.addEventListener('click', async () => {
  if (!editorStore.getState().design?.helices?.length) { alert('No design loaded.'); return }
  const result = await addAutoCrossover()
  if (!result) alert('Auto Crossover failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'))
  else showToast('Auto crossovers placed.')
})

;(() => {
  const modal = document.getElementById('autobreak-modal')
  const runBtn = document.getElementById('ab-run')
  const cancelBtn = document.getElementById('ab-cancel')

  document.getElementById('menu-routing-autobreak')?.addEventListener('click', () => {
    if (!editorStore.getState().design?.helices?.length) { alert('No design loaded.'); return }
    modal.classList.add('visible')
  })

  async function _runAutoBreak() {
    modal.classList.remove('visible')
    const algo = modal.querySelector('input[name="ab-algo"]:checked')?.value || 'current'
    // Show progress; animate for advanced algorithm
    _showProgress('Autobreak', algo === 'advanced' ? 'Running advanced optimizer…' : 'Running nick planner…')
    let _anim = null
    if (algo === 'advanced') {
      const fill = document.getElementById('op-progress-fill')
      let pct = 0
      _anim = setInterval(() => { pct = (pct + 8) % 88; if (fill) fill.style.width = pct + '%' }, 350)
    }
    const result = await addAutoBreak({ algorithm: algo })
    if (_anim) clearInterval(_anim)
    _hideProgress()
    if (!result) alert('Autobreak failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'))
    else showToast('Autobreak complete.')
  }

  runBtn?.addEventListener('click', _runAutoBreak)
  cancelBtn?.addEventListener('click', () => modal.classList.remove('visible'))
  modal?.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('visible') })
})()

document.getElementById('menu-seq-update-routing')?.addEventListener('click', async () => {
  const design = editorStore.getState().design
  if (!design) { alert('No design loaded.'); return }
  const hasCrossovers = design.strands?.some(s =>
    s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
  )
  if (!hasCrossovers) { alert('Place crossovers first (Auto Crossover) before updating routing.'); return }
  _showProgress('Updating routing…')
  const result = await applyAllDeformations()
  _hideProgress()
  if (!result) alert('Update Routing failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'))
  else showToast('Routing updated.')
})

// Enable Update Routing when crossovers are present
editorStore.subscribe((state, prev) => {
  if (state.design === prev.design) return
  const btn = document.getElementById('menu-seq-update-routing')
  if (!btn) return
  const hasCrossovers = state.design?.strands?.some(s =>
    s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
  ) ?? false
  btn.disabled = !hasCrossovers
})

// ── Menu bar — Sequencing ─────────────────────────────────────────────────────
document.getElementById('menu-seq-assign-scaffold')?.addEventListener('click', _openScaffoldModal)

document.getElementById('asc-cancel')?.addEventListener('click', () => {
  document.getElementById('assign-scaffold-modal').style.display = 'none'
})
document.getElementById('assign-scaffold-modal')?.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('assign-scaffold-modal').style.display = 'none'
  if (e.key === 'Enter')  document.getElementById('asc-apply')?.click()
})
document.getElementById('asc-apply')?.addEventListener('click', async () => {
  const modal        = document.getElementById('assign-scaffold-modal')
  const scaffoldName = modal.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
  const customRaw    = (document.getElementById('asc-custom-seq')?.value ?? '').replace(/\s/g, '').toUpperCase()
  const customErrEl  = document.getElementById('asc-custom-error')
  if (customRaw && customErrEl?.textContent) return
  modal.style.display = 'none'
  const label = customRaw ? `custom (${customRaw.length} nt)` : scaffoldName
  _showProgress(`Assigning ${label} sequence…`)
  const json = await assignScaffoldSequence(scaffoldName, { customSequence: customRaw || null })
  _hideProgress()
  if (!json) { alert('Assign scaffold sequence failed: ' + (editorStore.getState().lastError?.message ?? 'unknown')); return }
  await syncScaffoldSequenceResponse(json)
  const padMsg = json.padded_nt > 0 ? ` (${json.padded_nt} nt padded with N)` : ''
  showToast(`${label} sequence assigned.${padMsg}`)
})

document.getElementById('menu-seq-assign-staples')?.addEventListener('click', async () => {
  const design = editorStore.getState().design
  if (!design) { alert('No design loaded.'); return }
  const scaffold = design.strands?.find(s => s.strand_type === 'scaffold')
  if (!scaffold?.sequence) { alert('Scaffold has no sequence. Run "Assign Scaffold Sequence" first.'); return }
  _showProgress('Deriving complementary staple sequences…')
  const ok = await assignStapleSequences()
  _hideProgress()
  if (!ok) alert('Assign staple sequences failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'))
})

// ── Menu bar — Help ───────────────────────────────────────────────────────────
const _helpModal = document.getElementById('help-modal')
document.getElementById('menu-help-hotkeys')?.addEventListener('click', () => _helpModal?.classList.add('visible'))
document.getElementById('help-modal-close')?.addEventListener('click', () => _helpModal?.classList.remove('visible'))
_helpModal?.addEventListener('click', e => { if (e.target === _helpModal) _helpModal.classList.remove('visible') })

// ── Track last mouse position for cursor-toasts ─────────────────────────────
let _lastMouseX = 0, _lastMouseY = 0
window.addEventListener('mousemove', (e) => { _lastMouseX = e.clientX; _lastMouseY = e.clientY }, { passive: true })

const _toolDisplayNames = { select: 'Select', pencil: 'Pencil', nick: 'Nick', paint: 'Paint' }

// ── Keyboard shortcuts
window.addEventListener('keydown', (e) => {
  const ctrl = e.ctrlKey || e.metaKey

  // Undo / Redo — intercept before any INPUT/TEXTAREA check so browser undo
  // (Ctrl+Z on a text field) is not accidentally swallowed outside inputs.
  if (ctrl && e.key === 'z' && !e.shiftKey) {
    if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
      e.preventDefault()
      undoDesign()
    }
    return
  }
  if (ctrl && (e.key === 'y' || (e.key === 'z' && e.shiftKey) || e.key === 'Z')) {
    if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
      e.preventDefault()
      redoDesign()
    }
    return
  }

  // Ctrl+O — Open
  if (ctrl && e.key === 'o') {
    e.preventDefault()
    document.getElementById('menu-file-open')?.click()
    return
  }
  // Ctrl+S / Ctrl+Shift+S — Save / Save As
  if (ctrl && e.key === 's' && !e.shiftKey) {
    e.preventDefault()
    document.getElementById('menu-file-save')?.click()
    return
  }
  if (ctrl && e.key === 'S' && e.shiftKey) {
    e.preventDefault()
    document.getElementById('menu-file-save-as')?.click()
    return
  }

  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  if (ctrl) return   // don't intercept other Ctrl combos as tool keys

  // "T" — cycle through select → pencil → nick → paint
  if (e.key === 't' || e.key === 'T') {
    const _tCycle = ['select', 'pencil', 'nick', 'paint']
    const cur = editorStore.getState().selectedTool
    const idx = _tCycle.indexOf(cur)
    const next = _tCycle[(idx + 1) % _tCycle.length]
    editorStore.setState({ selectedTool: next })
    showCursorToast(_toolDisplayNames[next] ?? next, _lastMouseX, _lastMouseY)
  }

  // Tab — cycle through selectable filter items (strand, line, ends, xover only)
  // "strand" turns all on; every other key is exclusive (only that one active).
  if (e.key === 'Tab') {
    e.preventDefault()
    if (_tabCycleKeys.length) {
      const cur = editorStore.getState().selectFilter
      // Find which tab-cycle key is currently the "selected" one.
      // If strand (all-on), it's index 0. Otherwise find the single active key.
      let activeIdx = cur.strand ? 0 : _tabCycleKeys.findIndex(k => cur[k])
      if (activeIdx < 0) activeIdx = 0
      const nextKey = _tabCycleKeys[(activeIdx + 1) % _tabCycleKeys.length]
      editorStore.setState({ selectFilter: { ...cur, ..._selectFilterFor(nextKey) } })
    }
  }

  // Routing / sequencing number shortcuts
  if (e.key === '1') document.getElementById('menu-routing-scaffold-ends')?.click()
  if (e.key === '2') document.getElementById('menu-routing-auto-crossover')?.click()
  if (e.key === '3') { const b = document.getElementById('menu-routing-autobreak'); if (b && !b.disabled) b.click() }
  if (e.key === '4') { const b = document.getElementById('menu-seq-update-routing'); if (b && !b.disabled) b.click() }
  if (e.key === '5') document.getElementById('menu-seq-assign-scaffold')?.click()
  if (e.key === '6') document.getElementById('menu-seq-assign-staples')?.click()

  // Spreadsheet toggle
  if (e.key === 's' || e.key === 'S') { _spreadsheet?.toggle(); return }

  // Help modal
  if (e.key === '?' || e.key === 'F1') _helpModal?.classList.add('visible')
  if (e.key === 'Escape') _helpModal?.classList.remove('visible')
})

// ── Crossover context menu ────────────────────────────────────────────────────

const xoverMenuEl           = document.getElementById('xover-context-menu')
const xoverMenuAddBtn       = document.getElementById('xover-menu-extra-bases-add')
const xoverMenuEditBtn      = document.getElementById('xover-menu-extra-bases-edit')
const xoverMenuDeleteBtn    = document.getElementById('xover-menu-delete')

const _xoverMenu = (() => {
  let _currentXo       = null
  let _currentFl       = null   // forced ligation (when right-clicking an FL arc)
  let _selectedXoKeys  = []

  function hide() {
    xoverMenuEl.classList.remove('visible')
    _currentXo      = null
    _currentFl      = null
    _selectedXoKeys = []
  }

  function show(xo, fl, selectedXoKeys, clientX, clientY) {
    _currentXo      = xo ?? null
    _currentFl      = fl ?? null
    _selectedXoKeys = selectedXoKeys ?? []

    // Toggle add vs. edit button based on whether this crossover already has extra bases
    // (forced ligations don't support extra bases — hide both buttons)
    const hasExtras = !!(xo?.extra_bases)
    xoverMenuAddBtn.classList.toggle('hidden', !!fl || hasExtras)
    xoverMenuEditBtn.classList.toggle('hidden', !!fl || !hasExtras)

    // Position the menu, keeping it inside the viewport
    xoverMenuEl.style.left = '0'
    xoverMenuEl.style.top  = '0'
    xoverMenuEl.classList.add('visible')
    const mw = xoverMenuEl.offsetWidth, mh = xoverMenuEl.offsetHeight
    const vw = window.innerWidth,       vh = window.innerHeight
    xoverMenuEl.style.left = `${Math.min(clientX, vw - mw - 4)}px`
    xoverMenuEl.style.top  = `${Math.min(clientY, vh - mh - 4)}px`
  }

  xoverMenuDeleteBtn.addEventListener('click', async () => {
    const xo = _currentXo
    const fl = _currentFl
    hide()
    if (fl) {
      await deleteForcedLigation(fl.id)
    } else if (xo) {
      await deleteCrossover(xo.id)
    }
  })

  // Dismiss on any click outside the menu
  document.addEventListener('mousedown', (e) => {
    if ((_currentXo || _currentFl) && !xoverMenuEl.contains(e.target)) hide()
  })

  // Dismiss on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && (_currentXo || _currentFl)) hide()
  })

  return { show, hide, get currentXo() { return _currentXo }, get selectedXoKeys() { return _selectedXoKeys } }
})()

// ── Extra-bases dialog ────────────────────────────────────────────────────────

const _extraBasesDialog = (() => {
  const overlay   = document.getElementById('extra-bases-overlay')
  const input     = document.getElementById('eb-input')
  const errorEl   = document.getElementById('eb-error')
  const applyBtn  = document.getElementById('eb-apply')
  const cancelBtn = document.getElementById('eb-cancel')
  const VALID_RE  = /^[ACGTNacgtn]*$/

  let _resolve = null

  function open(existing) {
    input.value = existing ?? ''
    errorEl.classList.add('hidden')
    overlay.classList.remove('hidden')
    input.focus()
    input.select()
    return new Promise(res => { _resolve = res })
  }

  function close(result) {
    overlay.classList.add('hidden')
    _resolve?.(result)
    _resolve = null
  }

  applyBtn.addEventListener('click', () => {
    const val = input.value.trim().toUpperCase()
    if (!VALID_RE.test(val)) {
      errorEl.textContent = 'Only A, T, G, C, N are allowed.'
      errorEl.classList.remove('hidden')
      return
    }
    close(val)
  })

  cancelBtn.addEventListener('click', () => close(null))

  overlay.addEventListener('mousedown', (e) => {
    if (e.target === overlay) close(null)
  })

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  applyBtn.click()
    if (e.key === 'Escape') close(null)
  })

  return { open }
})()

async function _handleExtraBasesMenuClick() {
  const xo   = _xoverMenu.currentXo
  const keys = _xoverMenu.selectedXoKeys
  _xoverMenu.hide()
  if (!xo) return

  const result = await _extraBasesDialog.open(xo.extra_bases ?? null)
  if (result === null) return   // cancelled

  // If the right-clicked crossover is part of a multi-selection, apply to all selected.
  const rightClickedKey = `xo:${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`
  const applyToAll = keys.length > 1 && keys.includes(rightClickedKey)

  if (applyToAll) {
    const design  = editorStore.getState().design
    const entries = keys.flatMap(k => {
      const m = k.match(/^xo:(.+)_(\d+)_(FORWARD|REVERSE)$/)
      if (!m) return []
      const [, helix_id, index, strand] = m
      const found = design.crossovers?.find(x =>
        x.half_a.helix_id === helix_id &&
        x.half_a.index    === parseInt(index) &&
        x.half_a.strand   === strand,
      )
      return found ? [{ crossover_id: found.id, sequence: result }] : []
    })
    if (entries.length) await batchCrossoverExtraBases(entries)
  } else {
    await patchCrossoverExtraBases(xo.id, result)
  }
}

xoverMenuAddBtn.addEventListener('click',  _handleExtraBasesMenuClick)
xoverMenuEditBtn.addEventListener('click', _handleExtraBasesMenuClick)

// ── Cross-tab selection sync guard ───────────────────────────────────────────
let _syncingFromBroadcast = false

// ── Init views ──────────────────────────────────────────────────────────────
let _spreadsheet = null
const sliceContainerEl = document.getElementById('sliceview-container')
const sliceview = initSliceview(sliceSvg, sliceContainerEl, {
  onAddHelix:    ({ row, col }) => addHelixAtCell(row, col),
  onRemoveHelix: (helixId)     => deleteHelix(helixId),
})

const pathview = initPathview(pathCanvas, pathContainer, {
  onPaintScaffold: async (helixId, loBp, hiBp) => {
    // Auto-extend the helix if the paint range goes outside its current bounds.
    const design = editorStore.getState().design
    const helix  = design?.helices?.find(h => h.id === helixId)
    if (helix) {
      const hLo = helix.bp_start
      const hHi = helix.bp_start + helix.length_bp - 1
      if (loBp < hLo || hiBp > hHi) {
        const ok = await extendHelixBounds(helixId, Math.min(loBp, hLo), Math.max(hiBp, hHi))
        if (!ok) return   // extension failed — don't try to paint
      }
    }
    return scaffoldDomainPaint(helixId, loBp, hiBp)
  },

  onPaintStaple: async (helixId, direction, loBp, hiBp) => {
    // Auto-extend the helix if the paint range goes outside its current bounds.
    const design = editorStore.getState().design
    const helix  = design?.helices?.find(h => h.id === helixId)
    if (helix) {
      const hLo = helix.bp_start
      const hHi = helix.bp_start + helix.length_bp - 1
      if (loBp < hLo || hiBp > hHi) {
        const ok = await extendHelixBounds(helixId, Math.min(loBp, hLo), Math.max(hiBp, hHi))
        if (!ok) return
      }
    }
    return paintStapleDomain(helixId, direction, loBp, hiBp)
  },

  onEraseDomain: (strandId, domainIdx) =>
    domainIdx === null ? deleteStrand(strandId) : deleteDomain(strandId, domainIdx),

  onNickStrand:   (helixId, bpIndex, direction) => nickStrand(helixId, bpIndex, direction),
  onLigateStrand: (helixId, bpIndex, direction) => ligateStrand(helixId, bpIndex, direction),

  onAddCrossover: (halfA, halfB, nickBpA, nickBpB) =>
    placeCrossover(halfA, halfB, nickBpA, nickBpB),

  onMoveCrossover: (crossoverId, newIndex) =>
    moveCrossover(crossoverId, newIndex),

  onBatchMoveCrossovers: (moves) =>
    batchMoveCrossovers(moves),

  onForcedLigation: (threePrimeStrandId, fivePrimeStrandId) =>
    forcedLigation(threePrimeStrandId, fivePrimeStrandId),

  onInsertLoopSkip: (helixId, bpIndex, delta) => insertLoopSkip(helixId, bpIndex, delta),

  onResizeEnds: (entries) => resizeStrandEnds(entries),

  onPaintStrands: async (strandIds) => {
    await patchStrandsColor(strandIds, _getActivePaintColor())
  },

  onSelectionChange: (strandIds) => {
    _spreadsheet?.setSelectedStrands(strandIds)
    if (_syncingFromBroadcast) return
    if (!strandIds?.length) return
    nadocBroadcast.emit('selection-changed', { strandIds })
  },

  onStrandClick: () => {},   // color picker disabled in select mode

  onStrandHover: (info) => {
    editorStore.setState({ hoveredStrand: info })
  },

  onSliceChange: (bp) => sliceview.setSliceBp(bp),

  onCrossoverContextMenu: ({ xo, fl, selectedXoKeys, clientX, clientY }) => {
    _xoverMenu.show(xo, fl, selectedXoKeys, clientX, clientY)
  },

  onDeleteElements: async (elementKeys) => {
    const design = editorStore.getState().design
    if (!design) return

    // Collect crossover IDs to delete (explicit xover selections + those blocking domains)
    const xoverIdsToDelete = new Set()
    // Collect forced ligation IDs to delete
    const flIdsToDelete    = new Set()

    // Collect domain selectors from line/end keys: "{helix_id}|{lo}|{hi}|{direction}"
    const domainSelectors  = new Set()

    // Build set of positions covered by xo:/fl: keys so end: keys at the same
    // position don't cascade into unwanted domain deletions.
    const xoPositions = new Set()
    for (const key of elementKeys) {
      if (key.startsWith('xo:')) {
        const m = key.match(/^xo:(.+)_(\d+)_(FORWARD|REVERSE)$/)
        if (!m) continue
        const [, helix_id, index, strand] = m
        xoPositions.add(`${helix_id}_${index}_${strand}`)
        const xo = design.crossovers?.find(x =>
          x.half_a.helix_id === helix_id &&
          x.half_a.index    === parseInt(index) &&
          x.half_a.strand   === strand
        )
        if (xo) {
          xoverIdsToDelete.add(xo.id)
          // Also mark half_b position so its co-located end: key is skipped
          xoPositions.add(`${xo.half_b.helix_id}_${xo.half_b.index}_${xo.half_b.strand}`)
        }
      } else if (key.startsWith('fl:')) {
        const flId = key.slice(3)  // strip 'fl:' prefix
        const fl = design.forced_ligations?.find(f => f.id === flId)
        if (fl) {
          flIdsToDelete.add(fl.id)
          xoPositions.add(`${fl.three_prime_helix_id}_${fl.three_prime_bp}_${fl.three_prime_direction}`)
          xoPositions.add(`${fl.five_prime_helix_id}_${fl.five_prime_bp}_${fl.five_prime_direction}`)
        }
      }
    }

    for (const key of elementKeys) {
      if (key.startsWith('xo:') || key.startsWith('fl:')) continue  // already handled above
      if (key.startsWith('line:')) {
        const m = key.match(/^line:(.+)_(\d+)_(\d+)_(FORWARD|REVERSE)$/)
        if (m) domainSelectors.add(`${m[1]}|${m[2]}|${m[3]}|${m[4]}`)
      } else if (key.startsWith('end:')) {
        const m = key.match(/^end:(.+)_(\d+)_(FORWARD|REVERSE)$/)
        if (!m) continue
        const [, helix_id, bp, direction] = m
        // Skip end-caps that overlap a selected crossover — the user intended
        // to delete the crossover, not the domain.
        if (xoPositions.has(`${helix_id}_${bp}_${direction}`)) continue
        const bpN = parseInt(bp)
        for (const strand of design.strands) {
          for (const dom of strand.domains) {
            if (dom.helix_id !== helix_id || dom.direction !== direction) continue
            const lo = Math.min(dom.start_bp, dom.end_bp)
            const hi = Math.max(dom.start_bp, dom.end_bp)
            if (bpN === lo || bpN === hi) {
              domainSelectors.add(`${helix_id}|${lo}|${hi}|${direction}`)
              break
            }
          }
        }
      }
    }

    // For each domain to delete, also collect any crossovers referencing its endpoints
    for (const sel of domainSelectors) {
      const [helix_id, lo, hi, direction] = sel.split('|')
      const loN = parseInt(lo), hiN = parseInt(hi)
      const fiveBp  = direction === 'FORWARD' ? loN : hiN
      const threeBp = direction === 'FORWARD' ? hiN : loN
      for (const xo of design.crossovers ?? []) {
        for (const half of [xo.half_a, xo.half_b]) {
          if (half.helix_id === helix_id && half.strand === direction &&
              (half.index === fiveBp || half.index === threeBp)) {
            xoverIdsToDelete.add(xo.id)
          }
        }
      }
    }

    // Delete loop/skip markers (delta=0 removes)
    for (const key of elementKeys) {
      if (!key.startsWith('ls:')) continue
      const m = key.match(/^ls:(.+)_(\d+)_(loop|skip)$/)
      if (!m) continue
      await insertLoopSkip(m[1], parseInt(m[2]), 0)
    }

    // Delete crossovers and forced ligations first (domains fail with 409 if crossovers still reference them)
    if (xoverIdsToDelete.size) await batchDeleteCrossovers([...xoverIdsToDelete])
    if (flIdsToDelete.size)    await batchDeleteForcedLigations([...flIdsToDelete])

    // Delete domains — re-lookup index in the fresh design after each crossover deletion
    for (const sel of domainSelectors) {
      const [helix_id, lo, hi, direction] = sel.split('|')
      const loN = parseInt(lo), hiN = parseInt(hi)
      const cur = editorStore.getState().design
      if (!cur) continue
      let found = false
      for (const strand of cur.strands) {
        if (found) break
        for (let di = 0; di < strand.domains.length; di++) {
          const dom = strand.domains[di]
          if (dom.helix_id !== helix_id || dom.direction !== direction) continue
          const dlo = Math.min(dom.start_bp, dom.end_bp)
          const dhi = Math.max(dom.start_bp, dom.end_bp)
          if (dlo === loN && dhi === hiN) {
            await deleteDomain(strand.id, di)
            found = true; break
          }
        }
      }
    }
  },
})

// ── Strands spreadsheet ─────────────────────────────────────────────────────
_spreadsheet = initStrandsSpreadsheet({
  onSelectStrand: (strandId) => {
    pathview.setSelection([strandId])
    _spreadsheet.setSelectedStrands([strandId])
    if (!_syncingFromBroadcast) {
      nadocBroadcast.emit('selection-changed', { strandIds: [strandId] })
    }
  },
})

// ── Store subscriptions ──────────────────────────────────────────────────────
editorStore.subscribe((state, prev) => {
  // Update tool button active states + notify pathview
  if (state.selectedTool !== prev.selectedTool) {
    for (const [tool, btn] of Object.entries(toolBtns)) {
      btn.classList.toggle('active', tool === state.selectedTool)
    }
    pathview.setTool(state.selectedTool)
    // Dim filter strip when not in select mode
    selectFilterEl.classList.toggle('filter-inactive', state.selectedTool !== 'select')
    // Show/hide paint palette
    paintPaletteEl.classList.toggle('visible', state.selectedTool === 'paint')
  }

  // Sync paint colour (palette index or custom override)
  if (state.paintColorIdx !== prev.paintColorIdx || state.paintCustomColor !== prev.paintCustomColor) {
    _syncPaletteSwatches(state.paintColorIdx, state.paintCustomColor)
    pathview.setPaintColor(_getActivePaintColor())
  }

  // Sync selectable filter buttons + notify pathview
  if (state.selectFilter !== prev.selectFilter) {
    _syncFilterButtons(state.selectFilter)
    pathview.setSelectFilter(state.selectFilter)
  }

  // Sync view tool buttons + notify pathview
  if (state.viewTools !== prev.viewTools) {
    _syncViewToolButtons(state.viewTools)
    pathview.setViewTools(state.viewTools)
  }

  // Update origami name in toolbar
  if (state.design !== prev.design) {
    const name = state.design?.metadata?.name ?? 'Untitled'
    origamiNameEl.textContent = name
    document.title = `NADOC — ${name}`
    const menuBarTitle = document.getElementById('menu-bar-title')
    if (menuBarTitle) menuBarTitle.textContent = `NADOC — ${name}`
    sliceview.update(state.design)
    pathview.update(state.design)
    _spreadsheet?.update(state.design)
  }

  // Update status bar strand hover info + right-corner length
  if (state.hoveredStrand !== prev.hoveredStrand) {
    if (state.hoveredStrand) {
      _isHovering = true
      const { strandType, strandId, ntCount } = state.hoveredStrand
      const label = strandType === 'SCAFFOLD' ? 'Scaffold' : `Staple ${strandId}`
      statusStrandEl.textContent = `${label} — ${ntCount} nt`
      statusRightEl.textContent  = `${ntCount} nt`
    } else {
      _isHovering = false
      statusStrandEl.textContent = '—'
      _update3dConnectionStatus()   // restore connection status immediately
    }
  }

})

// ── BroadcastChannel ────────────────────────────────────────────────────────
nadocBroadcast.onMessage(({ type, strandIds }) => {
  if (type === 'design-changed') {
    fetchDesign()
  }
  if (type === 'selection-changed') {
    // Only positive selections sync cross-window; each window manages its own deselection.
    if (!strandIds?.length) return
    _syncingFromBroadcast = true
    pathview.setSelection(strandIds)
    _spreadsheet?.setSelectedStrands(strandIds)
    _syncingFromBroadcast = false
  }
})

// ── Ligation debug ───────────────────────────────────────────────────────────
initLigationDebug()

// ── Initial load ─────────────────────────────────────────────────────────────
;(async () => {
  loadingOverlay.classList.remove('hidden')
  await fetchDesign()
  loadingOverlay.classList.add('hidden')
})()
