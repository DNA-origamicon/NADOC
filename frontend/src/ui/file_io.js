// File open / save operations (design + assembly).
//
// Extracted verbatim from main.js's "File open / save" + "Assembly file save
// helpers" regions (Tier-5 carve-up, extraction #52). These are the cohesive
// file-IO operations — reading the active design's .nadoc from the server,
// writing it back through a File System Access API handle, "Save As" via the
// file-browser dialog, and the part-edit save-back-to-assembly path.
//
// Deliberately LEFT in main.js (the lifecycle spine — called from 20+ sites and
// not file-IO per se): _resetForNewDesign / _enterAssemblyMode /
// _exitAssemblyMode, plus the mutable file/path state (_fileHandle /
// _assemblyFileHandle / _assemblyName / _workspacePath / _assemblyWorkspacePath /
// _partEditContext) and its setters, and _updateAssemblyTitle. Those flow in as
// get/set shims + injected fns so the lifted operations stay verbatim.
//
// The dead _pickOpenFile (showOpenFilePicker wrapper, zero callers in the design
// editor — the cadnano editor has its own copy) was dropped, not carried.

import { openFileBrowser } from './file_browser.js'
import { showToast } from './toast.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import { docHeaders } from '../shared/doc_id.js'

/**
 * @param {object} deps
 * @param {object}   deps.store
 * @param {object}   deps.api
 * @param {Function} deps.setSyncStatus  (state, label)
 * @param {Function} deps.syncLog        (level, tag, msg)
 * @param {object}   deps.libraryPanel   (optional .refresh())
 * @param {Function} deps.updateAssemblyTitle
 * @param {Function} deps.setWorkspacePath
 * @param {Function} deps.setFileName
 * @param {Function} deps.setAssemblyWorkspacePath
 * @param {Function} deps.setFileHandle
 * @param {Function} deps.setAssemblyFileHandle
 * @param {Function} deps.setAssemblyName
 * @param {Function} deps.getWorkspacePath
 * @param {Function} deps.getAssemblyWorkspacePath
 * @param {Function} deps.getAssemblyName
 * @param {Function} deps.getPartEditContext
 * @returns {{getDesignContent, savePartToAssembly, saveToHandle, saveAs, saveAssemblyToHandle, saveAssemblyAs}}
 */
