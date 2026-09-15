/** Browser display preferences only; deliberately independent of job preparation. */
export function initGrapheneDisplayControls({ preview, simulation, ionPaths, storage } = {}) {
  const toggle = document.getElementById('md-graphene-show')
  const select = document.getElementById('md-graphene-representation')
  let selectedSurface = false, previewSurface = false
  let settings = { visible: true, representation: 'plane' }
  try {
    storage ??= globalThis.localStorage
    const saved = JSON.parse(storage.getItem('nadoc.grapheneDisplay') || 'null')
    if (saved) settings = { visible: saved.visible !== false,
      representation: ['plane', 'ball', 'stick'].includes(saved.representation) ? saved.representation : 'plane' }
  } catch { /* unavailable storage or an obsolete preference */ }
  function apply() {
    if (toggle) toggle.checked = settings.visible
    if (select) select.value = settings.representation
    const effective = { ...settings, visible: settings.visible && selectedSurface }
    preview?.setDisplay({ ...settings, visible: settings.visible && previewSurface })
    simulation?.setGrapheneDisplay(effective)
    ionPaths?.setGrapheneDisplay(effective)
  }
  function change() {
    settings = { visible: toggle?.checked !== false, representation: select?.value || 'plane' }
    try { storage.setItem('nadoc.grapheneDisplay', JSON.stringify(settings)) } catch { /* private mode */ }
    apply()
  }
  toggle?.addEventListener('change', change)
  select?.addEventListener('change', change)
  const onSelection = event => {
    const wasPreview = previewSurface
    selectedSurface = !!event.detail?.enabled
    previewSurface = event.detail?.previewEnabled ?? selectedSurface
    // Explicitly enabling a new setup reveals it even if the last job's wall was hidden.
    if (previewSurface && !wasPreview && !selectedSurface) settings.visible = true
    apply()
  }
  window.addEventListener('nadoc:namd-surface-selection', onSelection)
  apply()
  return { dispose() {
    window.removeEventListener('nadoc:namd-surface-selection', onSelection)
    toggle?.removeEventListener('change', change)
    select?.removeEventListener('change', change)
  } }
}
