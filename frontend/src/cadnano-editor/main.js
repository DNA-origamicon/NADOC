/**
 * NADOC Origami Editor — main entry point.
 *
 * Initialises the sliceview (SVG lattice picker) and pathview (Canvas strand
 * editor), fetches the current design, and keeps both views in sync with the
 * backend via BroadcastChannel + direct API polls.
 */

import { editorStore }   from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import { addRecentFile, getRecentFiles, closeSession as apiCloseSession,
         listLibraryFiles, getLibraryFileContent, uploadLibraryFile,
         saveDesignAs, saveDesignToWorkspace,
         mkdirLibrary, renameLibrary, moveLibrary, deleteLibraryItem } from '../api/client.js'
import { openFileBrowser } from '../ui/file_browser.js'
import {
  fetchDesign, addHelixAtCell, deleteHelix, extendHelixBounds,
  autoScaffold, scaffoldDomainPaint,
  paintStapleDomain, deleteStrand, deleteStrandsBatch, deleteDomain, nickStrand, ligateStrand, forcedLigation,
  deleteForcedLigation, batchDeleteForcedLigations,
  patchStrand, patchStrandsColor, undoDesign, redoDesign, placeCrossover, moveCrossover, batchMoveCrossovers,
  deleteCrossover, batchDeleteCrossovers, patchCrossoverExtraBases, batchCrossoverExtraBases, patchForcedLigationExtraBases,
  upsertStrandExtensionsBatch, deleteStrandExtensionsBatch,
  resizeStrandEnds, insertLoopSkip, clearAllLoopSkips, generateAllOverhangSequences,
  // menu bar operations
  createDesign, importDesign,
  exportDesign, exportCadnano, exportSequenceCsv,
  addAutoCrossover, addAutoBreak,
  scaffoldExtrudeNear, scaffoldExtrudeFar, autoScaffoldSeamed,
  autoScaffoldAdvancedSeamed, autoScaffoldSeamless, autoScaffoldAdvancedSeamless,
  assignScaffoldSequence, syncScaffoldSequenceResponse, assignStapleSequences,
  applyAllDeformations,
} from './api.js'
import { showToast, showCursorToast } from '../ui/toast.js'
import { initSliceview }  from './sliceview.js'
import { initPathview }   from './pathview.js'
import { initLigationDebug } from './ligation_debug.js'
import { initStrandsSpreadsheet } from './strands_spreadsheet.js'
import { initFeatureLogPanel } from '../ui/feature_log_panel.js'

// ── Tab identity ─────────────────────────────────────────────────────────────
// Each editor tab gets a unique, stable window.name so the 3D view (and other
// editors) can focus it via window.open('', windowName).
window.name = 'nadoc-editor-' + nadocBroadcast.tabId

// Inflate [data-icon] markup once the DOM is ready and watch for new nodes.
import('../ui/primitives/icon.js').then(({ inflateIcons, observeIcons }) => {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { inflateIcons(); observeIcons() })
  } else {
    inflateIcons()
    observeIcons()
  }
})

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

// Server workspace path — shared with the 3D view via localStorage so Ctrl+S in
// either tab always saves to the same server file.
const _WS_PATH_KEY = 'nadoc:workspace-path'
let _workspacePath = localStorage.getItem(_WS_PATH_KEY) || null
function _setWorkspacePath(path) {
  _workspacePath = path
  if (path) localStorage.setItem(_WS_PATH_KEY, path)
  else      localStorage.removeItem(_WS_PATH_KEY)
}

// The 3D view is the authoritative source of the design filename.
// It writes to this localStorage key whenever the user creates or opens a file.
// The cadnano editor reads from it so the tab/title always reflect the correct name.
const _FNAME_KEY = 'nadoc:design-filename'

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

// ── Label / title helper ──────────────────────────────────────────────────────
function _updateLabel() {
  const design   = editorStore.getState().design
  const label    = localStorage.getItem(_FNAME_KEY) ?? design?.metadata?.name ?? 'Untitled'
  if (origamiNameEl) origamiNameEl.textContent = label
  document.title = `NADOC — ${label}`
  const menuBarTitle = document.getElementById('menu-bar-title')
  if (menuBarTitle) menuBarTitle.textContent = `NADOC — ${label}`
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
    _setSyncStatus('red', 'save error')
    _syncLog('err', 'SAVE', `file write failed: ${e.message}`)
    alert(`Save failed: ${e.message}`)
    return false
  }
  _setSyncStatus('green', 'saved')
  _syncLog('info', 'SAVE', `→ ${handle.name}`)
  return true
}

// ── Sync status badge + debug panel ──────────────────────────────────────────

const _syncStatusDot  = document.querySelector('#sync-status .sync-dot')
const _syncStatusText = document.getElementById('sync-status-text')
const _syncDebugPanel = document.getElementById('sync-debug-panel')
document.getElementById('sync-debug-close')?.addEventListener('click', () => {
  _syncDebugPanel?.classList.remove('visible')
})

function _setSyncStatus(state, label) {
  const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
  if (_syncStatusDot)  { _syncStatusDot.className = `sync-dot ${state}` }
  if (_syncStatusText) { _syncStatusText.textContent = `${label} ${ts}` }
}

function _syncLog(level, tag, msg) {
  const cls = level === 'err' ? 'error' : level === 'warn' ? 'warn' : 'log'
  console[cls](`[SYNC][${tag}] ${msg}`)
  const body = document.getElementById('sync-debug-body')
  if (!body) return
  const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
  const row   = document.createElement('div');  row.className   = 'sdp-row'
  const tsEl  = document.createElement('span'); tsEl.className  = 'sdp-ts';  tsEl.textContent = ts
  const tagEl = document.createElement('span'); tagEl.className = `sdp-type ${level==='err'?'err':level==='warn'?'warn':'info'}`; tagEl.textContent = tag
  const msgEl = document.createElement('span'); msgEl.className = 'sdp-msg'; msgEl.textContent = msg
  row.append(tsEl, tagEl, msgEl)
  body.insertBefore(row, body.firstChild)
  while (body.children.length > 150) body.removeChild(body.lastChild)
}

