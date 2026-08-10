/**
 * Run-location — one shared "📁 Directory" control (above the jobs list, universal for every
 * engine) that chooses where new runs write, and a low-disk recommendation to move to a
 * roomier drive and run there.
 *
 * A simulation run can write multi-GB trajectories; pointing it at a spacious volume (e.g. an
 * external drive) keeps them off a full system disk — simulations read/write there normally
 * fine (the GPU is the bottleneck, not the periodic flushes). The chosen folder is a SINGLE
 * preference in localStorage, so it applies to whichever engine you launch; every engine's
 * create reads `getRunDir()`. Backed by the existing server-side folder browser
 * (`pickSystemFolder` / routes_fs) and the backend disk forecast's `suggested_archive`.
 *
 * Standalone helpers (getRunDir/setRunDir/runDirLabel/archiveRecommendation/recommendArchive)
 * are the shared preference API; `mountDirectoryButton(container, { api })` renders the one
 * button and keeps its label in sync across the app via a change event.
 */
import { pickSystemFolder } from './folder_picker.js'
import { showChoice } from './primitives/choice.js'
import { formatBytes } from './format_bytes.js'
import { createButton } from './primitives/button.js'

const _STORE_KEY = 'nadoc.runDir'          // engine-neutral: ONE run-location for all engines
const _EVT = 'nadoc:run-dir-change'

/** The current shared run directory (or null = default workspace). Read fresh each call so
 *  every engine + the button reflect the latest choice. */
export function getRunDir() {
  try {
    return (typeof localStorage !== 'undefined' && localStorage.getItem(_STORE_KEY)) || null
  } catch { return null }
}

/** Set the shared run directory (null clears it) and notify any mounted button. Returns it. */
export function setRunDir(dir) {
  const v = dir || null
  try {
    if (typeof localStorage !== 'undefined') {
      if (v) localStorage.setItem(_STORE_KEY, v)
      else localStorage.removeItem(_STORE_KEY)
    }
  } catch { /* private-mode / quota — ignore; nothing else to fall back to */ }
  try { window.dispatchEvent(new CustomEvent(_EVT, { detail: v })) } catch { /* no window (tests) */ }
  return v
}

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
 *    { proceed:true,  runDir:<suggested> }  — run on the roomier drive (sets the shared dir),
 *    { proceed:true,  runDir:<current> }    — run on the current target anyway,
 *    { proceed:false }                      — cancel.
 *  No recommendation → { proceed:true, runDir:getRunDir() } without a dialog (the caller still
 *  runs its normal low-disk Continue/Cancel confirm). */
export async function recommendArchive(forecast) {
  const rec = archiveRecommendation(forecast)
  if (!rec.show) return { proceed: true, runDir: getRunDir() }
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
  if (choice === 'archive') return { proceed: true, runDir: setRunDir(rec.path) }
  if (choice === 'here') return { proceed: true, runDir: getRunDir() }
  return { proceed: false }
}

/** Mount the ONE shared "📁 Directory" button into `container` (place it above the jobs list).
 *  Left-click opens the server-side folder browser; right-click resets to the default. The
 *  label stays in sync with the shared preference (across the app) via the change event. */
export function mountDirectoryButton(container, { api } = {}) {
  if (!container) return null
  const btn = createButton({
    label: `📁 ${runDirLabel(getRunDir())}`,
    variant: 'ghost',
    title: 'Folder that new runs (any engine) write into — point large trajectories at a roomy '
         + 'drive to keep them off a full system disk. Right-click to reset to the default.',
    onClick: async () => {
      const picked = await pickSystemFolder({
        api, title: 'Choose a folder for runs', initialPath: getRunDir() })
      if (picked) setRunDir(picked)
    },
  })
  btn.style.width = '100%'
  btn.addEventListener('contextmenu', (e) => { e.preventDefault(); setRunDir(null) })
  const sync = () => { btn.textContent = `📁 ${runDirLabel(getRunDir())}` }
  try { window.addEventListener(_EVT, sync) } catch { /* no window (tests) */ }
  container.appendChild(btn)
  sync()
  return btn
}
