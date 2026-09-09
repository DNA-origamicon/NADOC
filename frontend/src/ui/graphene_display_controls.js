/** Browser display preferences only; deliberately independent of job preparation. */
export function initGrapheneDisplayControls({ preview, simulation, storage } = {}) {
  const toggle = document.getElementById('md-graphene-show')
  const select = document.getElementById('md-graphene-representation')
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
    preview?.setDisplay(settings)
    simulation?.setGrapheneDisplay(settings)
  }
  function change() {
    settings = { visible: toggle?.checked !== false, representation: select?.value || 'plane' }
    try { storage.setItem('nadoc.grapheneDisplay', JSON.stringify(settings)) } catch { /* private mode */ }
    apply()
  }
  toggle?.addEventListener('change', change)
  select?.addEventListener('change', change)
  apply()
  return { dispose() {
    toggle?.removeEventListener('change', change)
    select?.removeEventListener('change', change)
  } }
}