window.__nadocSyncDebug = {
  status() {
    return {
      design:        editorStore.getState().design?.metadata?.name ?? null,
      fileHandle:    _fileHandle?.name ?? null,
      workspacePath: _workspacePath ?? null,
    }
  },
  forceResync() {
    _syncLog('warn', 'FORCE', 'Manual force re-fetch triggered')
    _setSyncStatus('yellow', 'fetching…')
    fetchDesign().then(() => { _setSyncStatus('green', 'synced') })
  },
  show() { _syncDebugPanel?.classList.add('visible') },
  hide() { _syncDebugPanel?.classList.remove('visible') },
}

document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.shiftKey && (e.key === 'd' || e.key === 'D')) {
    e.preventDefault()
    _syncDebugPanel?.classList.toggle('visible')
  }
})

// Track design changes to show "unsaved" state
let _lastSavedDesign   = null
let _suppressUnsavedBadge = false   // true while fetching an externally-driven design update
editorStore.subscribe((next, prev) => {
  if (next.design === prev.design) return
  if (next.design === _lastSavedDesign) return
  if (_suppressUnsavedBadge) return
  if (next.design !== null) {
    _setSyncStatus('yellow', 'unsaved')
    _syncLog('info', 'MUT', `design changed — ${next.design.metadata?.name ?? '?'}`)
  }
})

