/**
 * NADOC Origami Editor — main entry point.
 *
 * Initialises the sliceview (SVG lattice picker) and pathview (Canvas strand
 * editor), fetches the current design, and keeps both views in sync with the
 * backend via BroadcastChannel + direct API polls.
 */

import { editorStore }   from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import * as connectionMonitor from '../shared/connection_monitor.js'
import { docHeaders, docKey } from '../shared/doc_id.js'
import { addRecentFile, getRecentFiles, closeSession as apiCloseSession,
         listLibraryFiles, getLibraryFileContent, uploadLibraryFile,
         saveDesignAs, saveDesignToWorkspace,
         mkdirLibrary, renameLibrary, moveLibrary, deleteLibraryItem } from '../api/client.js'
import { openFileBrowser } from '../ui/file_browser.js'
import { initMenuFlyouts } from '../ui/menu_flyouts.js'
import {
  fetchDesign, addHelixAtCell, deleteHelix, reorderHelices, extendHelixBounds,
  scaffoldDomainPaint,
  paintStapleDomain, deleteStrand, deleteStrandsBatch, deleteDomain, nickStrand, ligateStrand, forcedLigation,
  deleteForcedLigation, batchDeleteForcedLigations,
  patchStrand, getStrandSequenceContext,
  patchStrandsColor, patchStrandsReference, patchOverhang, undoDesign, redoDesign, placeCrossover, moveCrossover, batchMoveCrossovers,
  deleteCrossover, batchDeleteCrossovers, patchCrossoverExtraBases, batchCrossoverExtraBases, patchForcedLigationExtraBases,
  upsertStrandExtensionsBatch, deleteStrandExtensionsBatch, savePlateLayout, convertStrandToBinder, generateBinderForOverhang, convertBinderToScaffold,
  resizeStrandEnds, shiftDomains, insertLoopSkip, clearAllLoopSkips, generateAllOverhangSequences,
  // menu bar operations
  createDesign, importDesign,
  exportDesign, exportCadnano, exportScadnano, exportSequenceCsv,
  addFullAutostaple, routeForPolymerization,
  autoScaffoldSeamed, autoScaffoldSeamless,
  assignScaffoldSequence, syncScaffoldSequenceResponse, assignStapleSequences,
  applyAllDeformations,
  seekFeatures, deleteFeature, revertToBeforeFeature, editFeature,
  resetRevisionWatermark, getSyncDebugState, onSyncEvent,
} from './api.js'
import { showToast, showCursorToast } from '../ui/toast.js'
import { showConfirm } from '../ui/primitives/confirm.js'
import { initSliceview }  from './sliceview.js'
import { initPathview }   from './pathview.js'
import { initZoomScope }  from './zoom_scope.js'
import { initLigationDebug } from './ligation_debug.js'
import { initStrandsSpreadsheet } from './strands_spreadsheet.js'
import { initFeatureLogPanel } from '../ui/feature_log_panel.js'
import { initPlateView } from '../ui/plate_view.js'
import { initStrandSequenceDialog } from '../ui/strand_sequence_dialog.js'
import { buildStrandMenuItems } from '../ui/strand_menu_items.js'
import { createContextMenu } from '../ui/primitives/context_menu.js'
import { ensureStapleColors, stapleColorOf, EXT_MOD_NAMES } from './pathview/palette.js'

initMenuFlyouts()
import { xoverKey, parseXoverKey, parseLineKey, parseEndKey, parseLoopSkipKey, parseForcedLigKey } from './element_keys.js'
import { SCAFFOLD_LENGTHS, ascWarningText, countScaffoldNt } from '../scene/scaffold_assign.js'

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

// Server workspace path — shared with the 3D view of THIS SAME document
// (doc-scoped key) via localStorage so Ctrl+S in either tab saves to the same
// file. Scoping by doc id keeps two different parts' editors from clobbering
// each other's save target.
const _WS_PATH_KEY = docKey('nadoc:workspace-path')
let _workspacePath = localStorage.getItem(_WS_PATH_KEY) || null
function _setWorkspacePath(path) {
  _workspacePath = path
  // Best-effort: a full localStorage quota must never throw on open.
  try {
    if (path) localStorage.setItem(_WS_PATH_KEY, path)
    else      localStorage.removeItem(_WS_PATH_KEY)
  } catch { /* quota / private mode — ignore */ }
}

// The 3D view is the authoritative source of the design filename.
// It writes to this (doc-scoped) localStorage key whenever the user creates or
// opens a file. The cadnano editor reads from it so the tab/title always reflect
// the correct name for THIS document.
const _FNAME_KEY = docKey('nadoc:design-filename')

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
  const r = await fetch('/api/design/export', { headers: docHeaders() })
  if (!r.ok) return null
  return r.text()
}