export function initFileIo({
  store, api,
  setSyncStatus, syncLog,
  libraryPanel,
  updateAssemblyTitle,
  setWorkspacePath, setFileName, setAssemblyWorkspacePath,
  setFileHandle, setAssemblyFileHandle, setAssemblyName,
  getWorkspacePath, getAssemblyWorkspacePath, getAssemblyName, getPartEditContext,
}) {
  /** Fetch the active design's .nadoc JSON from the server. */
  async function getDesignContent() {
    const r = await fetch('/api/design/export', { headers: docHeaders() })
    if (!r.ok) return null
    return r.text()
  }

  /** Save this tab's design back to the assembly instance, then notify the assembly tab. */
  async function savePartToAssembly({ silent = false } = {}) {
    if (!getPartEditContext()) return null
    const content = await getDesignContent()
    if (!content) {
      if (!silent) showToast('Failed to read design.', { severity: 'error' })
      return null
    }
    const ctx = getPartEditContext()
    // Save-back targets the ASSEMBLY's doc (this tab edits on its own isolated doc).
    const result = await api.patchInstanceDesign(ctx.instanceId, content, { docId: ctx.assemblyDoc })
    if (result) {
      syncLog('info', 'BC-TX', `part-design-updated id=${ctx.instanceId}`)
      setSyncStatus('green', silent ? 'auto-saved to assembly' : 'saved to assembly')
      nadocBroadcast.emit('part-design-updated', { instanceId: ctx.instanceId })
      if (!silent) {
        const modeEl = document.getElementById('mode-indicator')
        modeEl.textContent = `PART EDIT — ${ctx.name} ✓ saved`
        setTimeout(() => { modeEl.textContent = `PART EDIT — ${getPartEditContext()?.name}` }, 2000)
      }
    } else {
      setSyncStatus('red', 'save error')
      syncLog('err', 'BC-TX', `patchInstanceDesign failed for id=${ctx.instanceId}`)
      if (!silent) showToast('Save to assembly failed — assembly session may have expired.', { severity: 'error' })
    }
    return result
  }

  /** Save design to an existing file handle (in-place overwrite). */
  async function saveToHandle(handle) {
    const content = await getDesignContent()
    if (!content) { showToast('Failed to read design from server.', { severity: 'error' }); return false }
    try {
      const writable = await handle.createWritable()
      await writable.write(content)
      await writable.close()
    } catch (e) {
      showToast(`Save failed: ${e.message}`, { severity: 'error' })
      return false
    }
    return true
  }

  /** Save As — server-side only.  Updates session identity to the chosen path. */
  async function saveAs() {
    const { currentDesign } = store.getState()
    if (!currentDesign) { showToast('No design to save.', { severity: 'error' }); return }
    const workspacePath = getWorkspacePath()
    const stem = workspacePath
      ? workspacePath.replace(/\.nadoc$/i, '').split('/').pop()
      : (currentDesign.metadata?.name ?? 'design')
    const result = await openFileBrowser({
      title: 'Save Part As',
      mode: 'save',
      fileType: 'part',
      suggestedName: stem,
      suggestedExt: '.nadoc',
      api,
    })
    if (!result) return
    setSyncStatus('yellow', 'saving…')
    const r = await api.saveDesignAs(result.path, result.overwrite ?? false)
    if (r) {
      setFileHandle(null)
      setWorkspacePath(result.path)
      setFileName(result.name)
      setSyncStatus('green', 'saved')
      libraryPanel?.refresh()
    } else {
      setSyncStatus('red', 'save error')
    }
  }

  async function saveAssemblyToHandle(handle) {
    const content = await api.getAssemblyContent()
    if (!content) { showToast('Failed to read assembly from server.', { severity: 'error' }); return false }
    try {
      const writable = await handle.createWritable()
      await writable.write(content)
      await writable.close()
    } catch (e) {
      showToast(`Save failed: ${e.message}`, { severity: 'error' })
      return false
    }
    return true
  }

  async function saveAssemblyAs() {
    const { currentAssembly } = store.getState()
    const assemblyWorkspacePath = getAssemblyWorkspacePath()
    const stem = assemblyWorkspacePath
      ? assemblyWorkspacePath.replace(/\.nass$/i, '').split('/').pop()
      : (getAssemblyName() ?? currentAssembly?.metadata?.name ?? 'assembly')
    const result = await openFileBrowser({
      title: 'Save Assembly As',
      mode: 'save',
      fileType: 'assembly',
      suggestedName: stem,
      suggestedExt: '.nass',
      api,
    })
    if (!result) return
    const r = await api.saveAssemblyAs(result.path, result.overwrite ?? false)
    if (r) {
      setAssemblyFileHandle(null)
      setAssemblyName(result.name)
      setAssemblyWorkspacePath(result.path)
      updateAssemblyTitle()
      libraryPanel?.refresh()
    }
  }

  return { getDesignContent, savePartToAssembly, saveToHandle, saveAs, saveAssemblyToHandle, saveAssemblyAs }
}

