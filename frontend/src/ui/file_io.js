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
