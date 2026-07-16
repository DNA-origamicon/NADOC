/**
 * Run-location — choose a directory to write a (large) NAMD run into, remember it, and when
 * the disk forecast says the run won't fit, recommend archiving to a roomier drive and
 * running there.
 *
 * A NAMD run writes multi-GB trajectories; pointing it at a spacious volume (e.g. an external
 * Archive drive) keeps them off a full system disk — the run reads/writes from Archive fine
 * (the GPU is the bottleneck, not the periodic disk flushes). Backed by the existing
 * server-side folder browser (`pickSystemFolder` / routes_fs) and the backend disk forecast's
 * `suggested_archive` field.
 *
 * `initRunLocation({ api, storage })` → { getRunDir, setDir, clear, mountButton, recommendArchive }
 * The chosen directory is remembered in localStorage so the next run defaults to it.
 * Pure cores (`runDirLabel`, `archiveRecommendation`) are exported for tests.
 */
import { pickSystemFolder } from './folder_picker.js'
import { showChoice } from './primitives/choice.js'
import { formatBytes } from './format_bytes.js'
import { createButton } from './primitives/button.js'

const _STORE_KEY = 'nadoc.md.runDir'

/** Short display label for a run directory (its last path component). */
export function runDirLabel(dir) {
  if (!dir) return 'Default (workspace)'
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

export function initRunLocation({ api, storage } = {}) {
  const store = storage ?? (typeof localStorage !== 'undefined' ? localStorage : null)
  let _dir = null
  try { _dir = store?.getItem(_STORE_KEY) || null } catch { _dir = null }

  const getRunDir = () => _dir || null
  const setDir = (dir) => {
    _dir = dir || null
    try {
      if (_dir) store?.setItem(_STORE_KEY, _dir)
      else store?.removeItem(_STORE_KEY)
    } catch { /* private-mode / quota — the in-memory value still holds for this session */ }
  }
  const clear = () => setDir(null)

  /** Render a "Directory" button into `container`. Left-click opens the folder browser;
   *  right-click resets to the default. `onChange(dir)` fires after either. */
  function mountButton(container, onChange = () => {}) {
    const btn = createButton({
      label: `📁 ${runDirLabel(_dir)}`,
      variant: 'ghost',
      title: 'Choose the folder this run writes into (large trajectories go here). '
           + 'Right-click to reset to the default workspace location.',
      onClick: async () => {
        const picked = await pickSystemFolder({
          api, title: 'Choose a folder for this run', initialPath: _dir })
        if (picked) { setDir(picked); btn.textContent = `📁 ${runDirLabel(picked)}`; onChange(picked) }
      },
    })
    btn.addEventListener('contextmenu', (e) => {
      e.preventDefault(); clear(); btn.textContent = `📁 ${runDirLabel(null)}`; onChange(null)
    })
    container.appendChild(btn)
    return btn
  }

  /** If the forecast recommends a roomier drive, offer it. Resolves:
   *    { proceed:true,  runDir:<suggested> }  — the user chose to run on the roomier drive,
   *    { proceed:true,  runDir:<current> }    — run on the current target anyway,
   *    { proceed:false }                      — cancel.
   *  When there is NO recommendation, resolves { proceed:true, runDir:getRunDir() } without a
   *  dialog (the caller still runs its normal low-disk Continue/Cancel confirm). */
  async function recommendArchive(forecast) {
    const rec = archiveRecommendation(forecast)
    if (!rec.show) return { proceed: true, runDir: getRunDir() }
    const choice = await showChoice({
      title: 'Low disk space for this run',
      message: `This run may not fit on the target drive. ${rec.path} has `
             + `${formatBytes(rec.freeBytes)} free — archive the run there and write to it instead?`,
      options: [
        { label: `Archive to “${runDirLabel(rec.path)}” & run there`, value: 'archive',
          variant: 'primary', tooltip: rec.path },
        { label: 'Run here anyway', value: 'here', variant: 'ghost' },
      ],
      cancelLabel: 'Cancel',
    })
    if (choice === 'archive') { setDir(rec.path); return { proceed: true, runDir: rec.path } }
    if (choice === 'here') return { proceed: true, runDir: getRunDir() }
    return { proceed: false }
  }

  return { getRunDir, setDir, clear, mountButton, recommendArchive }
}