/**
 * Open-orchestration: load a part (.nadoc) or assembly (.nass) from the server
 * into the editor, driving the file-load overlay dialog through the fetch →
 * import → build pipeline.
 *
 * Extracted verbatim from main.js's "Library panel" region (the two
 * `_openPartFromServer` / `_openAssemblyFromServer` functions — Tier-5 carve-up,
 * extraction #59). Kept a SEPARATE factory from initFileIo (above) because the
 * open path's dependency surface is disjoint: it needs the file-load overlay
 * helpers, the lifecycle spine, and the one-shot assembly-load stash setters,
 * none of which the save-content ops touch. A second focused factory keeps each
 * test surface small and dodges reordering the locked initFileIo init.
 *
 * The lifecycle spine (resetForNewDesign / enterAssemblyMode), the file-load
 * overlay helpers (showFileLoad / flAppendLog / flSetProgress / flShowError /
 * flShowSuccess), and the mutable file/assembly state stay in main.js and flow
 * in as injected fns + setters so the lifted bodies stay verbatim.
 *
 * @param {object} deps
 * @param {object}   deps.store
 * @param {object}   deps.api
 * @param {Function} deps.showFileLoad     (header)
 * @param {Function} deps.flAppendLog      (msg, type?)
 * @param {Function} deps.flSetProgress    (pct, msg)
 * @param {Function} deps.flShowError      (msg)
 * @param {Function} deps.flShowSuccess    (msg) → Promise
 * @param {Function} deps.resetForNewDesign
 * @param {Function} deps.setFileName
 * @param {Function} deps.setWorkspacePath
 * @param {Function} deps.hideWelcome
 * @param {Function} deps.showWelcome
 * @param {Function} deps.revealWorkspaceForEmptyPart
 * @param {Function} deps.fitToView
 * @param {Function} deps.enterAssemblyMode
 * @param {Function} deps.setAssemblyWorkspacePath
 * @param {Function} deps.setAssemblyName
 * @param {Function} deps.setAssemblyFileHandle
 * @param {Function} deps.setAssemblyLoadOnProgress  (cb|null) — stash read by the assembly rebuild subscriber
 * @param {Function} deps.setAssemblyLoadSettle      ({resolve,reject}|null)
 * @returns {{openPartFromServer, openAssemblyFromServer}}
 */
