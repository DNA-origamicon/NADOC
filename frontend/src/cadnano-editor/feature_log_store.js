/** Adapt the editor state without dropping shared feature-log UI feedback. */
export function createFeatureLogStore(editorStore) {
  const adapt = state => ({ ...state, currentDesign: state.design, currentAssembly: null, assemblyActive: false })
  return {
    getState: () => adapt(editorStore.getState()),
    setState(patch) {
      const { currentDesign, ...rest } = patch
      editorStore.setState({ ...rest, ...(Object.hasOwn(patch, 'currentDesign') ? { design: currentDesign } : {}) })
    },
    subscribe: callback => editorStore.subscribe((next, previous) => callback(adapt(next), adapt(previous))),
    subscribeSlice(slice, callback) {
      if (slice === 'assembly') return () => {}
      return editorStore.subscribe((next, previous) => {
        if (slice !== 'design' || next.design !== previous.design) callback(adapt(next), adapt(previous))
      })
    },
  }
}
