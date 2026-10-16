/** Serialize expensive assembly builds, sharing duplicate requests and keeping
 * only the newest waiting snapshot. Disposed/superseded work must check current()
 * before publishing fetched geometry into the scene. */
export function createAssemblyRebuildQueue(run) {
  let active = null, pending = null, cycle = null, generation = 0

  async function drain() {
    try {
      while (pending) {
        const job = pending
        pending = null
        active = job
        try {
          await run(job.snapshot, () => job.generation === generation)
        } catch (error) {
          // A failed obsolete build must not swallow the newest queued request.
          if (!pending) throw error
        }
      }
    } finally {
      active = null
      cycle = null
    }
  }

  return {
    request(snapshot, invalidation = 0) {
      const last = pending ?? active
      if (cycle && last?.snapshot === snapshot && last.invalidation === invalidation &&
          last.generation === generation) return cycle
      pending = { snapshot, invalidation, generation: ++generation }
      if (!cycle) cycle = Promise.resolve().then(drain)
      return cycle
    },
    cancel() { generation++; pending = null },
  }
}