export function initFileOpen({
  store, api,
  showFileLoad, flAppendLog, flSetProgress, flShowError, flShowSuccess,
  resetForNewDesign, setFileName, setWorkspacePath, hideWelcome, showWelcome,
  revealWorkspaceForEmptyPart, fitToView, enterAssemblyMode,
  setAssemblyWorkspacePath, setAssemblyName, setAssemblyFileHandle,
  setAssemblyLoadOnProgress, setAssemblyLoadSettle,
}) {
  async function openPartFromServer(path, name) {
    showFileLoad('Opening Part')
    flAppendLog(`Path: ${path}`)
    try {
      flSetProgress(0, 'Fetching file…')
      const result = await api.getLibraryFileContent(path)
      if (!result?.content) {
        flAppendLog('Server returned no content.', 'error')
        flShowError('Could not load part.')
        return
      }
      flAppendLog(`File fetched — ${Math.round(result.content.length / 1024)} KB`)
      flSetProgress(50, 'Importing design…')
      flAppendLog('Parsing and validating design…')
      resetForNewDesign()
      const ok = await api.importDesign(result.content)
      if (ok) {
        flAppendLog('Design imported successfully.', 'success')
        setFileName(name ?? path)
        setWorkspacePath(path)
        hideWelcome()
        revealWorkspaceForEmptyPart()
        fitToView()
        await flShowSuccess('Part loaded successfully')
      } else {
        const err = store.getState().lastError
        flAppendLog(`Import failed: ${err?.message ?? 'unknown error'}`, 'error')
        flShowError('Failed to import part.')
        showWelcome()
      }
    } catch (e) {
      flAppendLog(`Exception: ${e?.message ?? String(e)}`, 'error')
      flShowError('Could not load part.')
    }
  }

  async function openAssemblyFromServer(path) {
    showFileLoad('Opening Assembly')
    flAppendLog(`Path: ${path}`)
    let _hasInstanceErrors = false
    try {
      flSetProgress(0, 'Fetching file…')
      const result = await api.getLibraryFileContent(path)
      if (!result?.content) {
        flAppendLog('Server returned no content.', 'error')
        flShowError('Could not load assembly.')
        return
      }
      flAppendLog(`File fetched — ${Math.round(result.content.length / 1024)} KB`)
      flSetProgress(25, 'Importing assembly…')
      flAppendLog('Parsing and validating assembly…')

      // The geometry build is owned by the assembly subscriber (mode-enter for a
      // fresh open, the assemblyChanged branch for a reload while already in
      // assembly mode).  Stash a one-shot progress callback + completion promise
      // BEFORE importing so whichever branch fires drives THIS dialog and the
      // build happens exactly once — at cylinders, never the saved representation.
      // (Previously we ALSO built explicitly here, then the subscriber rebuilt
      // again: a full throwaway build at the saved rep — ~24 s for surface.)
      let _resolveBuilt, _rejectBuilt
      const built = new Promise((res, rej) => { _resolveBuilt = res; _rejectBuilt = rej })
      setAssemblyLoadOnProgress(({ stage, done, total, name, error }) => {
        if (stage === 'fetched') {
          flAppendLog('Geometry received from server')
          flSetProgress(55, 'Building parts…')
        } else if (stage === 'fetch_error') {
          flAppendLog('Geometry fetch failed — trying per-part fallback…', 'warn')
        } else if (stage === 'instance_built') {
          const pct = 55 + Math.round((done / total) * 45)
          flSetProgress(pct, `Part ${done} / ${total}`)
          flAppendLog(`  ✓ ${name ?? `Part ${done}`}`, 'success')
        } else if (stage === 'instance_error') {
          const pct = 55 + Math.round((done / total) * 45)
          flSetProgress(pct, `Part ${done} / ${total}`)
          flAppendLog(`  ✗ ${name ?? `Part ${done}`}: ${error}`, 'error')
          _hasInstanceErrors = true
        }
      })
      setAssemblyLoadSettle({ resolve: _resolveBuilt, reject: _rejectBuilt })

      const ok = await api.importAssembly(result.content)
      if (!ok) {
        setAssemblyLoadOnProgress(null)
        setAssemblyLoadSettle(null)
        const err = store.getState().lastError
        flAppendLog(`Import failed: ${err?.message ?? 'unknown error'}`, 'error')
        flShowError('Failed to import assembly.')
        return
      }

      const assembly = store.getState().currentAssembly
      const instances = assembly?.instances ?? []
      const visible   = instances.filter(i => i.visible !== false)
      flAppendLog(`Assembly parsed — ${visible.length} part${visible.length !== 1 ? 's' : ''}`, 'success')
      flSetProgress(40, `Loading ${visible.length} part${visible.length !== 1 ? 's' : ''}…`)

      setAssemblyName(path.replace(/\.nass$/i, ''))
      setAssemblyFileHandle(null)
      setAssemblyWorkspacePath(path)

      if (visible.length > 0) {
        flAppendLog('Fetching part geometry…')
      } else {
        // Nothing to build — release the stash so the subscriber's empty rebuild
        // doesn't leave us awaiting a promise nothing settles.
        setAssemblyLoadOnProgress(null)
        setAssemblyLoadSettle(null)
        _resolveBuilt()
      }

      // Enter assembly mode.  Fresh open: this flips assemblyActive → the
      // mode-enter branch builds (consuming the stash + framing the camera).
      // Reload while already in assembly mode: the build already fired from the
      // import above; this is a no-op for the build.
      enterAssemblyMode()

      try {
        await built
      } catch (e) {
        _hasInstanceErrors = true
        flAppendLog(`Build failed: ${e?.message ?? String(e)}`, 'error')
      }

      if (_hasInstanceErrors) {
        flAppendLog('Assembly loaded with errors.', 'warn')
        flShowError('Some parts failed to load.')
      } else {
        flAppendLog('All parts loaded successfully.', 'success')
        await flShowSuccess('Assembly loaded successfully')
      }
    } catch (e) {
      setAssemblyLoadOnProgress(null)
      setAssemblyLoadSettle(null)
      flAppendLog(`Exception: ${e?.message ?? String(e)}`, 'error')
      flShowError('Could not load assembly.')
    }
  }

  return { openPartFromServer, openAssemblyFromServer }
}
