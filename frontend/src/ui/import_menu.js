/**
 * Import menu — the File → Import handlers plus the Library-panel import
 * callbacks (caDNAno / scadnano with cluster+overhang autodetection, and PDB).
 *
 * More coupled than the Export submenu: importing creates a fresh design, so
 * these flows touch the file/welcome/workspace lifecycle. Rather than the global
 * `store`/`api` only, the factory takes the lifecycle helpers it calls
 * (`resetForNewDesign` / `show`+`hideWelcome` / `renderRecentMenu` /
 * `setWorkspacePath` / `setFileName` / `setSyncStatus` / `saveAs` /
 * `setFileHandle`) plus the already-built `libraryPanel`.
 * `showToast` / `openFileBrowser` / `openImportPdbModal` are module imports.
 *
 * Returns the two autodetection callbacks + `runPdbImport` so the (earlier)
 * `initLibraryPanel` call can reference them via a lazy wrapper, and so
 * `runPdbImport` (the testable, file-input-free branch logic) is unit-testable.
 *
 * Extracted verbatim from main.js's `// ── Import helpers` … `// ── Import PDB`
 * block.
 */
import { showToast } from './toast.js'
import { openFileBrowser } from './file_browser.js'
import { openImportPdbModal } from './import_pdb_modal.js'

/** Sanitize an imported design name to the filename-safe charset (pure). */
export function sanitizeImportName(raw) {
  return String(raw ?? '').replace(/[^a-zA-Z0-9-_ ]/g, '_')
}

/**
 * Pull the non-default clusters + overhangs out of a freshly-imported design —
 * the inputs to the Save-dialog autodetection prompt. Pure.
 */
export function importedClusterOverhangExtras(design) {
  const clusters = (design?.cluster_transforms ?? []).filter(c => !c.is_default)
  const overhangs = design?.overhangs ?? []
  return { clusters, overhangs }
}

