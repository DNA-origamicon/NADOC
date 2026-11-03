import { selectionRefKey } from './selection_ref.js'
const identity = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]

/** Freeze the acknowledged native selection before any asynchronous work. */
export function createVRClipboard({ getState, api }) {
  let snapshot = null, generation = 0
  return {
    async copy(event) {
      snapshot = null
      const current = ++generation
      const state = getState()
      if (state.assemblyActive) throw new Error('Copy is available in the part editor')
      const refs = state.selection?.items ?? []
      const expected = refs.map(ref => encodeURIComponent(selectionRefKey(ref))).sort()
      if (!expected.length || JSON.stringify(expected) !== JSON.stringify([...(event.owners ?? [])].sort()))
        throw new Error('Selection changed; select Copy again')
      const { feature_log, ...source } = state.currentDesign
      const next = JSON.parse(JSON.stringify({ source, refs, matrix: identity }))
      const result = await api.validateVRClipboard(next)
      if (!result?.accepted) throw new Error('This selection cannot be copied')
      if (current !== generation || getState().currentDesign?.id !== source.id) throw new Error('Design changed')
      snapshot = next
      return result.preview ?? []
    },
    async paste(event, options) {
      if (!snapshot || snapshot.source.id !== getState().currentDesign?.id)
        throw new Error('Select Copy first')
      return api.pasteVRClipboard({ ...snapshot, matrix: event.matrix }, {
        ...options, onCommitted(response) { snapshot = null; options?.onCommitted?.(response) },
      })
    },
    reset() { generation++; snapshot = null },
  }
}