async function _saveAs() {
  const design = editorStore.getState().design
  if (!design) { alert('No design to save.'); return }
  const stem = _workspacePath
    ? _workspacePath.replace(/\.nadoc$/i, '').split('/').pop()
    : (localStorage.getItem(_FNAME_KEY) ?? design.metadata?.name ?? 'design')
  const result = await openFileBrowser({
    title: 'Save Part As',
    mode: 'save',
    fileType: 'part',
    suggestedName: stem,
    suggestedExt: '.nadoc',
    api: { listLibraryFiles, mkdirLibrary, renameLibrary, moveLibrary, deleteLibraryItem },
  })
  if (!result) return
  _setSyncStatus('yellow', 'saving…')
  const r = await saveDesignAs(result.path, result.overwrite ?? false)
  if (r) {
    _fileHandle = null
    _lastSavedDesign = editorStore.getState().design
    _setWorkspacePath(result.path)
    localStorage.setItem(_FNAME_KEY, result.name)
    _setSyncStatus('green', 'saved')
    _syncLog('info', 'SAVE', `→ ${result.path}`)
    _updateLabel()
  } else {
    _setSyncStatus('red', 'save error')
    _syncLog('err', 'SAVE', `save failed: ${result?.path}`)
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
    return { content: await file.text(), handle, name: handle.name.replace(/\.nadoc$/i, '') }
  }
  return new Promise(resolve => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.nadoc,application/json'
    input.onchange = async () => {
      const file = input.files[0]
      if (!file) { resolve(null); return }
      resolve({ content: await file.text(), handle: null, name: file.name.replace(/\.nadoc$/i, '') })
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
// Both the slice view and the feature log panel read their width from the
// `--cadnano-left-w` CSS variable on :root. The resize handle adjusts that
// single variable so switching tabs preserves the user's chosen width.
const resizeHandle = document.getElementById('resize-handle')
const slicePanel   = document.getElementById('sliceview-panel')
const _LEFT_W_KEY  = 'nadoc.cadnano.leftPanelWidth'

function _setLeftPanelWidth(w) {
  document.documentElement.style.setProperty('--cadnano-left-w', `${w}px`)
}
function _getLeftPanelWidth() {
  // Prefer slicePanel.offsetWidth — accurate even on first read before the
  // CSS variable has been set explicitly (it inherits from the stylesheet).
  return slicePanel.offsetWidth
}

// Restore persisted width on boot (clamped to allowed range).
try {
  const saved = parseFloat(localStorage.getItem(_LEFT_W_KEY) ?? '')
  if (Number.isFinite(saved) && saved >= 80 && saved <= 600) {
    _setLeftPanelWidth(saved)
  }
} catch { /* ignore */ }

let _resizing = false, _resizeStartX = 0, _resizeStartW = 0

resizeHandle.addEventListener('pointerdown', (e) => {
  _resizing    = true
  _resizeStartX = e.clientX
  _resizeStartW = _getLeftPanelWidth()
  resizeHandle.classList.add('dragging')
  resizeHandle.setPointerCapture(e.pointerId)
  e.preventDefault()
})
resizeHandle.addEventListener('pointermove', (e) => {
  if (!_resizing) return
  const w = Math.max(80, Math.min(600, _resizeStartW + (e.clientX - _resizeStartX)))
  _setLeftPanelWidth(w)
})
resizeHandle.addEventListener('pointerup', () => {
  if (!_resizing) return
  _resizing = false
  resizeHandle.classList.remove('dragging')
  try { localStorage.setItem(_LEFT_W_KEY, String(_getLeftPanelWidth())) } catch { /* ignore */ }
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

let _preLoopSkipFilter = null

sfBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.key
    const cur = editorStore.getState().selectFilter
    if (key === 'skip' || key === 'loop') {
      if (!cur[key]) {
        // Turning ON: save state (only when entering from normal mode), then go exclusive
        if (!cur.skip && !cur.loop) _preLoopSkipFilter = { ...cur }
        const patch = {}
        sfBtns.forEach(b => { if (b.dataset.key) patch[b.dataset.key] = false })
        editorStore.setState({ selectFilter: { ...cur, ...patch, [key]: true } })
      } else {
        // Turning OFF: restore saved state
        if (_preLoopSkipFilter) {
          editorStore.setState({ selectFilter: { ..._preLoopSkipFilter } })
          _preLoopSkipFilter = null
        } else {
          editorStore.setState({ selectFilter: { ...cur, [key]: false } })
        }
      }
    } else if (btn.hasAttribute('data-tab-cycle')) {
      editorStore.setState({ selectFilter: { ...cur, ..._selectFilterFor(key) } })
    } else {
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
  const win = window.open('', 'nadoc-3d-view')
  if (win && win.location.href !== 'about:blank') {
    win.focus()          // existing 3D view found — focus it without reloading
  } else if (win) {
    win.location.href = '/'  // blank tab created (no 3D view open) — navigate it
  }
})

// Poll opener state every 2 s; update button + status bar non-intrusively.
let _isHovering = false
function _update3dConnectionStatus() {
  const connected = window.opener && !window.opener.closed
  open3dBtn.textContent = connected ? '3D View ↗' : '3D View ⊕'
  open3dBtn.title       = connected ? 'Focus 3D window' : '3D view disconnected — click to open new window'
  open3dBtn.classList.toggle('disconnected', !connected)
  if (!_isHovering) {
    statusRightEl.textContent = connected ? '' : '3D view disconnected'
  }
}
_update3dConnectionStatus()
setInterval(_update3dConnectionStatus, 2000)

// ── Menu bar — File ──────────────────────────────────────────────────────────
// New Part is disabled in the cadnano editor — designs are created from the 3D view.
// (The menu item is visually disabled in the HTML; this guard prevents any accidental trigger.)

document.getElementById('menu-file-open')?.addEventListener('click', async () => {
  const _fbApi = { listLibraryFiles, mkdirLibrary, renameLibrary, moveLibrary, deleteLibraryItem }
  const result = await openFileBrowser({ title: 'Open from Server', mode: 'open', fileType: 'part', api: _fbApi })
  if (!result) return
  const res = await getLibraryFileContent(result.path)
  if (!res?.content) { alert('Could not load file from server.'); return }
  const r = await importDesign(res.content)
  if (!r) { alert('Failed to open design: ' + (editorStore.getState().lastError?.message ?? 'Unknown error')); return }
  _fileHandle = null
  _setWorkspacePath(result.path)
  localStorage.setItem(_FNAME_KEY, result.name)
  _updateLabel()
  addRecentFile(result.name, res.content)
  _renderRecentMenu()
  _lastSavedDesign = editorStore.getState().design
  _setSyncStatus('green', 'opened')
  _syncLog('info', 'OPEN', `${result.path} from server`)
})

document.getElementById('menu-file-upload')?.addEventListener('click', () => {
  const input = document.createElement('input')
  input.type = 'file'; input.accept = '.nadoc,.nass,application/json'; input.multiple = true
  input.onchange = async (e) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    const _fbApi = { listLibraryFiles, mkdirLibrary, renameLibrary, moveLibrary, deleteLibraryItem }
    for (const file of files) {
      const content = await file.text()
      const ext     = file.name.endsWith('.nass') ? '.nass' : '.nadoc'
      const stem    = file.name.replace(/\.(nadoc|nass)$/i, '')
      const dest    = await openFileBrowser({
        title: `Upload "${file.name}" to…`,
        mode: 'save',
        fileType: ext === '.nass' ? 'assembly' : 'part',
        suggestedName: stem,
        suggestedExt: ext,
        api: _fbApi,
      })
      if (!dest) continue
      await uploadLibraryFile(content, file.name, { destPath: dest.path, overwrite: dest.overwrite ?? false })
      _syncLog('info', 'UPLOAD', `→ ${dest.path}`)
    }
  }
  input.click()
})

document.getElementById('menu-file-download')?.addEventListener('click', async () => {
  const _fbApi = { listLibraryFiles, mkdirLibrary, renameLibrary, moveLibrary, deleteLibraryItem }
  const result = await openFileBrowser({ title: 'Download from Server', mode: 'open', fileType: 'all', api: _fbApi })
  if (!result) return
  const res = await getLibraryFileContent(result.path)
  if (!res?.content) { alert('Could not retrieve file from server.'); return }
  const blob = new Blob([res.content], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = result.path.split('/').pop(); a.click()
  URL.revokeObjectURL(url)
  _syncLog('info', 'DL', `downloaded ${a.download}`)
})

document.getElementById('menu-file-save')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { alert('No design to save.'); return }
  _setSyncStatus('yellow', 'saving…')
  // Prefer server workspace path (shared with 3D view), fall back to local file handle
  const wsPath = localStorage.getItem(_WS_PATH_KEY)
  if (wsPath) {
    _syncLog('info', 'SAVE', `explicit save → ${wsPath}`)
    const r = await saveDesignToWorkspace(wsPath)
    if (r) {
      _lastSavedDesign = editorStore.getState().design
      _setSyncStatus('green', 'saved')
    } else {
      _setSyncStatus('red', 'save error')
    }
  } else if (_fileHandle) {
    _syncLog('info', 'SAVE', `→ ${_fileHandle.name}`)
    await _saveToHandle(_fileHandle)
    _lastSavedDesign = editorStore.getState().design
  } else {
    await _saveAs()
  }
})
document.getElementById('menu-file-save-as')?.addEventListener('click', _saveAs)

// ── Recent files ─────────────────────────────────────────────────────────────
function _renderRecentMenu() {
  const submenu = document.getElementById('recent-files-submenu')
  if (!submenu) return
  const recent = getRecentFiles()
  submenu.innerHTML = ''
  if (!recent.length) {
    const el = document.createElement('button')
    el.className = 'dropdown-item'; el.textContent = 'No recent files'
    el.disabled = true; el.style.color = '#484f58'; el.style.cursor = 'default'
    submenu.appendChild(el)
    return
  }
  for (const entry of recent) {
    const el = document.createElement('button')
    el.className = 'dropdown-item'
    el.textContent = entry.name
    el.addEventListener('click', async () => {
      _fileHandle = null
      localStorage.setItem(_FNAME_KEY, entry.name)
      const result = await importDesign(entry.content)
      if (!result) { alert('Failed to reload: ' + (editorStore.getState().lastError?.message ?? 'Unknown error')); return }
      _updateLabel()
      addRecentFile(entry.name, entry.content)
      _renderRecentMenu()
    })
    submenu.appendChild(el)
  }
}
_renderRecentMenu()

document.getElementById('menu-file-close-session')?.addEventListener('click', async () => {
  _fileHandle = null
  localStorage.removeItem(_FNAME_KEY)
  await apiCloseSession()
  window.location.href = '/'
})

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
    const mode = modal.querySelector('input[name="as-mode"]:checked')?.value || 'seamed'
    modal.classList.remove('visible')
    if (mode === 'seamless') {
      _showProgress('Seamless Scaffold — routing…')
      const ok = await autoScaffoldSeamless()
      _hideProgress()
      if (!ok) { alert('Seamless scaffold failed: ' + (editorStore.getState().lastError?.message ?? 'unknown')) }
      else { _setRoutingCheck('scaffoldEnds', true) }
    } else if (mode === 'advanced-seamed') {
      _showProgress('Advanced Seam Routing — routing…')
      const ok = await autoScaffoldAdvancedSeamed()
      _hideProgress()
      if (!ok) { alert('Advanced seam routing failed: ' + (editorStore.getState().lastError?.message ?? 'unknown')) }
      else { _setRoutingCheck('scaffoldEnds', true) }
    } else if (mode === 'advanced-seamless') {
      _showProgress('Advanced Seamless Routing — routing…')
      const ok = await autoScaffoldAdvancedSeamless()
      _hideProgress()
      if (!ok) { alert('Advanced seamless routing failed: ' + (editorStore.getState().lastError?.message ?? 'unknown')) }
      else { _setRoutingCheck('scaffoldEnds', true) }
    } else {
      _showProgress('Autoscaffold — routing…')
      const ok = await autoScaffoldSeamed()
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

document.getElementById('menu-seq-clear-all-loop-skips')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { alert('No design loaded.'); return }
  if (!confirm('Remove all loop/skip marks from the design?')) return
  const result = await clearAllLoopSkips()
  if (!result) alert('Clear failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'))
  else showToast('All loop/skips cleared.')
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

document.getElementById('menu-seq-generate-overhangs')?.addEventListener('click', async () => {
  const design = editorStore.getState().design
  if (!design) { alert('No design loaded.'); return }
  const ovhgCount = design.overhangs?.length ?? 0
  if (ovhgCount === 0) { alert('No overhangs found.'); return }
  showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
  _showProgress(`Generating sequences for ${ovhgCount} overhang${ovhgCount !== 1 ? 's' : ''}…`)
  const result = await generateAllOverhangSequences()
  _hideProgress()
  if (!result?.ok) {
    alert('Generate overhangs failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'))
  } else {
    showToast(`Sequences generated for ${result.count} overhang${result.count !== 1 ? 's' : ''}.`)
  }
})

// ── Menu bar — Help ───────────────────────────────────────────────────────────
const _helpModal = document.getElementById('help-modal')
document.getElementById('menu-help-hotkeys')?.addEventListener('click', () => _helpModal?.classList.add('visible'))
document.getElementById('help-modal-close')?.addEventListener('click', () => _helpModal?.classList.remove('visible'))
_helpModal?.addEventListener('click', e => { if (e.target === _helpModal) _helpModal.classList.remove('visible') })

const _backgroundContainer = document.getElementById('editor-root') || document.body
const _backgroundModal = document.getElementById('background-modal')
const _bgColorInput = document.getElementById('bg-color-input')
const _bgColorHexInput = document.getElementById('bg-color-hex')
const _bgImageInput = document.getElementById('bg-image-input')
const _bgImageFit = document.getElementById('bg-image-fit')
const _bgImageName = document.getElementById('bg-image-name')
const _bgPreview = document.getElementById('bg-preview')

const _backgroundState = {
  mode: 'color',
  color: '#0d1117',
  imageUrl: '',
  imageName: '',
  imageFit: 'cover',
}

function _formatAqueousBackground() {
  return `radial-gradient(circle at 18% 18%, rgba(255,255,255,0.18), transparent 5%),
    radial-gradient(circle at 78% 22%, rgba(255,255,255,0.14), transparent 4%),
    radial-gradient(circle at 35% 72%, rgba(255,255,255,0.16), transparent 5%),
    radial-gradient(circle at 65% 80%, rgba(255,255,255,0.12), transparent 6%),
    linear-gradient(180deg, rgba(21,96,143,0.94), rgba(2,40,66,0.96))`
}

function _updateBackgroundPreviewText() {
  if (_backgroundState.mode === 'image' && _backgroundState.imageUrl) {
    _bgPreview.textContent = `Image background: ${_backgroundState.imageName || 'selected image'}`
  } else if (_backgroundState.mode === 'aqueous') {
    _bgPreview.textContent = 'Aqueous theme applied. The environment feels cooler and underwater.'
  } else {
    _bgPreview.textContent = `Solid color background: ${_backgroundState.color}`
  }
}

function _applyBackgroundStyle() {
  _backgroundContainer.style.backgroundRepeat = 'no-repeat'
  _backgroundContainer.style.backgroundPosition = 'center center'
  _backgroundContainer.style.backgroundAttachment = 'fixed'

  if (_backgroundState.mode === 'image' && _backgroundState.imageUrl) {
    _backgroundContainer.style.backgroundImage = `url("${_backgroundState.imageUrl}")`
    _backgroundContainer.style.backgroundSize = _backgroundState.imageFit === 'stretch' ? '100% 100%' : _backgroundState.imageFit
    _backgroundContainer.style.backgroundColor = _backgroundState.color
  } else if (_backgroundState.mode === 'aqueous') {
    _backgroundContainer.style.backgroundImage = _formatAqueousBackground()
    _backgroundContainer.style.backgroundSize = 'cover'
    _backgroundContainer.style.backgroundColor = '#07324a'
  } else {
    _backgroundContainer.style.backgroundImage = 'none'
    _backgroundContainer.style.backgroundColor = _backgroundState.color
  }
  _updateBackgroundPreviewText()
}

function _syncBackgroundModal() {
  _bgColorInput && (_bgColorInput.value = _backgroundState.color)
  _bgColorHexInput && (_bgColorHexInput.value = _backgroundState.color)
  if (_bgImageInput) _bgImageInput.value = ''
  if (_bgImageName) _bgImageName.textContent = _backgroundState.imageName || 'No image selected'
  if (_bgImageFit) _bgImageFit.value = _backgroundState.imageFit
  _updateBackgroundPreviewText()
}

_bgColorInput?.addEventListener('input', (event) => {
  _backgroundState.mode = 'color'
  _backgroundState.color = event.target.value
  _bgColorHexInput && (_bgColorHexInput.value = _backgroundState.color)
  _applyBackgroundStyle()
})

_bgColorHexInput?.addEventListener('input', (event) => {
  const value = event.target.value.trim()
  if (/^#[0-9a-fA-F]{6}$/.test(value)) {
    _backgroundState.mode = 'color'
    _backgroundState.color = value
    _bgColorInput && (_bgColorInput.value = value)
    _applyBackgroundStyle()
  }
})

_bgImageInput?.addEventListener('change', (event) => {
  const file = event.target.files?.[0]
  if (!file) {
    _backgroundState.mode = 'color'
    _backgroundState.imageUrl = ''
    _backgroundState.imageName = ''
    _applyBackgroundStyle()
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    _backgroundState.mode = 'image'
    _backgroundState.imageUrl = reader.result
    _backgroundState.imageName = file.name
    _bgImageName && (_bgImageName.textContent = file.name)
    _applyBackgroundStyle()
  }
  reader.readAsDataURL(file)
})

_bgImageFit?.addEventListener('change', (event) => {
  _backgroundState.imageFit = event.target.value
  if (_backgroundState.mode === 'image') _applyBackgroundStyle()
})

document.getElementById('menu-view-background')?.addEventListener('click', () => {
  _syncBackgroundModal()
  if (_backgroundModal) _backgroundModal.style.display = 'flex'
})

document.getElementById('background-modal-close')?.addEventListener('click', () => {
  if (_backgroundModal) _backgroundModal.style.display = 'none'
})

document.getElementById('background-modal-reset')?.addEventListener('click', () => {
  _backgroundState.mode = 'color'
  _backgroundState.color = '#0d1117'
  _backgroundState.imageUrl = ''
  _backgroundState.imageName = ''
  _backgroundState.imageFit = 'cover'
  _syncBackgroundModal()
  _applyBackgroundStyle()
})

document.getElementById('background-modal-aqueous')?.addEventListener('click', () => {
  _backgroundState.mode = 'aqueous'
  _backgroundState.color = '#0d1117'
  _backgroundState.imageUrl = ''
  _backgroundState.imageName = ''
  _syncBackgroundModal()
  _applyBackgroundStyle()
})

document.getElementById('background-modal-apply')?.addEventListener('click', () => {
  if (_backgroundModal) _backgroundModal.style.display = 'none'
})

_backgroundContainer && _applyBackgroundStyle()

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

  // "R" — cycle through select → pencil → nick → paint
  if (e.key === 'r' || e.key === 'R') {
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

// ── Overhang context menu ─────────────────────────────────────────────────────

const ovhgMenuEl      = document.getElementById('overhang-context-menu')
const ovhgMenuNameBtn = document.getElementById('overhang-menu-set-name')

const _ovhgMenu = (() => {
  let _currentId = null

  function hide() {
    ovhgMenuEl.classList.remove('visible')
    _currentId = null
  }

  function show(overhangId, clientX, clientY) {
    _currentId = overhangId
    ovhgMenuEl.style.left = '0'
    ovhgMenuEl.style.top  = '0'
    ovhgMenuEl.classList.add('visible')
    const mw = ovhgMenuEl.offsetWidth, mh = ovhgMenuEl.offsetHeight
    ovhgMenuEl.style.left = `${Math.min(clientX, window.innerWidth  - mw - 4)}px`
    ovhgMenuEl.style.top  = `${Math.min(clientY, window.innerHeight - mh - 4)}px`
  }

  ovhgMenuNameBtn.addEventListener('click', async () => {
    const id = _currentId
    hide()
    if (!id) return
    const design = editorStore.getState().design
    const existing = design?.overhangs?.find(o => o.id === id)?.label ?? ''
    const name = await _ovhgNameDialog.open(existing)
    if (name === null) return
    await api.patchOverhang(id, { label: name || null })
  })

  document.addEventListener('mousedown', (e) => {
    if (_currentId && !ovhgMenuEl.contains(e.target)) hide()
  })
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _currentId) hide()
  })

  return { show, hide }
})()

