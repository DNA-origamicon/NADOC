/**
 * Export menu handlers for current, supported interchange formats.
 *
 * A flat cluster of sibling click handlers: each wires one menu item to an
 * export action (an `api.*` call that streams a download, or a direct
 * `<a download>` hit against a backend URL) and surfaces success/failure as a
 * toast. No shared state beyond `store` (to guard "no design loaded") and
 * `api`; everything else (`showToast`, `getStapleColorOrder`) is
 * a module import, so the factory only needs those two deps.
 *
 * @param {object} deps
 * @param {object} deps.store — getState() → { currentDesign, lastError }
 * @param {object} deps.api   — exportSequenceCsv / exportSequenceXlsx /
 *                              exportCadnano / exportSurfaceStl / exportSurface3mf
 * @returns {object}
 */
import { showToast, showPersistentToast, dismissToast } from './toast.js'
import { getStapleColorOrder } from './spreadsheet.js'
import { buildIdtStrandNames } from './idt_order.js'

/** Last backend error message, or 'unknown'. Pure (reads a plain state object). */
export function exportErrorMessage(state) {
  return state?.lastError?.message ?? 'unknown'
}

/** Ask which coordinate set to export. Resolves to 'native', 'visualized', or null. */
export function showPdbPositionModal(visualizationName, trajectory = null, coloring = null) {
  return new Promise(resolve => {
    const overlay = document.createElement('div')
    overlay.className = 'modal-overlay'
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10001;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;padding:24px'
    const box = document.createElement('div')
    box.style.cssText = 'width:min(520px,100%);background:#1a2530;border:1px solid #455a64;border-radius:10px;padding:22px;color:#cfd8dc;font-family:sans-serif;box-shadow:0 12px 48px rgba(0,0,0,.7)'
    const title = document.createElement('h2')
    title.textContent = 'Export PDB positions'
    title.style.cssText = 'font-size:17px;margin:0 0 10px;color:#eceff1'
    const text = document.createElement('p')
    text.textContent = trajectory
      ? `Export frame ${trajectory.frame} of ${trajectory.total} from the ${visualizationName} view?`
      : `${visualizationName} is currently displayed. Which positions should the PDB use?`
    text.style.cssText = 'font-size:13px;line-height:1.5;margin:0 0 20px'
    let colorCheck = null
    const colorRow = document.createElement('label')
    if (coloring?.values?.length) {
      colorRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin:-8px 0 18px;font-size:13px;cursor:pointer'
      colorCheck = document.createElement('input')
      colorCheck.type = 'checkbox'; colorCheck.checked = true
      const label = document.createElement('span')
      label.textContent = `Include current ${coloring.title || 'simulation'} coloring (ChimeraX B-factor)`
      colorRow.append(colorCheck, label)
    }
    const buttons = document.createElement('div')
    buttons.style.cssText = 'display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap'
    const finish = value => {
      overlay.remove()
      resolve(colorCheck && value != null
        ? { choice: value, includeColoring: colorCheck.checked }
        : value)
    }
    for (const [label, value, primary] of [
      ['Cancel', null, false],
      ['Native NADOC positions', 'native', false],
      [trajectory ? `Export frame ${trajectory.frame} of ${trajectory.total}` : `${visualizationName} positions`, 'visualized', true],
    ]) {
      const button = document.createElement('button')
      button.textContent = label
      button.style.cssText = `padding:8px 14px;border-radius:5px;cursor:pointer;color:#fff;border:1px solid ${primary ? '#0288d1' : '#546e7a'};background:${primary ? '#0288d1' : '#263238'}`
      button.addEventListener('click', () => finish(value))
      buttons.appendChild(button)
    }
    overlay.addEventListener('click', e => { if (e.target === overlay) finish(null) })
    box.append(title, text)
    if (colorCheck) box.appendChild(colorRow)
    box.appendChild(buttons); overlay.appendChild(box); document.body.appendChild(overlay)
  })
}

export function initExportMenu({ store, api, getPdbVisualization = () => null }) {
  let pdbExportBusy = false
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

  // ── Export IDT plate/tube order workbook ──────────────────────────────────────
  document.getElementById('menu-file-export-idt-xlsx')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    const state = store.getState()
    const names = buildIdtStrandNames(
      state.currentDesign, state.strandGroups, state.currentDesign.plate_layout,
    )
    const ok = await api.exportIdtOrderXlsx(names)
    if (!ok) showToast('Export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  // ── Export caDNAno (.json) ─────────────────────────────────────────────────────
  document.getElementById('menu-file-export-cadnano')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    const ok = await api.exportCadnano()
    if (!ok) showToast('Export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  document.getElementById('menu-file-export-scadnano')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    const ok = await api.exportScadnano()
    if (!ok) showToast('scadnano export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  // ── Export PDB ─────────────────────────────────────────────────────────────────
  document.getElementById('menu-file-export-pdb')?.addEventListener('click', async () => {
    if (!haveDesign() || pdbExportBusy) return
    const visualization = getPdbVisualization()
    let positions = null
    if (visualization?.positions?.length) {
      const result = await showPdbPositionModal(visualization.name, visualization.trajectory, visualization.coloring)
      if (result === null) return
      const choice = typeof result === 'object' ? result.choice : result
      if (choice === 'visualized') positions = visualization.positions
      if (typeof result === 'object' && !result.includeColoring) visualization.coloring = null
    }
    pdbExportBusy = true
    showPersistentToast('Generating PDB…', { severity: 'info', loading: true })
    let ok = false
    try {
      ok = await api.exportPdb(positions, visualization)
    } catch (_) {
      ok = false
    } finally {
      pdbExportBusy = false
      dismissToast()
    }
    if (ok) showToast('PDB generated. Download starting…', { severity: 'success' })
    else showToast('PDB export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
  })

  // ── Export PSF for NAMD ────────────────────────────────────────────────────────
  document.getElementById('menu-file-export-psf')?.addEventListener('click', async () => {
    if (!haveDesign()) return
    const ok = await api.exportPsf()
    if (!ok) showToast('PSF export failed: ' + exportErrorMessage(store.getState()), { severity: 'error' })
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

  return {}
}