async function _saveToHandle(handle) {
  const content = await _getDesignContent()
  if (!content) { showToast('Failed to read design from server.', { severity: 'error' }); return false }
  try {
    const writable = await handle.createWritable()
    await writable.write(content)
    await writable.close()
  } catch (e) {
    _setSyncStatus('red', 'save error')
    _syncLog('err', 'SAVE', `file write failed: ${e.message}`)
    showToast(`Save failed: ${e.message}`, { severity: 'error' })
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

// ── Backend connection monitor: status badge + restart recovery ────────────────
// On disconnect the badge goes red. On a server restart the backend session-cache
// has normally restored the design — we just re-pull it. If the backend came back
// empty but this editor still holds the design in memory, offer to push it back.
let _restartHandling = false
connectionMonitor.start({ onChange: async (evt) => {
  if (evt.type === 'disconnected') {
    _setSyncStatus('red', 'reconnecting…')
    _syncLog('warn', 'CONN', 'backend unreachable — reconnecting')
  } else if (evt.type === 'reconnected') {
    _setSyncStatus('green', 'reconnected')
    _syncLog('info', 'CONN', 'backend reachable again')
  } else if (evt.type === 'restarted') {
    if (_restartHandling) return
    _restartHandling = true
    _setSyncStatus('yellow', 'backend restarted — re-syncing…')
    _syncLog('warn', 'CONN', 'backend restarted — re-syncing')
    // The backend's per-session revision resets low after a restart; clear the
    // stale-response watermark so post-restart responses aren't dropped as
    // "older" (which would freeze the editor on pre-restart data).
    resetRevisionWatermark()
    try {
      const json = await fetchDesign()
      if (!json?.design) {
        // Backend came back empty. Prefer reloading the autosaved workspace file:
        // it holds the COMPLETE design, whereas the editor's in-memory copy has
        // STRIPPED feature-log payload blobs (the backend omits them from
        // skip-geometry responses) — re-importing that would permanently lose the
        // fine-routing revert history. Fall back to the in-memory import only for
        // a never-saved design (no workspace file).
        const wsPath = localStorage.getItem(_WS_PATH_KEY)
        if (wsPath) {
          const res = await getLibraryFileContent(wsPath)
          if (res?.content) {
            await importDesign(res.content)
            nadocBroadcast.emit('design-changed')
          }
        } else {
          const mem = editorStore.getState().design
          if (mem && window.confirm(
              'The backend restarted and no longer has the design loaded.\n\n' +
              'Restore it from this editor tab? (Unsaved fine-routing history may be lost.)')) {
            await fetch('/api/design/import', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', ...docHeaders() },
              body: JSON.stringify({ content: JSON.stringify(mem) }),
            })
            await fetchDesign()
            nadocBroadcast.emit('design-changed')
          }
        }
      }
      _setSyncStatus('green', 'synced')
    } catch (e) {
      _setSyncStatus('red', 'recovery error')
      _syncLog('err', 'CONN', `recovery failed: ${e?.message ?? e}`)
    } finally {
      _restartHandling = false
    }
  }
} })

// Surface every sync decision (APPLY / DROP-stale / RESET) in the debug panel,
// so a dropped out-of-order response is visible while reproducing the bug.
onSyncEvent((e) => {
  if (e.decision === 'DROP') {
    _syncLog('warn', 'SYNC',
      `DROP stale ${e.source} rev=${e.rev} < applied=${e.lastRev} (kept newer state)`)
  } else if (e.decision === 'RESET') {
    _syncLog('info', 'SYNC', 'revision watermark reset (backend restart)')
  } else if (e.decision === 'APPLY' && e.rev != null) {
    _syncLog('log', 'SYNC', `apply ${e.source} rev=${e.rev} strands=${e.strands} flog=${e.flog}`)
  }
})

window.__nadocSyncDebug = {
  status() {
    return {
      design:        editorStore.getState().design?.metadata?.name ?? null,
      fileHandle:    _fileHandle?.name ?? null,
      workspacePath: _workspacePath ?? null,
    }
  },
  /** Stale-response guard state: docId, last-applied revision, in-flight count,
   *  dropped count, and the recent sync-decision log. */
  sync() {
    const s = getSyncDebugState()
    console.group('[nadocSyncDebug] sync state')
    console.log('docId          :', s.docId)
    console.log('lastAppliedRev :', s.lastAppliedRev)
    console.log('inFlight       :', s.inFlight)
    console.log('dropped (stale):', s.dropped)
    console.log('store strands  :', s.storeStrands, ' feature_log:', s.storeFlog)
    console.table(s.log)
    console.groupEnd()
    return s
  },
  /** Compare this editor's store to the BACKEND document it targets — the fastest
   *  way to spot a desync (different revision / feature_log length / doc). */
  async backend() {
    const h = { ...docHeaders() }
    const [design, health] = await Promise.all([
      fetch('/api/design', { headers: h }).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch('/api/health').then(r => r.json()).catch(() => null),
    ])
    const store = editorStore.getState().design
    const out = {
      docId:            getSyncDebugState().docId,
      server_instance:  health?.server_instance_id ?? null,
      backend_revision: design?.revision ?? null,
      backend_flog:     design?.design?.feature_log?.length ?? null,
      backend_strands:  design?.design?.strands?.length ?? null,
      store_flog:       store?.feature_log?.length ?? null,
      store_strands:    store?.strands?.length ?? null,
      lastAppliedRev:   getSyncDebugState().lastAppliedRev,
      IN_SYNC:          (design?.design?.feature_log?.length ?? -1) === (store?.feature_log?.length ?? -2),
    }
    console.group('[nadocSyncDebug] backend vs store')
    Object.entries(out).forEach(([k, v]) => console.log(k.padEnd(17) + ':', v))
    if (!out.IN_SYNC) console.warn('DESYNC: panel and backend feature_log differ — re-open the file or forceResync().')
    console.groupEnd()
    return out
  },
  forceResync() {
    _syncLog('warn', 'FORCE', 'Manual force re-fetch triggered')
    _setSyncStatus('yellow', 'fetching…')
    _suppressUnsavedBadge = true   // pulling backend state is not a local edit
    resetRevisionWatermark()       // accept whatever the backend currently has
    fetchDesign()
      .finally(() => { _suppressUnsavedBadge = false })
      .then(() => { _setSyncStatus('green', 'synced') })
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

// Track design changes to drive the unsaved badge + autosave.
let _lastSavedDesign   = null
let _suppressUnsavedBadge = false   // true while fetching an externally-driven design update

// ── Autosave ──────────────────────────────────────────────────────────────
// Persist to the current save target after every edit so changes are never lost
// between manual saves. Edits made in THIS tab schedule a debounced write; the
// debounce coalesces drag bursts and batch ops into a single save. Externally
// driven updates (a BroadcastChannel re-fetch) are suppressed, so only the tab
// that originated a change writes it — no two-tab write race.
//
// If the design was never saved (no workspace path or file handle yet) there is
// no target to write to: we leave the badge on "unsaved" and wait for the user's
// first manual Save to establish a target, after which autosave takes over.
const _AUTOSAVE_DEBOUNCE_MS = 600
let _autosaveTimer    = null
let _autosaveInFlight = false
let _autosavePending  = false

function _hasSaveTarget() {
  return !!(localStorage.getItem(_WS_PATH_KEY) || _fileHandle)
}

async function _runAutosave() {
  if (_autosaveInFlight) { _autosavePending = true; return }
  if (!_hasSaveTarget()) return
  const designAtSave = editorStore.getState().design
  if (!designAtSave || designAtSave === _lastSavedDesign) return   // nothing new
  _autosaveInFlight = true
  const wsPath = localStorage.getItem(_WS_PATH_KEY)
  try {
    if (wsPath) {
      _setSyncStatus('yellow', 'saving…')
      // Tell sibling tabs (3D view) BEFORE the write that this file change is
      // OURS, so they skip the SSE file-changed reload. Without this, the 3D
      // tab reloads our autosave back into the shared backend doc — a stale
      // snapshot — clobbering in-progress edits (nicks "reverting a second
      // later"). The 5s self-saved window on the receiver covers SSE latency.
      nadocBroadcast.emit('file-saved', { path: wsPath })
      const ok = !!(await saveDesignToWorkspace(wsPath))
      if (ok) {
        _lastSavedDesign = designAtSave
        _setSyncStatus('green', 'saved')
        _syncLog('info', 'AUTOSAVE', `→ ${wsPath}`)
      } else {
        _setSyncStatus('red', 'save error')
        _syncLog('err', 'AUTOSAVE', `workspace save failed: ${wsPath}`)
      }
    } else if (_fileHandle) {
      const ok = await _saveToHandle(_fileHandle)   // sets its own badge + log
      if (ok) _lastSavedDesign = designAtSave
    }
  } catch (e) {
    _setSyncStatus('red', 'save error')
    _syncLog('err', 'AUTOSAVE', `failed: ${e.message}`)
  } finally {
    _autosaveInFlight = false
    if (_autosavePending) { _autosavePending = false; _scheduleAutosave() }
  }
}

function _scheduleAutosave() {
  if (_autosaveTimer) clearTimeout(_autosaveTimer)
  _autosaveTimer = setTimeout(() => { _autosaveTimer = null; _runAutosave() }, _AUTOSAVE_DEBOUNCE_MS)
}

editorStore.subscribe((next, prev) => {
  if (next.design === prev.design) return
  if (next.design === _lastSavedDesign) return
  if (_suppressUnsavedBadge) return
  if (next.design === null) return
  _setSyncStatus('yellow', 'unsaved')
  _syncLog('info', 'MUT', `design changed — ${next.design.metadata?.name ?? '?'}`)
  if (_hasSaveTarget()) _scheduleAutosave()   // debounced; flips badge to saved
})

async function _saveAs() {
  const design = editorStore.getState().design
  if (!design) { showToast('No design to save.', { severity: 'error' }); return }
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

// ── Hand-edit one strand's sequence ──────────────────────────────────────────
// Same dialog module the 3D editor uses; the api wrapper differs (this editor's
// ./api.js drives editorStore), so it is injected rather than imported by the module.
const _strandSequenceDialog = initStrandSequenceDialog({
  api: { getStrandSequenceContext, patchStrand },
  showToast,
})

// ── Assign scaffold sequence modal ───────────────────────────────────────────
// Opened either from the Sequencing menu (whole design → first scaffold) or from
// a scaffold strand's right-click "Edit sequence…" (one specific strand), which
// mirrors the 3D viewport's scaffold context menu.

// Which strand the currently-open modal targets (null = first scaffold), and the
// nt count for that strand — read by the warning updater and the apply handler.
let _ascTargetStrandId = null
let _ascTotalNt = 0
let _ascListenersWired = false

function _openScaffoldModal(targetStrandId = null) {
  const design = editorStore.getState().design
  if (!design) { showToast('No design loaded.', { severity: 'error' }); return }
  if (targetStrandId != null) {
    const st = design.strands?.find(s => s.id === targetStrandId)
    if (st?.strand_type !== 'scaffold') { showToast('Not a scaffold strand.', { severity: 'error' }); return }
  }

  _ascTargetStrandId = targetStrandId
  const totalNt = countScaffoldNt(design, targetStrandId)
  _ascTotalNt = totalNt

  const modal       = document.getElementById('assign-scaffold-modal')
  const lengthEl    = document.getElementById('asc-length-line')
  const warnEl      = document.getElementById('asc-warning')
  const customSeqEl = document.getElementById('asc-custom-seq')
  const charCountEl = document.getElementById('asc-custom-char-count')
  const customErrEl = document.getElementById('asc-custom-error')

  if (customSeqEl) customSeqEl.value = ''
  if (charCountEl) charCountEl.textContent = '0 nt'
  if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }

  lengthEl.textContent = targetStrandId != null
    ? `Scaffold length: ${totalNt} nt (selected strand only)`
    : `Scaffold length: ${totalNt} nt`
  modal.style.display = 'flex'

  // Wire the field events once — reopening the modal must not stack duplicate
  // listeners (they would each close over a stale nt count).
  if (!_ascListenersWired) {
    _ascListenersWired = true
    modal.querySelectorAll('input[name="asc-scaffold"]').forEach(r => r.addEventListener('change', _ascUpdateWarning))
    customSeqEl?.addEventListener('input', () => {
      const raw = customSeqEl.value.replace(/\s/g, '').toUpperCase()
      if (charCountEl) charCountEl.textContent = `${raw.length} nt`
      const bad = [...new Set(raw.replace(/[ATGCN]/g, ''))]
      if (bad.length > 0) {
        if (customErrEl) { customErrEl.textContent = `Invalid: ${bad.join(', ')}`; customErrEl.style.display = 'inline' }
      } else {
        if (customErrEl) { customErrEl.textContent = ''; customErrEl.style.display = 'none' }
      }
      _ascUpdateWarning()
    })
  }
  _ascUpdateWarning()
}

function _ascUpdateWarning() {
  const modal  = document.getElementById('assign-scaffold-modal')
  const warnEl = document.getElementById('asc-warning')
  if (!modal || !warnEl) return
  const customRaw    = (document.getElementById('asc-custom-seq')?.value ?? '').replace(/\s/g, '').toUpperCase()
  const scaffoldName = modal.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
  const text = ascWarningText({
    customRaw,
    totalNt: _ascTotalNt,
    scaffoldName,
    scaffoldLen: SCAFFOLD_LENGTHS[scaffoldName] ?? 0,
  })
  warnEl.textContent = text ?? ''
  warnEl.style.display = text ? 'block' : 'none'
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

document.getElementById('btn-autoscaffold').addEventListener('click', async () => {
  await autoScaffoldSeamed()
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
  // Reflect the toggle's state as a ✓ on its View-menu item.
  document.getElementById('menu-view-periodic-boundary')
    ?.classList.toggle('is-checked', !!viewTools.periodicBoundary)
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
  if (!res?.content) { showToast('Could not load file from server.', { severity: 'error' }); return }
  const r = await importDesign(res.content)
  if (!r) { showToast('Failed to open design: ' + (editorStore.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' }); return }
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
        title: `Import "${file.name}" — choose destination`,
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

document.getElementById('menu-file-save')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { showToast('No design to save.', { severity: 'error' }); return }
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
      if (!result) { showToast('Failed to reload: ' + (editorStore.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' }); return }
      _updateLabel()
      addRecentFile(entry.name, entry.content)
      _renderRecentMenu()
    })
    submenu.appendChild(el)
  }
}
_renderRecentMenu()

document.getElementById('menu-file-close-session')?.addEventListener('click', async () => {
  // Broadcast first so other NADOC tabs (3D window + sibling editors) close
  // / reset before we navigate. Best-effort wrapped so a channel error
  // doesn't block the local close.
  try { nadocBroadcast.emit('session-closed') } catch { /* best-effort */ }
  _fileHandle = null
  localStorage.removeItem(_FNAME_KEY)
  await apiCloseSession()
  window.location.href = '/'
})

document.getElementById('menu-file-export-seq-csv')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
  const ok = await exportSequenceCsv()
  if (!ok) showToast('Export failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
})
document.getElementById('menu-file-export-native')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
  if (!await exportDesign()) showToast('Part export failed.', { severity: 'error' })
})
document.getElementById('menu-file-export-cadnano')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
  const ok = await exportCadnano()
  if (!ok) showToast('Export failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
})
document.getElementById('menu-file-export-scadnano')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
  const ok = await exportScadnano()
  if (!ok) showToast('scadnano export failed.', { severity: 'error' })
})
document.getElementById('menu-file-export-pdb')?.addEventListener('click', () => {
  if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
  const a = document.createElement('a'); a.href = '/api/design/export/pdb'; a.download = ''; a.click()
})
document.getElementById('menu-file-export-psf')?.addEventListener('click', () => {
  if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
  const a = document.createElement('a'); a.href = '/api/design/export/psf'; a.download = ''; a.click()
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
    if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
    const mode = modal.querySelector('input[name="as-mode"]:checked')?.value || 'seamed'
    modal.classList.remove('visible')
    if (mode === 'seamless') {
      _showProgress('Seamless Scaffold — routing…')
      const ok = await autoScaffoldSeamless()
      _hideProgress()
      if (!ok) { showToast('Seamless scaffold failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'), { severity: 'error' }) }
      else { _setRoutingCheck('scaffoldEnds', true) }
    } else {
      _showProgress('Autoscaffold — routing…')
      const ok = await autoScaffoldSeamed()
      _hideProgress()
      if (!ok) { showToast('Autoscaffold failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'), { severity: 'error' }) }
      else { _setRoutingCheck('scaffoldEnds', true) }
    }
  }

  document.getElementById('menu-routing-scaffold-ends')?.addEventListener('click', () => {
    if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
    modal.classList.add('visible')
  })
  btnRun?.addEventListener('click', _runAutoscaffold)
  btnCancel?.addEventListener('click', () => modal.classList.remove('visible'))
  modal?.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('visible') })
})()