// ── Overhang name dialog ──────────────────────────────────────────────────────

const _ovhgNameDialog = (() => {
  const overlay = document.createElement('div')
  overlay.className = 'eb-overlay hidden'
  overlay.innerHTML = `
    <div class="eb-dialog" role="dialog">
      <h3 class="eb-title">Set overhang name</h3>
      <input id="ovhg-name-input" class="eb-input" type="text" placeholder="Name…" autocomplete="off" spellcheck="false"/>
      <div class="eb-actions">
        <button id="ovhg-name-cancel" class="eb-btn">Cancel</button>
        <button id="ovhg-name-apply" class="eb-btn primary">Apply</button>
      </div>
    </div>`
  document.body.appendChild(overlay)

  const input     = overlay.querySelector('#ovhg-name-input')
  const applyBtn  = overlay.querySelector('#ovhg-name-apply')
  const cancelBtn = overlay.querySelector('#ovhg-name-cancel')
  let _resolve    = null

  function open(existing) {
    input.value = existing ?? ''
    overlay.classList.remove('hidden')
    input.focus(); input.select()
    return new Promise(res => { _resolve = res })
  }
  function close(result) {
    overlay.classList.add('hidden')
    _resolve?.(result)
    _resolve = null
  }

  applyBtn.addEventListener('click', () => close(input.value.trim()))
  cancelBtn.addEventListener('click', () => close(null))
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') close(input.value.trim())
    if (e.key === 'Escape') close(null)
  })

  return { open }
})()

