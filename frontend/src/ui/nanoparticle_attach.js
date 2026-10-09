/** One-shot overhang picking; selection filters are restored on every exit. */
export function initNanoparticleAttach({ store, api, selectionController, notify }) {
  let pending = null
  let busy = false
  function cancel() {
    if (!pending) return
    const previous = pending
    pending = null
    store.setState({ selectableTypes: previous.selectableTypes, toolFilters: previous.toolFilters })
  }
  function begin(id) {
    if (busy) return
    cancel()
    const state = store.getState()
    pending = { id, designId: state.currentDesign?.id,
      selectableTypes: state.selectableTypes, toolFilters: state.toolFilters }
    selectionController.clear()
    store.setState({
      selectableTypes: Object.fromEntries(Object.keys(state.selectableTypes).map(k => [k, ['overhangs', 'scaffold', 'staples'].includes(k)])),
      toolFilters: { ...state.toolFilters, overhangLocations: true },
    })
    notify('Select an overhang to attach this nanoparticle. Esc cancels.', 6000)
  }
  const unsubscribe = store.subscribe((state, previous) => {
    if (!pending || busy) return
    if (state.currentDesign?.id !== pending.designId) { cancel(); return }
    if (state.selection === previous.selection) return
    const picks = state.selection?.items?.filter(r => r.kind === 'overhang') ?? []
    if (picks.length !== 1) return
    const target = state.currentDesign?.overhangs?.find(o => o.id === picks[0].id)
    if (!target || target.auxiliary_endpoint) return
    const id = pending.id
    const designId = pending.designId
    busy = true
    cancel()
    notify('Fitting nanoparticle attachment…', 6000)
    api.attachNanoparticleToOverhang(id, target.id)
      .then(() => {
        if (store.getState().currentDesign?.id !== designId) return
        selectionController.select({ kind: 'nanoparticle', id }); notify('Nanoparticle attached.')
      })
      .catch(error => notify(error.message, { severity: 'error', duration: 8000 }))
      .finally(() => { busy = false })
  })
  function onKey(event) { if (event.key === 'Escape' && pending) { cancel(); notify('Attachment cancelled.') } }
  document.addEventListener('keydown', onKey)
  return { begin, cancel, dispose() { cancel(); unsubscribe?.(); document.removeEventListener('keydown', onKey) } }
}