// Auto Crossover + Autobreak retired from the Routing menu in favour of one-click
// Full Autostaple ('2'). The backend endpoints + autobreak modal markup remain for revival.

document.getElementById('menu-routing-full-autostaple')?.addEventListener('click', async () => {
  if (!editorStore.getState().design?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
  _showProgress('Full autostaple', 'Assigning sequences and routing staples…')
  const result = await addFullAutostaple({ scaffold_name: 'M13mp18' })
  _hideProgress()
  if (!result) {
    showToast('Full autostaple failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
    return
  }
  const full = result.full_autostaple ?? {}
  showToast(`Full autostaple complete: ${full.auto_crossover?.placed ?? 0} crossovers placed.`)
})

document.getElementById('menu-routing-polymerization')?.addEventListener('click', async () => {
  if (!editorStore.getState().design?.helices?.length) { showToast('No design loaded.', { severity: 'error' }); return }
  const result = await routeForPolymerization()
  if (!result) {
    showToast('Route for polymerization failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
    return
  }
  const nBridges = result.seam_ligation_ids?.length ?? 0
  const warnings = result.warnings ?? []
  if (warnings.length) showToast(`Routed ${nBridges} bridging staple(s). ${warnings[0]}`, { severity: 'warning' })
  else showToast(`Routed for polymerization: ${nBridges} bridging staple(s) across the seam.`)
})

document.getElementById('menu-seq-update-routing')?.addEventListener('click', async () => {
  const design = editorStore.getState().design
  if (!design) { showToast('No design loaded.', { severity: 'error' }); return }
  const hasCrossovers = design.strands?.some(s =>
    s.domains?.some((d, i) => i > 0 && d.helix_id !== s.domains[i - 1].helix_id)
  )
  if (!hasCrossovers) { showToast('Place crossovers first (Full Autostaple) before adding loops/skips.', { severity: 'error' }); return }
  _showProgress('Adding loops/skips…')
  const result = await applyAllDeformations()
  _hideProgress()
  if (!result) showToast('Add Loops/Skips failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
  else showToast(
    'Loops/skips added — method of Dietz, Douglas & Shih, Science 2009 (doi:10.1126/science.1174251).',
    {
      duration: 8000,
      action: {
        label: 'View paper',
        onClick: () => window.open('https://doi.org/10.1126/science.1174251', '_blank', 'noopener'),
      },
    },
  )
})

document.getElementById('menu-seq-clear-all-loop-skips')?.addEventListener('click', async () => {
  if (!editorStore.getState().design) { showToast('No design loaded.', { severity: 'error' }); return }
  const ok = await showConfirm({
    title: 'Clear loops & skips',
    message: 'Remove all loop/skip marks from the design?',
    danger: true,
    confirmLabel: 'Clear all',
  })
  if (!ok) return
  const result = await clearAllLoopSkips()
  if (!result) showToast('Clear failed: ' + (editorStore.getState().lastError?.message ?? 'unknown error'), { severity: 'error' })
  else showToast('All loop/skips cleared.')
})

// Enable Add Loops/Skips when crossovers are present
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
document.getElementById('menu-seq-assign-scaffold')?.addEventListener('click', () => _openScaffoldModal(null))

document.getElementById('asc-cancel')?.addEventListener('click', () => {
  document.getElementById('assign-scaffold-modal').style.display = 'none'
  _ascTargetStrandId = null
})
document.getElementById('assign-scaffold-modal')?.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('assign-scaffold-modal').style.display = 'none'
    _ascTargetStrandId = null
  }
  if (e.key === 'Enter')  document.getElementById('asc-apply')?.click()
})
document.getElementById('asc-apply')?.addEventListener('click', async () => {
  const modal        = document.getElementById('assign-scaffold-modal')
  const scaffoldName = modal.querySelector('input[name="asc-scaffold"]:checked')?.value ?? 'M13mp18'
  const customRaw    = (document.getElementById('asc-custom-seq')?.value ?? '').replace(/\s/g, '').toUpperCase()
  const customErrEl  = document.getElementById('asc-custom-error')
  if (customRaw && customErrEl?.textContent) return
  const targetStrandId = _ascTargetStrandId
  modal.style.display = 'none'
  _ascTargetStrandId = null   // clear targeting after use
  const label = customRaw ? `custom (${customRaw.length} nt)` : scaffoldName
  _showProgress(`Assigning ${label} sequence…`)
  const json = await assignScaffoldSequence(scaffoldName, {
    customSequence: customRaw || null,
    strandId: targetStrandId,
  })
  _hideProgress()
  if (!json) { showToast('Assign scaffold sequence failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'), { severity: 'error' }); return }
  await syncScaffoldSequenceResponse(json)
  const padMsg = json.padded_nt > 0 ? ` (${json.padded_nt} nt padded with N)` : ''
  showToast(`${label} sequence assigned.${padMsg}`)
})

