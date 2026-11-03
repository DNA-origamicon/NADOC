import { trajectoryMemory } from './trajectory_memory.js'

/** Startup reads have the same ownership/byte limits as playback caches. */
export function initMdTrajectoryPrefetch(api) {
  let warm = null
  function cancel() {
    if (!warm) return
    warm.abort.abort()
    for (const lease of Object.values(warm.leases)) trajectoryMemory.release(lease)
    warm = null
  }
  function consume(kind) {
    const pending = warm[kind]
    warm[kind] = null
    trajectoryMemory.release(warm.leases[kind])
    return pending
  }
  return {
    cancel,
    start(jobId, stride, count = 8) {
      cancel()
      const indices = Array.from({ length: count }, (_, i) => i)
      const entry = { jobId, stride, count, abort: new AbortController(), leases: {} }
      warm = entry
      for (const kind of ['model', 'frames']) {
        const lease = Symbol(`prefetch ${kind}`); entry.leases[kind] = lease
        const work = kind === 'model' ? api.getMdAtomisticModel(jobId)
          : api.getMdFramesAtomistic(jobId, indices, { stride, positionsOnly: true, compact: true, signal: entry.abort.signal })
        entry[kind] = work.then(result => {
          if (warm === entry && entry[kind]) trajectoryMemory.retain(lease, result, () => { entry[kind] = null })
          return result
        })
        entry[kind].catch(() => {})
      }
    },
    model(jobId) {
      const pending = warm?.jobId === jobId && warm.model ? consume('model') : null
      return pending ?? api.getMdAtomisticModel(jobId)
    },
    frames(jobId, indices, stride) {
      if (warm?.jobId === jobId && warm.stride === stride && warm.frames && indices.every(i => i >= 0 && i < warm.count)) return consume('frames')
      return api.getMdFramesAtomistic(jobId, indices, { stride, positionsOnly: true, compact: true })
    },
  }
}