// ── Strand extension dialog (cadnano editor) ──────────────────────────────────

const _MODIFICATION_NAMES = {
  cy3: 'Cy3', cy5: 'Cy5', fam: 'FAM', tamra: 'TAMRA',
  bhq1: 'BHQ-1', bhq2: 'BHQ-2', atto488: 'ATTO 488', atto550: 'ATTO 550', biotin: 'Biotin',
}

function _openStrandExtDialog(strand, clientX, clientY) {
  document.getElementById('__cadnano-ext-dialog')?.remove()

  const design = editorStore.getState().design
  const ext5   = (design?.extensions ?? []).find(e => e.strand_id === strand.id && e.end === 'five_prime')  ?? null
  const ext3   = (design?.extensions ?? []).find(e => e.strand_id === strand.id && e.end === 'three_prime') ?? null
  const hasAny = !!(ext5 || ext3)

  let defaultEnd = 'five_prime'
  if (ext5 && !ext3) defaultEnd = 'five_prime'
  else if (ext3 && !ext5) defaultEnd = 'three_prime'
  else if (ext5 && ext3) defaultEnd = 'both'

  const prefill = defaultEnd === 'five_prime' && ext5 ? ext5
    : defaultEnd === 'three_prime' && ext3 ? ext3
    : null

  const dlgW = 280, dlgH = 380
  const dlgX = Math.min(clientX + 8, window.innerWidth  - dlgW - 10)
  const dlgY = Math.min(clientY + 8, window.innerHeight - dlgH - 10)

  const dialog = document.createElement('div')
  dialog.id = '__cadnano-ext-dialog'
  dialog.style.cssText = `position:fixed;left:${dlgX}px;top:${dlgY}px;width:${dlgW}px;` +
    `background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:14px 16px;` +
    `z-index:10000;box-shadow:0 8px 24px rgba(0,0,0,.6);font-size:13px;color:#c9d1d9;user-select:none;`

  const title = document.createElement('div')
  title.style.cssText = 'font-size:13px;font-weight:700;margin-bottom:10px;color:#cde'
  title.textContent = hasAny ? 'Edit extensions' : 'Add extension'
  dialog.appendChild(title)

  // End selector
  let endVal = defaultEnd
  const endRow = document.createElement('div')
  endRow.style.cssText = 'display:flex;gap:12px;margin-bottom:10px'
  for (const [val, lbl] of [['five_prime', "5′"], ['three_prime', "3′"], ['both', 'Both']]) {
    const label = document.createElement('label')
    label.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;color:#cde;font-size:12px'
    const radio = document.createElement('input')
    radio.type = 'radio'; radio.name = '__cadnano-ext-end'; radio.value = val
    if (val === defaultEnd) radio.checked = true
    radio.addEventListener('change', () => { endVal = val })
    label.appendChild(radio); label.appendChild(document.createTextNode(lbl))
    endRow.appendChild(label)
  }
  dialog.appendChild(endRow)

  // Sequence input
  const seqLabel = document.createElement('div')
  seqLabel.textContent = 'Sequence (ACGTN, optional):'
  seqLabel.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:4px'
  dialog.appendChild(seqLabel)

  const seqInput = document.createElement('input')
  seqInput.type = 'text'; seqInput.value = prefill?.sequence ?? ''; seqInput.placeholder = 'e.g. TTTT'
  seqInput.style.cssText = 'width:100%;box-sizing:border-box;background:#161b22;border:1px solid #30363d;' +
    'border-radius:4px;color:#c9d1d9;padding:5px 8px;font-family:var(--font-ui);font-size:12px;outline:none;margin-bottom:4px;'
  dialog.appendChild(seqInput)

  const seqHint = document.createElement('div')
  seqHint.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:8px;min-height:14px'
  dialog.appendChild(seqHint)
  seqInput.addEventListener('input', () => {
    const v = seqInput.value.trim().toUpperCase()
    if (v && !/^[ACGTN]+$/.test(v)) { seqHint.textContent = 'Only A, C, G, T, N allowed'; seqHint.style.color = '#ff6b6b' }
    else { seqHint.textContent = v ? `${v.length} bp` : ''; seqHint.style.color = '#8899aa' }
  })

  // Modification dropdown
  const modLabel = document.createElement('div')
  modLabel.textContent = 'Modification:'; modLabel.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:4px'
  dialog.appendChild(modLabel)

  const modSel = document.createElement('select')
  modSel.style.cssText = 'width:100%;background:#161b22;color:#c9d1d9;border:1px solid #30363d;' +
    'border-radius:4px;padding:5px 6px;font-size:12px;cursor:pointer;outline:none;margin-bottom:8px;'
  const noneOpt2 = document.createElement('option'); noneOpt2.value = ''; noneOpt2.textContent = 'None'
  modSel.appendChild(noneOpt2)
  for (const [key, name] of Object.entries(_MODIFICATION_NAMES)) {
    const opt = document.createElement('option'); opt.value = key; opt.textContent = name
    modSel.appendChild(opt)
  }
  modSel.value = prefill?.modification ?? ''
  dialog.appendChild(modSel)

  // Label input
  const lblLabel = document.createElement('div')
  lblLabel.textContent = 'Label (optional):'; lblLabel.style.cssText = 'font-size:11px;color:#8899aa;margin-bottom:4px'
  dialog.appendChild(lblLabel)

  const lblInput = document.createElement('input')
  lblInput.type = 'text'; lblInput.value = prefill?.label ?? ''; lblInput.placeholder = 'e.g. Cy3 dye'
  lblInput.style.cssText = 'width:100%;box-sizing:border-box;background:#161b22;border:1px solid #30363d;' +
    'border-radius:4px;color:#c9d1d9;padding:5px 8px;font-size:12px;outline:none;margin-bottom:10px;'
  dialog.appendChild(lblInput)

  // Remove existing button (shown only when strand has extensions)
  if (hasAny) {
    const remBtn = document.createElement('button')
    remBtn.textContent = 'Remove all extensions'
    remBtn.style.cssText = 'width:100%;background:#21262d;border:1px solid #30363d;color:#ff9999;border-radius:4px;' +
      'padding:5px 14px;cursor:pointer;font-size:12px;margin-bottom:8px;'
    remBtn.addEventListener('click', async () => {
      const ids = [ext5?.id, ext3?.id].filter(Boolean)
      dialog.remove()
      await deleteStrandExtensionsBatch(ids)
    })
    dialog.appendChild(remBtn)
  }

  const errHint = document.createElement('div')
  errHint.style.cssText = 'font-size:11px;color:#ff6b6b;min-height:14px;margin-bottom:6px'
  dialog.appendChild(errHint)

  // Buttons
  const btns = document.createElement('div')
  btns.style.cssText = 'display:flex;gap:8px;justify-content:flex-end'

  const cancelBtn = document.createElement('button')
  cancelBtn.textContent = 'Cancel'
  cancelBtn.style.cssText = 'background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;' +
    'padding:5px 14px;cursor:pointer;font-size:12px;'
  cancelBtn.addEventListener('click', () => dialog.remove())

  const applyBtn = document.createElement('button')
  applyBtn.textContent = 'Apply'
  applyBtn.style.cssText = 'background:#238636;border:1px solid #2ea043;color:#fff;border-radius:4px;' +
    'padding:5px 14px;cursor:pointer;font-size:12px;'
  applyBtn.addEventListener('click', async () => {
    const seq = seqInput.value.trim().toUpperCase() || null
    const mod = modSel.value || null
    const lbl = lblInput.value.trim() || null
    if (!seq && !mod) { errHint.textContent = 'Provide at least a sequence or modification.'; return }
    if (seq && !/^[ACGTN]+$/.test(seq)) { errHint.textContent = 'Sequence contains invalid characters.'; return }

    const ends = endVal === 'both' ? ['five_prime', 'three_prime'] : [endVal]
    const items = ends.map(end => ({ strandId: strand.id, end, sequence: seq, modification: mod, label: lbl }))
    applyBtn.disabled = true; applyBtn.textContent = '…'
    try {
      await upsertStrandExtensionsBatch(items)
      dialog.remove()
    } catch (err) {
      errHint.textContent = err?.message ?? 'Error saving extension.'
      applyBtn.disabled = false; applyBtn.textContent = 'Apply'
    }
  })

  btns.appendChild(cancelBtn); btns.appendChild(applyBtn)
  dialog.appendChild(btns)
  document.body.appendChild(dialog)
  seqInput.focus()

  const _esc = e => {
    if (e.key === 'Escape') { dialog.remove(); document.removeEventListener('keydown', _esc) }
    if (e.key === 'Enter')  { applyBtn.click() }
  }
  document.addEventListener('keydown', _esc)
  requestAnimationFrame(() => {
    const _out = e => {
      if (!dialog.contains(e.target)) { dialog.remove(); document.removeEventListener('mousedown', _out) }
    }
    document.addEventListener('mousedown', _out)
  })
}

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

    // Toggle add vs. edit button based on whether this crossover/FL already has extra bases
    const target    = xo ?? fl
    const hasExtras = !!(target?.extra_bases)
    xoverMenuAddBtn.classList.toggle('hidden', hasExtras)
    xoverMenuEditBtn.classList.toggle('hidden', !hasExtras)

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

  return { show, hide, get currentXo() { return _currentXo }, get currentFl() { return _currentFl }, get selectedXoKeys() { return _selectedXoKeys } }
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
  const fl   = _xoverMenu.currentFl
  const keys = _xoverMenu.selectedXoKeys
  _xoverMenu.hide()

  if (fl) {
    // Forced ligation — single item, no multi-selection support
    const result = await _extraBasesDialog.open(fl.extra_bases ?? null)
    if (result === null) return
    await patchForcedLigationExtraBases(fl.id, result)
    return
  }

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

  onOverhangContextMenu: ({ overhangId, clientX, clientY }) => {
    _ovhgMenu.show(overhangId, clientX, clientY)
  },

  onStrandContextMenu: ({ strand, clientX, clientY }) => {
    _openStrandExtDialog(strand, clientX, clientY)
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

    // Delete loop/skip markers in parallel (delta=0 removes, each is independent)
    const lsKeys = [...elementKeys].filter(k => k.startsWith('ls:'))
    if (lsKeys.length) {
      await Promise.all(lsKeys.map(key => {
        const m = key.match(/^ls:(.+)_(\d+)_(loop|skip)$/)
        return m ? insertLoopSkip(m[1], parseInt(m[2]), 0) : null
      }))
    }

    // Delete crossovers and forced ligations first (domains fail with 409 if crossovers still reference them)
    if (xoverIdsToDelete.size) await batchDeleteCrossovers([...xoverIdsToDelete])
    if (flIdsToDelete.size)    await batchDeleteForcedLigations([...flIdsToDelete])

    // Delete domains — partition into whole-strand batch vs. partial-strand sequential.
    // Whole-strand: all domains of the strand are selected → single batch API call.
    // Partial-strand: only some domains selected → re-lookup by geometry key after each delete.
    if (domainSelectors.size) {
      const cur = editorStore.getState().design
      if (cur) {
        // Map each selector to the strand + domain index it refers to
        const strandGroups = new Map()  // strandId → { strand, selectedIndices: Set<number> }
        for (const sel of domainSelectors) {
          const [helix_id, lo, hi, direction] = sel.split('|')
          const loN = parseInt(lo), hiN = parseInt(hi)
          for (const strand of cur.strands) {
            let matchIdx = -1
            for (let di = 0; di < strand.domains.length; di++) {
              const dom = strand.domains[di]
              if (dom.helix_id !== helix_id || dom.direction !== direction) continue
              const dlo = Math.min(dom.start_bp, dom.end_bp)
              const dhi = Math.max(dom.start_bp, dom.end_bp)
              if (dlo === loN && dhi === hiN) { matchIdx = di; break }
            }
            if (matchIdx >= 0) {
              if (!strandGroups.has(strand.id)) {
                strandGroups.set(strand.id, { strand, selectedIndices: new Set() })
              }
              strandGroups.get(strand.id).selectedIndices.add(matchIdx)
              break
            }
          }
        }

        // Split into whole-strand (batch) and partial-strand (sequential)
        const wholeStrandIds = []
        const partialSelectors = []  // geometry keys for domains in partially-selected strands

        for (const [strandId, { strand, selectedIndices }] of strandGroups) {
          if (selectedIndices.size === strand.domains.length) {
            wholeStrandIds.push(strandId)
          } else {
            // Keep the original geometry selectors for partial-strand domains
            for (const sel of domainSelectors) {
              const [helix_id, lo, hi, direction] = sel.split('|')
              const loN = parseInt(lo), hiN = parseInt(hi)
              const owns = strand.domains.some(dom => {
                if (dom.helix_id !== helix_id || dom.direction !== direction) return false
                return Math.min(dom.start_bp, dom.end_bp) === loN && Math.max(dom.start_bp, dom.end_bp) === hiN
              })
              if (owns) partialSelectors.push(sel)
            }
          }
        }

        // One batch call for whole-strand deletions
        if (wholeStrandIds.length === 1) await deleteStrand(wholeStrandIds[0])
        else if (wholeStrandIds.length > 1) await deleteStrandsBatch(wholeStrandIds)

        // Sequential only for the rare partial-strand cases, re-lookup index each time
        for (const sel of partialSelectors) {
          const [helix_id, lo, hi, direction] = sel.split('|')
          const loN = parseInt(lo), hiN = parseInt(hi)
          const fresh = editorStore.getState().design
          if (!fresh) break
          for (const strand of fresh.strands) {
            let found = false
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
            if (found) break
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
    _updateLabel()
    sliceview.update(state.design)
    pathview.update(state.design)
    _spreadsheet?.update(state.design)
    // Re-announce with updated name so all registries (3D view + other editors) stay current.
    _announceself('editor-title-changed')
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
nadocBroadcast.onMessage(async ({ type, strandIds, source, windowName, designName }) => {
  if (type === 'design-changed') {
    _syncLog('info', 'BC-RX', `design-changed from ${source?.slice(0, 8) ?? '?'}`)
    _setSyncStatus('yellow', 'syncing…')
    _suppressUnsavedBadge = true
    try {
      await fetchDesign()
      _setSyncStatus('green', 'synced')
    } finally {
      _suppressUnsavedBadge = false
    }
    _updateLabel()
  }
  if (type === 'selection-changed') {
    // Only positive selections sync cross-window; each window manages its own deselection.
    if (!strandIds?.length) return
    _syncingFromBroadcast = true
    pathview.setSelection(strandIds)
    _spreadsheet?.setSelectedStrands(strandIds)
    _syncingFromBroadcast = false
  }
  if (type === 'editor-list-request') {
    // 3D view (or another editor) is asking all editors to re-announce themselves.
    _announceself('editor-announce')
  }
  if (type === 'editor-announce' || type === 'editor-title-changed') {
    _editorRegistry.set(source, { windowName, designName })
    _renderEditorDropdown()
  }
  if (type === 'editor-goodbye') {
    _editorRegistry.delete(source)
    _renderEditorDropdown()
  }
  if (type === 'session-closed') {
    // The 3D window closed the session. This editor tab was opened by it via
    // window.open(), so window.close() works (browser allows close for
    // script-opened windows). Best-effort — if blocked, the user just sees
    // a "session ended" tab they can close manually.
    try { window.close() } catch { /* best-effort */ }
  }
})

// ── Editor tab registry ──────────────────────────────────────────────────────
// Tracks other open cadnano editors via BroadcastChannel, populating the
// "Editors" dropdown so the user can jump between open editor tabs.
const _editorRegistry = new Map()  // source tabId → { windowName, designName }

function _announceself(msgType = 'editor-announce') {
  const design = editorStore.getState().design
  const name   = localStorage.getItem(_FNAME_KEY) ?? design?.metadata?.name ?? 'Untitled'
  nadocBroadcast.emit(msgType, { windowName: window.name, designName: name })
}

function _renderEditorDropdown() {
  const menuItem = document.getElementById('menu-item-editors')
  const dropdown = document.getElementById('editor-list-dropdown')
  if (!menuItem || !dropdown) return
  dropdown.innerHTML = ''

  if (_editorRegistry.size === 0) {
    menuItem.style.display = 'none'
    return
  }

  menuItem.style.display = ''
  for (const [, { windowName, designName }] of _editorRegistry) {
    const btn = document.createElement('button')
    btn.className = 'dropdown-item'
    btn.textContent = designName || 'Untitled'
    btn.addEventListener('click', () => {
      const win = window.open('', windowName)
      if (win) win.focus()
    })
    dropdown.appendChild(btn)
  }
}

window.addEventListener('beforeunload', () => {
  nadocBroadcast.emit('editor-goodbye')
})

// ── Ligation debug ───────────────────────────────────────────────────────────
initLigationDebug()

// ── Side tab strip + Feature Log panel ───────────────────────────────────────
// The cadnano editor has its own editorStore (with `design` field), but the
// shared feature_log_panel module expects a store with `currentDesign`. We
// shim the API surface so the panel can mount unchanged.
{
  // Adapt editorStore → { currentDesign, currentAssembly, lastError } shape.
  const _flStore = {
    getState() {
      const s = editorStore.getState()
      return {
        currentDesign:    s.design,
        currentAssembly:  null,
        assemblyActive:   false,
        lastError:        s.lastError,
      }
    },
    setState(_partial) { /* feature_log_panel never calls this */ },
    subscribe(fn) {
      return editorStore.subscribe((next, prev) => {
        fn(
          { currentDesign: next.design, currentAssembly: null, assemblyActive: false, lastError: next.lastError },
          { currentDesign: prev.design, currentAssembly: null, assemblyActive: false, lastError: prev.lastError },
        )
      })
    },
    subscribeSlice(slice, fn) {
      // The panel only uses 'design' and 'assembly' slices. Map 'design' to
      // editorStore subscription; 'assembly' is a no-op (not applicable here).
      if (slice === 'design') {
        return editorStore.subscribe((next, prev) => {
          fn({ currentDesign: next.design }, { currentDesign: prev.design })
        })
      }
      return () => {}
    },
  }

  // Minimal API shim — only the methods feature_log_panel actually calls.
  // After mutation, refresh editorStore.design so subscribers (including the
  // panel itself) re-render with the latest feature_log.
  async function _flMutate(method, path, body) {
    const init = body !== undefined
      ? { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : { method }
    const r = await fetch(`/api${path}`, init)
    const json = await r.json().catch(() => null)
    if (!r.ok) {
      editorStore.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
      return null
    }
    editorStore.setState({ lastError: null })
    if (json?.design) editorStore.setState({ design: json.design })
    return json
  }

  const _flApi = {
    seekFeatures:         (position, subPosition = null) =>
      _flMutate('POST', '/design/features/seek', { position, sub_position: subPosition }),
    deleteFeature:        (i) => _flMutate('DELETE', `/design/features/${i}`),
    revertToBeforeFeature:(i) => _flMutate('POST',   `/design/features/${i}/revert`),
    editFeature:          (i, params) => _flMutate('POST', `/design/features/${i}/edit`, { params }),
  }

  const flPanel = initFeatureLogPanel(_flStore, { api: _flApi })

  // Tab strip click → swap which left-side panel is visible.
  const tabStrip   = document.getElementById('cadnano-tab-strip')
  const slicePanelEl = document.getElementById('sliceview-panel')
  const flPanelEl    = document.getElementById('cadnano-feature-log-container')
  if (tabStrip && slicePanelEl && flPanelEl) {
    const tabBtns = tabStrip.querySelectorAll('.cn-tab-btn')
    function _setActiveTab(tabId) {
      for (const b of tabBtns) b.classList.toggle('active', b.dataset.tab === tabId)
      slicePanelEl.style.display = tabId === 'slice'       ? '' : 'none'
      flPanelEl.classList.toggle('is-active', tabId === 'feature-log')
    }
    for (const b of tabBtns) {
      b.addEventListener('click', () => _setActiveTab(b.dataset.tab))
    }
  }
  // Suppress unused-var warning in non-strict modes.
  void flPanel
}

// ── Initial load ─────────────────────────────────────────────────────────────
;(async () => {
  loadingOverlay.classList.remove('hidden')
  await fetchDesign()
  loadingOverlay.classList.add('hidden')
  // Announce after the design is loaded so the name is correct.
  _announceself('editor-announce')
})()
