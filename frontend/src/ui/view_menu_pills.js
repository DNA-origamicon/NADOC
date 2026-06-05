// View-menu pill state + menu-visibility sync.
//
// Extracted verbatim from main.js (banner `// ── View menu toggle pill state`).
// One reactive `store.subscribe` that mirrors store-backed view toggles onto the
// View-menu pill chrome (`is-on` class) plus three small visibility helpers:
//   - _syncAssemblyMenuVisibility: swap the Tools↔Assembly menus + hide the
//     single-design view toggles (slice/unfold/cadnano) in assembly mode.
//   - _syncImportMenuVisibility:  show Import caDNAno/scadnano only on the welcome
//     screen (no design) or in assembly mode.
//   - _syncDeformMenuEnabled:     grey out "Deformed View" while cadnano/unfold is
//     active (both require straight geometry).
//
// `setMenuToggle` (`_setMenuToggle` in main.js) is a 43-use shared menu-pill util
// and stays in main.js — injected here, not moved. `getFileName` exposes the
// mutable `_fileName` closure var (used only for the tab title… which stays in
// main.js; not needed here). These helpers are called ONLY from this region in
// main.js, so the lift is fully self-contained.

export function initViewMenuPills({ store, setMenuToggle }) {
  function syncAssemblyMenuVisibility(active) {
    document.getElementById('menu-item-assembly').style.display  = active ? '' : 'none'
    document.getElementById('menu-item-tools').style.display     = active ? 'none' : ''
    for (const id of ['menu-view-slice', 'menu-view-unfold', 'menu-view-cadnano']) {
      document.getElementById(id).style.display = active ? 'none' : ''
    }
  }

  // Import caDNAno / scadnano are only shown on the welcome screen or in assembly mode.
  function syncImportMenuVisibility() {
    const { currentDesign, assemblyActive } = store.getState()
    const show = !currentDesign || assemblyActive
    for (const id of ['menu-file-import-cadnano', 'menu-file-import-scadnano']) {
      const el = document.getElementById(id)
      if (el) el.style.display = show ? '' : 'none'
    }
  }

  // Gray out the "Deformed View" menu item while cadnano or unfold is active.
  // Both modes require deform to be off (straight geometry), so the toggle is
  // disallowed from inside them; _toggleDeformView() also shows a toast.
  function syncDeformMenuEnabled() {
    const s = store.getState()
    const disabled = !!(s.cadnanoActive || s.unfoldActive)
    document.getElementById('menu-view-deform')?.classList.toggle('disabled', disabled)
  }

  // Sync store-backed toggles reactively.
  store.subscribe((newState, prevState) => {
    if (newState.unfoldActive     !== prevState.unfoldActive)     { setMenuToggle('menu-view-unfold',       newState.unfoldActive);  syncDeformMenuEnabled() }
    if (newState.cadnanoActive    !== prevState.cadnanoActive)    { setMenuToggle('menu-view-cadnano',      newState.cadnanoActive); syncDeformMenuEnabled() }
    if (newState.assemblyActive   !== prevState.assemblyActive)   { syncAssemblyMenuVisibility(newState.assemblyActive); syncImportMenuVisibility() }
    if (newState.currentDesign    !== prevState.currentDesign)    syncImportMenuVisibility()
    if (newState.deformVisuActive !== prevState.deformVisuActive) setMenuToggle('menu-view-deform',       newState.deformVisuActive)
    if (newState.showHelixLabels  !== prevState.showHelixLabels)  setMenuToggle('menu-view-helix-labels', newState.showHelixLabels)
    if (newState.showSequences    !== prevState.showSequences)    setMenuToggle('menu-view-sequences',    newState.showSequences)
    if (newState.staplesHidden    !== prevState.staplesHidden)    setMenuToggle('menu-view-hide-staples', newState.staplesHidden)
    // When unfold auto-deactivates on cadnano exit, update the mode indicator
    // once the unfold animation finishes (cadnanoActive is already false by then).
    if (newState.unfoldActive !== prevState.unfoldActive && !newState.unfoldActive && !newState.cadnanoActive) {
      document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
    }
  })

  syncImportMenuVisibility()

  return { syncAssemblyMenuVisibility, syncImportMenuVisibility, syncDeformMenuEnabled }
}
