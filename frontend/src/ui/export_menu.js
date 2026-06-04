/**
 * Export menu — the File → Export submenu handlers.
 *
 * A flat cluster of sibling click handlers: each wires one menu item to an
 * export action (an `api.*` call that streams a download, or a direct
 * `<a download>` hit against a backend URL) and surfaces success/failure as a
 * toast. No shared state beyond `store` (to guard "no design loaded") and
 * `api`; everything else (`showToast`, `docHeaders`, `getStapleColorOrder`) is
 * a module import, so the factory only needs those two deps.
 *
 * Extracted verbatim from main.js's `// ── Export Sequences (CSV)` …
 * `// ── Export GROMACS complete package` block. GROMACS export itself is a
 * stub (the modal+poller was removed 2026-05-17, see the inline note); the
 * menu item shows a "being re-worked" toast.
 *
 * @param {object} deps
 * @param {object} deps.store — getState() → { currentDesign, lastError }
 * @param {object} deps.api   — exportSequenceCsv / exportSequenceXlsx /
 *                              exportCadnano / exportSurfaceStl / exportSurface3mf
 * @returns {{ showNamdPromptModal: Function }}
 */
import { showToast } from './toast.js'
import { docHeaders } from '../shared/doc_id.js'
import { getStapleColorOrder } from './spreadsheet.js'

/** Last backend error message, or 'unknown'. Pure (reads a plain state object). */
export function exportErrorMessage(state) {
  return state?.lastError?.message ?? 'unknown'
}

/** Trigger a browser download of a backend export URL via a transient `<a>`. */
export function triggerDownload(url) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  a.click()
}

/**
 * Build + show the NAMD "AI Assistant Prompt" modal over the page, prefilled
 * with `promptText`. Copy-to-clipboard + close (✕ / Close / backdrop click).
 * Returns the cleanup function (also wired to the close affordances).
 */
export function showNamdPromptModal(promptText) {
  // ── Modal ──────────────────────────────────────────────────────────────────
  const overlay = document.createElement('div')
  overlay.style.cssText = [
    'position:fixed', 'inset:0', 'z-index:10001',
    'background:rgba(0,0,0,0.65)',
    'display:flex', 'align-items:center', 'justify-content:center',
    'padding:24px', 'box-sizing:border-box',
  ].join(';')

  const box = document.createElement('div')
  box.style.cssText = [
    'background:#1a2530', 'border:1px solid #37474f',
    'border-radius:10px', 'padding:0',
    'width:min(740px,100%)', 'max-height:85vh',
    'display:flex', 'flex-direction:column',
    'font-family:sans-serif', 'color:#cfd8dc',
    'box-shadow:0 12px 48px rgba(0,0,0,0.7)',
  ].join(';')

  const header = document.createElement('div')
  header.style.cssText = [
    'padding:18px 22px 14px', 'border-bottom:1px solid #263238',
    'display:flex', 'align-items:flex-start', 'gap:12px',
  ].join(';')

  const headerText = document.createElement('div')
  headerText.style.cssText = 'flex:1'

  const title = document.createElement('div')
  title.textContent = 'AI Assistant Prompt'
  title.style.cssText = 'font-size:15px;font-weight:700;color:#eceff1;margin-bottom:4px'

  const subtitle = document.createElement('div')
  subtitle.textContent = 'Paste into VS Code Copilot Chat, Claude, ChatGPT, or any LLM for step-by-step simulation guidance. Also included as AI_ASSISTANT_PROMPT.txt inside the ZIP.'
  subtitle.style.cssText = 'font-size:12px;color:#78909c;line-height:1.45'

  headerText.append(title, subtitle)

  const btnClose = document.createElement('button')
  btnClose.textContent = '✕'
  btnClose.style.cssText = [
    'background:none', 'border:none', 'color:#78909c',
    'font-size:18px', 'cursor:pointer', 'padding:0 2px',
    'line-height:1', 'flex-shrink:0', 'margin-top:1px',
  ].join(';')

  header.append(headerText, btnClose)

  const pre = document.createElement('textarea')
  pre.readOnly = true
  pre.value = promptText
  pre.style.cssText = [
    'flex:1', 'overflow:auto', 'margin:0',
    'padding:16px 20px', 'background:#111c24',
    'border:none', 'border-radius:0',
    'color:#b0bec5', 'font-family:"Cascadia Code","Fira Mono",monospace',
    'font-size:11.5px', 'line-height:1.6',
    'resize:none', 'outline:none',
    'white-space:pre', 'min-height:0',
  ].join(';')

  const footer = document.createElement('div')
  footer.style.cssText = [
    'padding:12px 22px', 'border-top:1px solid #263238',
    'display:flex', 'justify-content:flex-end', 'gap:10px',
  ].join(';')

  const btnCopy = document.createElement('button')
  btnCopy.textContent = 'Copy to Clipboard'
  btnCopy.style.cssText = [
    'padding:8px 20px', 'border-radius:5px', 'border:none',
    'background:#0288d1', 'color:#fff', 'cursor:pointer',
    'font-size:13px', 'font-weight:600',
  ].join(';')

  const btnDone = document.createElement('button')
  btnDone.textContent = 'Close'
  btnDone.style.cssText = [
    'padding:8px 18px', 'border-radius:5px',
    'border:1px solid #455a64',
    'background:#263238', 'color:#b0bec5',
    'cursor:pointer', 'font-size:13px',
  ].join(';')

  const cleanup = () => document.body.removeChild(overlay)

  btnCopy.addEventListener('click', async () => {
    await navigator.clipboard.writeText(promptText).catch(() => {
      pre.select()
      document.execCommand('copy')
    })
    btnCopy.textContent = 'Copied!'
    setTimeout(() => { btnCopy.textContent = 'Copy to Clipboard' }, 2000)
  })
  btnClose.addEventListener('click', cleanup)
  btnDone.addEventListener('click', cleanup)
  overlay.addEventListener('click', e => { if (e.target === overlay) cleanup() })

  footer.append(btnCopy, btnDone)
  box.append(header, pre, footer)
  overlay.appendChild(box)
  document.body.appendChild(overlay)
  pre.focus()
  return cleanup
}

