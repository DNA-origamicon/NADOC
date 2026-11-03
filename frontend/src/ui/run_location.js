/** Engine-specific run locations and directory picker. */
import { pickSystemFolder } from './folder_picker.js'
import { showChoice } from './primitives/choice.js'
import { formatBytes } from './format_bytes.js'
import { createButton } from './primitives/button.js'

import { getRunDir, setRunDir, RUN_DIR_EVENT as _EVT } from './run_location_preferences.js'
export { getRunDir, setRunDir } from './run_location_preferences.js'

/** Short display label for a run directory (its last path component). */
export function runDirLabel(dir) {
  if (!dir) return 'Default folder'
  const parts = String(dir).replace(/\/+$/, '').split('/')
  return parts[parts.length - 1] || String(dir)
}

/** From a backend disk forecast, the archive recommendation (pure).
 *  → { show:false } | { show:true, path, freeBytes }. */
export function archiveRecommendation(forecast) {
  const s = forecast && forecast.suggested_archive
  if (!forecast || !forecast.warn || !s || !s.path) return { show: false }
  return { show: true, path: s.path, freeBytes: Number(s.free_bytes) || 0 }
}

/** If the forecast recommends a roomier drive, offer to archive the run there. Resolves:
 *    { proceed:true,  runDir:<suggested> }  — run on the roomier drive (sets this engine’s dir),
 *    { proceed:true,  runDir:<current> }    — run on the current target anyway,
 *    { proceed:false }                      — cancel.
 *  No recommendation → { proceed:true, runDir:getRunDir(engine) } without a dialog (the caller still
 *  runs its normal low-disk Continue/Cancel confirm). */
export async function recommendArchive(forecast, engine = 'namd') {
  const rec = archiveRecommendation(forecast)
  if (!rec.show) return { proceed: true, runDir: getRunDir(engine) }
  const choice = await showChoice({
    title: 'Low disk space for this run',
    message: `This run may not fit on the target drive. ${rec.path} has `
           + `${formatBytes(rec.freeBytes)} free — store the run there instead?`,
    options: [
      { label: `Store in “${runDirLabel(rec.path)}” & run there`, value: 'archive',
        variant: 'primary', tooltip: rec.path },
      { label: 'Run here anyway', value: 'here', variant: 'ghost' },
    ],
    cancelLabel: 'Cancel',
  })
  if (choice === 'archive') return { proceed: true, runDir: setRunDir(rec.path, engine) }
  if (choice === 'here') return { proceed: true, runDir: getRunDir(engine) }
  return { proceed: false }
}

/** Mount the "📁 Directory" button into `container` (place it above the jobs list).
 *  Left-click opens the server-side folder browser; right-click resets to the default. The
 *  label stays in sync with this engine’s preference (across the app) via the change event. */
export function mountDirectoryButton(container, { api, engine: initialEngine = 'namd' } = {}) {
  if (!container) return null
  let engine = initialEngine
  let checkSeq = 0
  let status = null
  const btn = createButton({
    label: `📁 ${runDirLabel(getRunDir(engine))} · checking…`,
    variant: 'ghost',
    title: 'Folder that new runs for this engine write into — point large trajectories at a roomy '
         + 'drive to keep them off a full system disk. Right-click to reset to the default.',
    onClick: async () => {
      const pickedEngine = engine
      const picked = await pickSystemFolder({
        api, title: `Choose a folder for ${pickedEngine} runs`, initialPath: getRunDir(pickedEngine) })
      if (picked) setRunDir(picked, pickedEngine)
    },
  })
  btn.style.width = '100%'
  btn.addEventListener('contextmenu', (e) => { e.preventDefault(); setRunDir(null, engine) })
  const render = ({ checking = false } = {}) => {
    const chosen = getRunDir(engine)
    const shownPath = chosen || status?.path || null
    const label = runDirLabel(shownPath)
    btn.textContent = `📁 ${label}${checking ? ' · checking…' : status?.ok === false ? ' ⚠' : ''}`
    btn.dataset.runDirState = checking ? 'checking' : status?.ok === false ? 'error' : 'ok'
    btn.style.borderColor = status?.ok === false ? '#f85149' : ''
    btn.style.color = status?.ok === false ? '#f85149' : ''
    btn.title = status?.ok === false
      ? `${status.detail || 'This folder is unavailable.'}\n${status.path || chosen || ''}`
      : `Folder that new ${engine} runs write into: ${shownPath || 'NADOC workspace default'}. `
        + 'Right-click to reset to the default.'
  }
  const sync = async () => {
    const seq = ++checkSeq
    status = null
    render({ checking: !!api?.getMdRunDirStatus })
    if (!api?.getMdRunDirStatus) { render(); return }
    try {
      const next = await api.getMdRunDirStatus(getRunDir(engine), engine)
      if (seq !== checkSeq) return
      status = next || {
        ok: false, path: getRunDir(engine), detail: 'Could not check this folder.' }
    } catch (err) {
      if (seq !== checkSeq) return
      status = {
        ok: false, path: getRunDir(engine),
        detail: `Could not check this folder: ${err?.message || err}`,
      }
    }
    render()
  }
  try { window.addEventListener(_EVT, sync) } catch { /* no window (tests) */ }
  btn.setEngine = next => {
    if (!next || next === engine) return
    engine = next
    void sync()
  }
  container.appendChild(btn)
  let initiallyChecked = false
  const checkWhenVisible = () => {
    const pane = document.getElementById('tab-content-dynamics')
    if (initiallyChecked || pane?.hidden) return
    initiallyChecked = true
    void sync()
  }
  window.addEventListener('nadoc:left-tab-change', checkWhenVisible)
  render()
  checkWhenVisible()
  return btn
}