document.getElementById('menu-seq-assign-staples')?.addEventListener('click', async () => {
  const design = editorStore.getState().design
  if (!design) { showToast('No design loaded.', { severity: 'error' }); return }
  const scaffold = design.strands?.find(s => s.strand_type === 'scaffold')
  if (!scaffold?.sequence) { showToast('Scaffold has no sequence. Run "Assign Scaffold Sequence" first.', { severity: 'error' }); return }
  _showProgress('Deriving complementary staple sequences…')
  const ok = await assignStapleSequences()
  _hideProgress()
  if (!ok) showToast('Assign staple sequences failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
})

document.getElementById('menu-seq-generate-overhangs')?.addEventListener('click', async () => {
  const design = editorStore.getState().design
  if (!design) { showToast('No design loaded.', { severity: 'error' }); return }
  const ovhgCount = design.overhangs?.length ?? 0
  if (ovhgCount === 0) { showToast('No overhangs found.', { severity: 'error' }); return }
  showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
  _showProgress(`Generating sequences for ${ovhgCount} overhang${ovhgCount !== 1 ? 's' : ''}…`)
  const result = await generateAllOverhangSequences()
  _hideProgress()
  if (!result?.ok) {
    showToast('Generate overhangs failed: ' + (editorStore.getState().lastError?.message ?? 'unknown'), { severity: 'error' })
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

document.getElementById('menu-view-periodic-boundary')?.addEventListener('click', () => {
  const cur = editorStore.getState().viewTools
  editorStore.setState({ viewTools: { ...cur, periodicBoundary: !cur.periodicBoundary } })
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

  // "F" — fit-to-view (slice + path views)
  if (e.key === 'f' || e.key === 'F') {
    e.preventDefault()
    sliceview?.fitToContent?.()
    pathview?.fitToContent?.()
    return
  }

  // "R" — cycle through select → pencil → nick → paint
  if (e.key === 'r' || e.key === 'R') {
    const _tCycle = ['select', 'pencil', 'nick', 'paint']
    const cur = editorStore.getState().selectedTool
    const idx = _tCycle.indexOf(cur)
    const next = _tCycle[(idx + 1) % _tCycle.length]
    editorStore.setState({ selectedTool: next })
    showCursorToast(_toolDisplayNames[next] ?? next, _lastMouseX, _lastMouseY)
  }

  // "N" — Nick tool
  if (e.key === 'n' || e.key === 'N') {
    editorStore.setState({ selectedTool: 'nick' })
    showCursorToast(_toolDisplayNames.nick ?? 'Nick', _lastMouseX, _lastMouseY)
    return
  }

  // "P" — Paint tool. Pressing P again while already on Paint nudges the paint
  // colour up by one hex unit (#RRGGBB + 1, wrapping at #ffffff), so each press
  // yields a distinct colour — handy for grouping strands by colour afterwards.
  if (e.key === 'p' || e.key === 'P') {
    if (editorStore.getState().selectedTool === 'paint') {
      const cur  = _getActivePaintColor()
      const n    = (parseInt(cur.slice(1), 16) + 1) & 0xffffff
      const next = '#' + n.toString(16).padStart(6, '0')
      editorStore.setState({ paintCustomColor: next })
      showCursorToast(next, _lastMouseX, _lastMouseY)
    } else {
      editorStore.setState({ selectedTool: 'paint' })
      showCursorToast(_toolDisplayNames.paint ?? 'Paint', _lastMouseX, _lastMouseY)
    }
    return
  }

  // Tab — cycle through selectable filter items (strand, line, ends, xover only)
  // "strand" turns all on; every other key is exclusive (only that one active).
  if (e.key === 'Tab' && e.target?.tagName?.toUpperCase() === 'CANVAS') {
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
  // '2' = one-click Full Autostaple (subsumes Auto Crossover + Autobreak, which
  // are now hotkey-less).
  if (e.key === '2') { const b = document.getElementById('menu-routing-full-autostaple'); if (b && !b.disabled) b.click() }
  if (e.key === '4') { const b = document.getElementById('menu-seq-update-routing'); if (b && !b.disabled) b.click() }
  if (e.key === '5') document.getElementById('menu-seq-assign-scaffold')?.click()
  if (e.key === '6') document.getElementById('menu-seq-assign-staples')?.click()

  // Spreadsheet toggle
  if (e.key === 's' || e.key === 'S') { _spreadsheet?.toggle(); return }

  // Help modal
  if (e.key === '?' || e.key === 'F1') _helpModal?.classList.add('visible')
  if (e.key === 'Escape') {
    // 1. Close help modal if open. 2. Otherwise drop back to Select tool —
    // matches the universal sketch-mode convention (Blender, Illustrator, etc.)
    // and gives users an escape hatch from accidental pencil/nick/paint mode.
    if (_helpModal?.classList.contains('visible')) {
      _helpModal.classList.remove('visible')
      return
    }
    const cur = editorStore.getState().selectedTool
    if (cur && cur !== 'select') {
      editorStore.setState({ selectedTool: 'select' })
      showCursorToast(_toolDisplayNames.select ?? 'Select', _lastMouseX, _lastMouseY)
    }
  }
})

// ── Overhang context menu ─────────────────────────────────────────────────────

const ovhgMenuEl       = document.getElementById('overhang-context-menu')
const ovhgMenuNameBtn  = document.getElementById('overhang-menu-set-name')
const ovhgMenuBinderBtn = document.getElementById('overhang-menu-generate-binder')

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
    await patchOverhang(id, { label: name || null })
  })

  ovhgMenuBinderBtn?.addEventListener('click', async () => {
    const id = _currentId
    hide()
    if (!id) return
    await generateBinderForOverhang(id)
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

// ── Strand right-click context menu (cadnano editor) ──────────────────────────

// Latest strand selection emitted by pathview (for multi-select "Make Reference").
let _lastSelectedStrandIds = []
let _strandCtxMenu = null   // { root, close } from createContextMenu

function _hideStrandCtxMenu() {
  _strandCtxMenu?.close()
  _strandCtxMenu = null
}

/**
 * Strand right-click menu. The items themselves come from the SHARED
 * ui/strand_menu_items.js (the 3D viewport builds the same list from the same
 * module), and rendering/placement/dismissal come from the shared
 * ui/primitives/context_menu.js — so neither the labels nor the visibility rules
 * can drift between the two editors any more.
 */
function _showStrandCtxMenu(strand, clientX, clientY) {
  _hideStrandCtxMenu()
  const design = editorStore.getState().design
  // Apply to the whole selection if the right-clicked strand is part of it; else just this one.
  const sel = _lastSelectedStrandIds.includes(strand.id)
    ? _lastSelectedStrandIds.slice()
    : [strand.id]
  const allRef = sel.length > 0 &&
    sel.every(id => design?.strands?.find(s => s.id === id)?.is_reference)
  const anyRef = sel.some(id => design?.strands?.find(s => s.id === id)?.is_reference)

  const items = buildStrandMenuItems(
    { strandIds: sel, strandType: strand.strand_type, allReference: allRef, anyReference: anyRef },
    {
      onSetReference: (ids, makeRef) => patchStrandsReference(ids, makeRef),
      onConvertToBinder: (id) => convertStrandToBinder(id),
      onConvertToScaffold: (id) => convertBinderToScaffold(id),
      onAssignScaffoldSequence: (id) => _openScaffoldModal(id),
      onEditSequence: (id) => _strandSequenceDialog.open(id),
      onEditExtensions: () => _openStrandExtDialog(strand, clientX, clientY),
    },
  )
  if (!items.length) return
  _strandCtxMenu = createContextMenu({
    x: clientX, y: clientY, items,
    onClose: () => { _strandCtxMenu = null },
  })
}

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
  const rightClickedKey = xoverKey(xo)
  const applyToAll = keys.length > 1 && keys.includes(rightClickedKey)

  if (applyToAll) {
    const design  = editorStore.getState().design
    const entries = keys.flatMap(k => {
      const p = parseXoverKey(k)
      if (!p) return []
      const found = design.crossovers?.find(x =>
        x.half_a.helix_id === p.helix_id &&
        x.half_a.index    === p.index &&
        x.half_a.strand   === p.strand,
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

  onForcedLigation: (threePrimeStrandId, fivePrimeStrandId, isPeriodicSeam = false) =>
    forcedLigation(threePrimeStrandId, fivePrimeStrandId, isPeriodicSeam),

  onInsertLoopSkip: (helixId, bpIndex, delta) => insertLoopSkip(helixId, bpIndex, delta),

  onResizeEnds: (entries) => resizeStrandEnds(entries),

  onShiftDomains: (entries) => shiftDomains(entries),

  onReorderHelices: (orderedIds) => reorderHelices(orderedIds),

  onPaintStrands: async (strandIds) => {
    await patchStrandsColor(strandIds, _getActivePaintColor())
  },

  onSelectionChange: (strandIds) => {
    _lastSelectedStrandIds = strandIds ?? []
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
    _showStrandCtxMenu(strand, clientX, clientY)
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
        const p = parseXoverKey(key)
        if (!p) continue
        const { helix_id, index, strand } = p
        xoPositions.add(`${helix_id}_${index}_${strand}`)
        const xo = design.crossovers?.find(x =>
          x.half_a.helix_id === helix_id &&
          x.half_a.index    === index &&
          x.half_a.strand   === strand
        )
        if (xo) {
          xoverIdsToDelete.add(xo.id)
          // Also mark half_b position so its co-located end: key is skipped
          xoPositions.add(`${xo.half_b.helix_id}_${xo.half_b.index}_${xo.half_b.strand}`)
        }
      } else if (key.startsWith('fl:')) {
        const flId = parseForcedLigKey(key)?.id   // codec owns the 'fl:' prefix
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
        const p = parseLineKey(key)
        if (p) domainSelectors.add(`${p.helix_id}|${p.lo}|${p.hi}|${p.direction}`)
      } else if (key.startsWith('end:')) {
        const p = parseEndKey(key)
        if (!p) continue
        const { helix_id, bp: bpN, direction } = p
        // Skip end-caps that overlap a selected crossover — the user intended
        // to delete the crossover, not the domain.
        if (xoPositions.has(`${helix_id}_${bpN}_${direction}`)) continue
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
        const p = parseLoopSkipKey(key)
        return p ? insertLoopSkip(p.helix_id, p.bp, 0) : null
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

// Space-held magnifier lens — same UX as the main 3D app's zoom_scope.
// Purely visual; clicks pass through to pathCanvas. Re-renders the world
// at lens transform via pathview.drawToLens() so the magnified content is
// crisp instead of pixel-upscaled.
const _zoomScope = initZoomScope(pathCanvas, pathview)

// ── Strands spreadsheet ─────────────────────────────────────────────────────
_spreadsheet = initStrandsSpreadsheet({
  onSelectStrand: (strandId) => {
    pathview.setSelection([strandId])
    _spreadsheet.setSelectedStrands([strandId])
    if (!_syncingFromBroadcast) {
      nadocBroadcast.emit('selection-changed', { strandIds: [strandId] })
    }
  },
  onEditSequence: (strandId) => _strandSequenceDialog.open(strandId),
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

  // Push the unligated-crossover marker set into pathview whenever it
  // changes. The set is recomputed on every backend response (any nick or
  // crossover edit), so the ⚠ marker auto-appears / auto-clears in lockstep
  // with topology mutations.
  if (state.unligatedCrossoverIds !== prev.unligatedCrossoverIds) {
    pathview.setUnligatedCrossoverIds?.(state.unligatedCrossoverIds)
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
nadocBroadcast.onMessage(async (data) => {
  const { type, strandIds, source } = data
  if (type === 'design-changed') {
    if (!nadocBroadcast.isSameDoc(data)) return   // doc-scoped: only our document
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
    if (!nadocBroadcast.isSameDoc(data)) return   // doc-scoped
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
    // Another NADOC tab closed the session. Try window.close() first (works
    // for script-opened tabs); if the browser blocks it, fall back to
    // navigating this tab to the 3D welcome screen so the user isn't left
    // staring at stale state. setTimeout fires only if the close didn't
    // actually tear down the tab.
    try { window.close() } catch { /* best-effort */ }
    setTimeout(() => { window.location.href = '/' }, 50)
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

  // Feature-log ops use the editor's api functions (NOT a bare fetch): they
  // carry docHeaders() so they hit THIS editor's document — the previous inline
  // shim omitted the doc header and hit the default doc, producing "Feature
  // index N out of range (log has 1 entries)". They also forward subIndex for
  // per-sub-step revert/delete and ride the stale-response guard.
  const _flApi = {
    seekFeatures,
    deleteFeature,          // (index, subIndex)
    revertToBeforeFeature,  // (index, subIndex)
    editFeature,            // (index, params)
  }

  const flPanel = initFeatureLogPanel(_flStore, { api: _flApi })

  // ── Plates and tubes panel (96-well plate layout + IDT tube list) ───────────
  const platesPanelEl = document.getElementById('cadnano-plates-panel')
  let _platesView = null
  let _platesSig = null
  const _plateLayoutSig = layout => JSON.stringify(layout ?? null)
  let _renderedPlateLayoutSig = _plateLayoutSig(null)
  const _sig = (d) => d ? JSON.stringify([
    d.id,
    (d.strands ?? []).filter(s => ['staple', 'linker', 'oh_binder'].includes(s.strand_type) && !s.is_reference)
      .map(s => `${s.id}:${s.name || ''}:${s.color || ''}:${s.domains?.length ?? 0}`),
    (d.extensions ?? []).map(e => `${e.strand_id}:${e.modification || ''}`),
  ]) : 'null'
  function _refreshPlates() {
    if (!_platesView) return
    const design = editorStore.getState().design
    if (!design) {
      _platesView.setData([], null)
      _platesSig = _sig(null)
      _renderedPlateLayoutSig = _plateLayoutSig(null)
      return
    }
    ensureStapleColors(design)
    const helixById = Object.fromEntries((design.helices ?? []).map(h => [h.id, h]))
    const modOf = new Map()
    for (const e of design.extensions ?? []) {
      if (e.modification && !modOf.has(e.strand_id)) modOf.set(e.strand_id, e.modification)
    }
    const records = []
    let idx = 0
    for (const s of design.strands ?? []) {
      if (!['staple', 'linker', 'oh_binder'].includes(s.strand_type) || s.is_reference) continue
      idx += 1
      const lengthNt = (s.domains ?? []).reduce((sum, d) => {
        const h = helixById[d.helix_id]
        const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
        const skip = (h?.loop_skips ?? [])
          .filter(ls => ls.bp_index >= lo && ls.bp_index <= hi)
          .reduce((a, ls) => a + ls.delta, 0)
        return sum + (Math.abs(d.end_bp - d.start_bp) + 1) + skip
      }, 0)
      const mod = modOf.get(s.id) || null
      records.push({
        strandId: s.id,
        color: stapleColorOf(s),
        lengthNt,
        groupId: null,            // cadnano editor has no strand groups
        groupOrder: Infinity,
        hasMod: !!mod,
        modName: mod ? (EXT_MOD_NAMES[mod] || mod) : null,
        sequence: s.sequence || '',
        name: `S${idx}`,
      })
    }
    _platesView.setData(records, design.plate_layout ?? null)
    _platesSig = _sig(design)
    _renderedPlateLayoutSig = _plateLayoutSig(design.plate_layout)
  }

  // Tab strip click → swap which left-side panel is visible.
  const tabStrip   = document.getElementById('cadnano-tab-strip')
  const slicePanelEl = document.getElementById('sliceview-panel')
  const flPanelEl    = document.getElementById('cadnano-feature-log-container')
  if (tabStrip && slicePanelEl && flPanelEl) {
    const tabBtns = tabStrip.querySelectorAll('.cn-tab-btn')
    if (platesPanelEl) {
      _platesView = initPlateView(document.getElementById('cn-plate-canvas'), {
        wrapEl: document.getElementById('cn-plate-canvas-wrap'),
        toolbarEl: document.getElementById('cn-plate-toolbar'),
        getTubesContainer: () => document.getElementById('cn-plate-tubes'),
        enableGroupMode: false,                 // no group system in the cadnano editor
        onSaveLayout: (layout) => {
          _renderedPlateLayoutSig = _plateLayoutSig(layout)
          savePlateLayout(layout)
        },
        onStrandClick: (sid) => {
          // Highlight the strand in the pathview + the spreadsheet (which
          // autoscrolls to the row). Empty well clears the selection.
          const ids = sid ? [sid] : []
          pathview.setSelection(ids)
          _spreadsheet?.setSelectedStrands(ids)
        },
      })
    }
    function _setActiveTab(tabId) {
      for (const b of tabBtns) b.classList.toggle('active', b.dataset.tab === tabId)
      slicePanelEl.style.display = tabId === 'slice'       ? '' : 'none'
      flPanelEl.classList.toggle('is-active', tabId === 'feature-log')
      if (platesPanelEl) platesPanelEl.classList.toggle('is-active', tabId === 'plates')
      if (tabId === 'plates') { _refreshPlates(); _platesView?.resetView() }
    }
    for (const b of tabBtns) {
      b.addEventListener('click', () => _setActiveTab(b.dataset.tab))
    }
    // Refresh for topology changes and EXTERNAL layout changes (undo/redo or
    // the other editor), but not for our own save response.
    editorStore.subscribe((state, prev) => {
      if (state.design === prev.design) return
      if (!platesPanelEl?.classList.contains('is-active')) return
      const sig = _sig(state.design)
      const layoutSig = _plateLayoutSig(state.design?.plate_layout)
      if (sig === _platesSig && layoutSig === _renderedPlateLayoutSig) return
      _refreshPlates()
    })
  }
  // Suppress unused-var warning in non-strict modes.
  void flPanel
}

// ── Initial load ─────────────────────────────────────────────────────────────
;(async () => {
  loadingOverlay.classList.remove('hidden')
  // Loading the current design is not an edit — suppress the unsaved/autosave
  // path and mark the freshly-loaded design as already persisted.
  _suppressUnsavedBadge = true
  try {
    await fetchDesign()
  } finally {
    _suppressUnsavedBadge = false
  }
  _lastSavedDesign = editorStore.getState().design
  _setSyncStatus('green', 'synced')
  loadingOverlay.classList.add('hidden')
  // Announce after the design is loaded so the name is correct.
  _announceself('editor-announce')
})()