export function initImportMenu(deps) {
  const {
    store, api, libraryPanel,
    resetForNewDesign, showWelcome, hideWelcome, renderRecentMenu,
    setWorkspacePath, setFileName, setSyncStatus, saveAs, setFileHandle,
  } = deps

  // Prompt Save As for an already-imported design, then add it as an assembly part.
  async function importAsAssemblyPart(suggestedName) {
    const saveResult = await openFileBrowser({
      title: 'Save New Part As',
      mode: 'save',
      fileType: 'part',
      suggestedName,
      suggestedExt: '.nadoc',
      api,
    })
    if (!saveResult) {
      store.setState({ currentDesign: null })
      return
    }
    const saved = await api.saveDesignAs(saveResult.path, saveResult.overwrite ?? false)
    if (!saved) { showToast('Failed to save part.', { severity: 'error' }); store.setState({ currentDesign: null }); return }
    store.setState({ currentDesign: null })
    await api.addInstance({ source: { type: 'file', path: saveResult.path }, name: saveResult.name.replace(/\.nadoc$/i, '') })
    libraryPanel?.refresh()
    showToast(`Part "${saveResult.name}" added to assembly.`)
  }

  // ── Library panel import callbacks (cadnano / scadnano with autodetection) ──────

  async function importCadnanoWithAutodetection() {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.json'
    const file = await new Promise(r => { input.onchange = () => r(input.files?.[0] ?? null); input.click() })
    if (!file) return
    const content = await file.text()
    resetForNewDesign()
    const result = await api.importCadnanoDesign(content)
    if (!result) {
      showToast('Failed to import caDNAno file: ' + (store.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' })
      if (!store.getState().assemblyActive) showWelcome()
      return
    }
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
    showToast('Note: caDNAno designs appear upside down due to the original caDNAno coordinate convention.', 8000)
    api.addRecentFile(file.name, content, 'cadnano')
    renderRecentMenu()

    const design = store.getState().currentDesign
    const { clusters, overhangs } = importedClusterOverhangExtras(design)
    const suggestedName = sanitizeImportName(design?.metadata?.name ?? file.name.replace(/\.[^.]+$/, ''))

    hideWelcome()

    const dest = await openFileBrowser({
      title: 'Save Imported Design',
      mode: 'save', fileType: 'part',
      suggestedName, suggestedExt: '.nadoc', api,
      autodetection: (clusters.length || overhangs.length) ? { clusters, overhangs } : null,
    })
    if (!dest) return

    if (dest.includeClusters === false && clusters.length) {
      for (const cl of clusters) await api.deleteCluster(cl.id)
    }
    if (dest.includeOverhangs === false && overhangs.length) {
      await api.clearOverhangs()
    }

    const r = await api.saveDesignAs(dest.path, dest.overwrite ?? false)
    if (r) {
      setFileHandle(null)
      setWorkspacePath(dest.path)
      setFileName(dest.name)
      setSyncStatus('green', 'saved')
      libraryPanel?.refresh()
    }
  }

  async function importScadnanoWithAutodetection() {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.sc'
    const file = await new Promise(r => { input.onchange = () => r(input.files?.[0] ?? null); input.click() })
    if (!file) return
    const content = await file.text()
    const baseName = file.name.replace(/\.sc$/i, '')
    resetForNewDesign()
    const result = await api.importScadnanoDesign(content, baseName)
    if (!result) {
      showToast('Failed to import scadnano file: ' + (store.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' })
      if (!store.getState().assemblyActive) showWelcome()
      return
    }
    if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
    showToast('Note: scadnano designs appear upside down due to the original scadnano coordinate convention.', 8000)
    api.addRecentFile(file.name, content, 'scadnano')
    renderRecentMenu()

    const design = store.getState().currentDesign
    const { clusters, overhangs } = importedClusterOverhangExtras(design)
    const suggestedName = sanitizeImportName(design?.metadata?.name ?? baseName)

    hideWelcome()

    const dest = await openFileBrowser({
      title: 'Save Imported Design',
      mode: 'save', fileType: 'part',
      suggestedName, suggestedExt: '.nadoc', api,
      autodetection: (clusters.length || overhangs.length) ? { clusters, overhangs } : null,
    })
    if (!dest) return

    if (dest.includeClusters === false && clusters.length) {
      for (const cl of clusters) await api.deleteCluster(cl.id)
    }
    if (dest.includeOverhangs === false && overhangs.length) {
      await api.clearOverhangs()
    }

    const r = await api.saveDesignAs(dest.path, dest.overwrite ?? false)
    if (r) {
      setFileHandle(null)
      setWorkspacePath(dest.path)
      setFileName(dest.name)
      setSyncStatus('green', 'saved')
      libraryPanel?.refresh()
    }
  }

  // ── Import caDNAno ─────────────────────────────────────────────────────────────
  document.getElementById('menu-file-import-cadnano')?.addEventListener('click', () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const content = await file.text()
      resetForNewDesign()
      const result = await api.importCadnanoDesign(content)
      if (!result) {
        showToast('Failed to import caDNAno file: ' + (store.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' })
        if (!store.getState().assemblyActive) showWelcome()
        return
      }
      if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
      showToast('Note: caDNAno designs appear upside down due to the original caDNAno coordinate convention.', 8000)
      api.addRecentFile(file.name, content, 'cadnano')
      renderRecentMenu()
      const design = store.getState().currentDesign
      const suggestedName = sanitizeImportName(design?.metadata?.name ?? file.name.replace(/\.[^.]+$/, ''))
      if (store.getState().assemblyActive) {
        await importAsAssemblyPart(suggestedName)
      } else {
        hideWelcome()
        await saveAs()
      }
    }
    input.click()
  })

  // ── Import scadnano ────────────────────────────────────────────────────────────
  document.getElementById('menu-file-import-scadnano')?.addEventListener('click', () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.sc'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const content = await file.text()
      const baseName = file.name.replace(/\.sc$/i, '')
      resetForNewDesign()
      const result = await api.importScadnanoDesign(content, baseName)
      if (!result) {
        showToast('Failed to import scadnano file: ' + (store.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' })
        if (!store.getState().assemblyActive) showWelcome()
        return
      }
      if (result.import_warnings?.length) showToast(result.import_warnings.join(' | '), 5000)
      showToast('Note: scadnano designs appear upside down due to the original scadnano coordinate convention.', 8000)
      api.addRecentFile(file.name, content, 'scadnano')
      renderRecentMenu()
      const design = store.getState().currentDesign
      const suggestedName = sanitizeImportName(design?.metadata?.name ?? baseName)
      if (store.getState().assemblyActive) {
        await importAsAssemblyPart(suggestedName)
      } else {
        hideWelcome()
        await saveAs()
      }
    }
    input.click()
  })

  // ── Import PDB (DNA design and/or protein, by RCSB id or file) ──────────────────
  async function runPdbImport(args) {
    const json = await api.importPdbAuto({
      ...args,
      expectedRevision: api.currentRevisionWatermark?.() ?? null,
    })
    // A response can win the network race with AbortController. Never apply a
    // result after the user cancelled/closed the import dialog.
    if (args.signal?.aborted) return { cancelled: true }
    if (!json) {
      showToast('PDB import failed: ' + (store.getState().lastError?.message ?? 'Unknown error'), { severity: 'error' })
      return null
    }
    if (json.needs_dna_decision) return json   // modal prompts, then re-calls with the choice
    const parts = []
    if (json.imported?.dna) {
      resetForNewDesign()
      api.syncDesignResponse(json)
      hideWelcome()
      parts.push('DNA design')
      if (json.import_warnings?.length) showToast(json.import_warnings.join(' | '), 5000)
    }
    if (json.imported?.protein) {
      if (json.protein_placement === 'library') {
        parts.push(`protein ${json.protein.name} in library (${json.protein.atom_count} atoms)`)
      } else {
        // A free placement was added server-side; syncing renders that exact instance.
        api.syncDesignResponse(json)
        hideWelcome()
        parts.push(`protein ${json.protein.name} (${json.protein.atom_count} atoms)`)
      }
    }
    if (parts.length) showToast('Imported ' + parts.join(' + '), 4000)
    return json
  }

  document.getElementById('menu-file-import-pdb')?.addEventListener('click', () => {
    openImportPdbModal({ onResult: runPdbImport })
  })

  return { importCadnanoWithAutodetection, importScadnanoWithAutodetection, runPdbImport }
}
