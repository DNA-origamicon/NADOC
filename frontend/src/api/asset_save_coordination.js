/** Keep workspace acknowledgements outside a private asset transaction. */
export function createAssetSaveCoordination() {
  let held = null
  const saving = new Set()
  return {
    hold() {
      if (held) throw new Error('Finish or refresh the current asset operation first.')
      let release
      const done = new Promise(resolve => { release = resolve })
      const token = { done }
      held = token
      return { ready: Promise.allSettled([...saving]), release() {
        if (held === token) held = null
        release()
      } }
    },
    async save(action, isCurrent) {
      while (held) await held.done
      if (!isCurrent()) return null
      // Register before dispatch so a new operation waits for the entire save,
      // including its revision acknowledgement and store synchronization.
      let finished
      const pending = new Promise(resolve => { finished = resolve })
      saving.add(pending)
      try { return await action() } finally { saving.delete(pending); finished() }
    },
  }
}