export function initExportMenu({ store, api }) {
  // Shared guard: every export needs a design loaded. Returns true if OK.
  const haveDesign = () => {
    if (!store.getState().currentDesign) {
      showToast('No design loaded.', { severity: 'error' })
      return false
    }
    return true
  }

  // ── Export Sequences (CSV) ─────────────────────────────────────────────────────
  document.getElementById('menu-file-export-seq-csv')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    const ok = await api.exportSequenceCsv()
    if (!ok) showToast('Export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  // ── Export Sequences (Excel, overhang bold) ────────────────────────────────────
  document.getElementById('menu-file-export-seq-xlsx')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    const { strandColors, strandOrder } = getStapleColorOrder(store.getState())
    const ok = await api.exportSequenceXlsx(strandColors, strandOrder)
    if (!ok) showToast('Export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  // ── Export caDNAno (.json) ─────────────────────────────────────────────────────
  document.getElementById('menu-file-export-cadnano')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    const ok = await api.exportCadnano()
    if (!ok) showToast('Export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  // ── Export PDB for NAMD ────────────────────────────────────────────────────────
  document.getElementById('menu-file-export-pdb')?.addEventListener('click', () => {
    if (!haveDesign()) return
    triggerDownload('/api/design/export/pdb')
  })

  // ── Export PSF for NAMD ────────────────────────────────────────────────────────
  document.getElementById('menu-file-export-psf')?.addEventListener('click', () => {
    if (!haveDesign()) return
    triggerDownload('/api/design/export/psf')
  })

  // ── Export Surface STL (3D print) ──────────────────────────────────────────────
  document.getElementById('menu-file-export-stl')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    showToast('Building surface STL…', { severity: 'info' })
    const ok = await api.exportSurfaceStl()
    if (ok) showToast('Surface STL exported (auto-scaled to 200 mm).', { severity: 'success' })
    else showToast('STL export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  // ── Export Surface 3MF (multi-color print) ──────────────────────────────────────
  document.getElementById('menu-file-export-3mf')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    showToast('Building multi-color 3MF…', { severity: 'info' })
    const res = await api.exportSurface3mf()
    if (res && res.ok) {
      const detail = res.coloring ? ` (${res.coloring})` : ''
      showToast('Surface 3MF exported: scaffold + 3 staple colors, 200 mm' + detail + '.', { severity: 'success' })
    } else {
      showToast('3MF export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
    }
  })

  // ── Export NAMD complete package ──────────────────────────────────────────────
  document.getElementById('menu-file-export-namd-complete')?.addEventListener('click', async () => {
    if (!haveDesign()) return

    // Trigger the download immediately — don't make the user wait for the prompt fetch.
    triggerDownload('/api/design/export/namd-complete')

    // Fetch and display the AI assistant prompt in a popup.
    let promptText = null
    try {
      const r = await fetch('/api/design/export/namd-prompt', { headers: docHeaders() })
      if (r.ok) promptText = await r.text()
    } catch (_) { /* non-fatal */ }
    if (!promptText) return

    showNamdPromptModal(promptText)
  })

  // ── Export GROMACS complete package (background job) ─────────────────────────
  {
    const toast   = document.getElementById('gromacs-job-toast')
    const label   = document.getElementById('gromacs-job-label')
    const dlBtn   = document.getElementById('gromacs-job-download')
    const dismiss = document.getElementById('gromacs-job-dismiss')

    dismiss?.addEventListener('click', () => { toast.className = '' })

    // ── GROMACS export dialog — REMOVED 2026-05-17 ───────────────────────────
    // The original migration to createModal left the body div un-hidden at
    // module-init time, so it leaked into the main page above the canvas.
    // The whole feature (modal body + handler + job poller) is stubbed out
    // until it's re-implemented with the proper lazy-build pattern matching
    // the other migrated modals. Menu item now shows a "not available" toast.
    //
    // TODO(gromacs): Re-add `<div id="gromacs-export-modal-body" hidden>` to
    // index.html with the package-name / positions / NVT-steps / oxDNA-CG /
    // disabled-solvate form. Rebuild `_buildGmxModalOnce()` (lazy createModal,
    // unhide inside the build function — NOT at IIFE init), `_onGmxExport()`
    // with the fetch + poll loop against `/api/design/export/gromacs-start`
    // and `/gromacs-cg-start`. See git history for the prior implementation.
    // (`label`/`dlBtn` above are retained for that re-implementation; unused now.)
    document.getElementById('menu-file-export-gromacs-complete')?.addEventListener('click', () => {
      showToast('GROMACS export is being re-worked — try again after the next deploy.', { severity: 'error' })
    })
  }

  return { showNamdPromptModal }
}
