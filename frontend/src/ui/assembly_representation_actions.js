import { getDocId } from '../shared/doc_id.js'
import { confirmedAssemblyRepresentations } from '../api/assembly_response_authority.js'

export const immediateAssemblyRepresentations = new Set(['full', 'beads', 'cylinders', 'hull-prism'])

const members = assembly => JSON.stringify((assembly?.instances ?? []).map(row => row.id).sort())
const representations = assembly => new Map((assembly?.instances ?? []).map(row => [row.id, row.representation]))

/** Change only display metadata. Preserve the renderer's non-enumerable source
 * version, which ordinary object spreading would silently discard. */
export function withAssemblyRepresentations(assembly, wanted) {
  let changed = false
  const instances = assembly.instances.map(row => {
    if (!wanted.has(row.id) || row.representation === wanted.get(row.id)) return row
    changed = true
    const copy = { ...row, representation: wanted.get(row.id) }
    const sourceKey = Object.getOwnPropertyDescriptor(row, 'geometrySourceKey')
    if (sourceKey) Object.defineProperty(copy, 'geometrySourceKey', sourceKey)
    return copy
  })
  return changed ? { ...assembly, instances } : assembly
}

/** Show prepared CG geometry immediately while saving choices in order.
 * Acknowledgements still go through the API's normal revision/persistence path;
 * a newer local choice is reapplied in the same synchronous continuation.
 * Only unsent intermediate choices are coalesced. Atomistic/surface choices use
 * the same queue but keep their established acknowledgement-before-display path.
 */
export function createAssemblyRepresentationActions({
  store, api, onDisplay = () => {}, onError = () => {},
  documentId = getDocId, host = globalThis.window,
}) {
  let scope = null, pending = null, latest = null, running = false, disposed = false, internal = false, epoch = 0

  function current(token) {
    const state = store.getState(), assembly = state.currentAssembly
    return !disposed && token === scope && state.assemblyActive && assembly
      && documentId() === token.docId && assembly.id === token.id && members(assembly) === token.members
  }

  function reset() {
    pending?.resolve(false)
    scope = null; pending = null; latest = null
    epoch++
  }

  function display(token, wanted) {
    if (!current(token)) return
    const before = store.getState().currentAssembly
    const after = withAssemblyRepresentations(before, wanted)
    if (after !== before) {
      internal = true
      try { store.setState({ currentAssembly: after }) } finally { internal = false }
    }
    onDisplay(after)
  }

  function showLatest(token) {
    if (latest?.scope === token && latest.immediate) display(token, latest.wanted)
  }

  // A document replacement retires queued writes and late acknowledgements.
  // Other authoritative snapshots can update metadata while a save is pending;
  // retain that metadata and reapply only the latest representation choice.
  const changed = (next, previous) => {
    if (internal || !scope || next.currentAssembly === previous.currentAssembly
      && next.assemblyActive === previous.assemblyActive) return
    const token = scope
    if (!current(token)) { reset(); return }
    // Metadata/pose tools often spread the displayed rows, including our
    // optimistic representation. That is not a server confirmation. Accepted
    // response provenance confirms every value, including values equal to the
    // optimistic view. Unmarked local snapshots cannot confirm a display choice.
    const confirmed = confirmedAssemblyRepresentations(next.currentAssembly)
    if (confirmed) token.confirmed = confirmed
    showLatest(token)
  }
  const unsubscribe = store.subscribeSlice
    ? store.subscribeSlice('assembly', changed) : store.subscribe(changed)
  host?.addEventListener('nadoc:document-reset', reset)

  async function drain() {
    if (running) return
    running = true
    try {
      while (pending) {
        const choice = pending, token = choice.scope
        pending = null
        if (!current(token)) { choice.resolve(false); continue }
        try {
          const json = await api.batchPatchInstances(choice.patches, { skipSync: true, suppressBusy: choice.immediate })
          if (!current(token)) { choice.resolve(false); continue }
          if (!json?.assembly || json.assembly.id !== token.id) throw new Error('The representation could not be saved.')
          const before = store.getState().currentAssembly
          internal = true
          try { api._syncFromAssemblyResponse(json) } finally { internal = false }
          if (!current(token)) { choice.resolve(false); continue }
          const after = store.getState().currentAssembly
          // A stale response may be rejected by the normal revision guard.
          if (after !== before) token.confirmed = confirmedAssemblyRepresentations(json)
            ?? confirmedAssemblyRepresentations(after) ?? representations(after)
          if (latest === choice) {
            latest = null
            display(token, token.confirmed)
          } else showLatest(token)
          choice.resolve(true)
        } catch (error) {
          if (current(token)) {
            if (latest === choice) {
              latest = null
              display(token, token.confirmed)
            } else showLatest(token)
            onError(error)
          }
          choice.resolve(false)
        }
      }
    } finally { running = false }
  }

  return {
    capture() {
      const assembly = store.getState().currentAssembly
      return { epoch, docId: documentId(), id: assembly?.id, members: members(assembly) }
    },
    choose(representation, context = null) {
      const state = store.getState(), assembly = state.currentAssembly
      if (disposed || !state.assemblyActive || !assembly?.instances?.length) return Promise.resolve(false)
      if (context && (context.epoch !== epoch || context.docId !== documentId()
        || context.id !== assembly.id || context.members !== members(assembly))) return Promise.resolve(false)
      if (!scope || !current(scope)) {
        reset()
        scope = { id: assembly.id, docId: documentId(), members: members(assembly), confirmed: representations(assembly) }
      }
      pending?.resolve(false)
      let resolve
      const result = new Promise(done => { resolve = done })
      const patches = assembly.instances.map(row => ({ id: row.id, representation }))
      const choice = { scope, resolve, patches, wanted: new Map(patches.map(row => [row.id, row.representation])),
        immediate: immediateAssemblyRepresentations.has(representation) }
      pending = latest = choice
      showLatest(scope)
      void drain()
      return result
    },
    dispose() {
      disposed = true; reset(); unsubscribe()
      host?.removeEventListener('nadoc:document-reset', reset)
    },
  }
}
