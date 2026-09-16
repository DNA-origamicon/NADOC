/** Overlap the three independent startup reads. Keep only one pending job; the
 * foreground consumer takes ownership of each result exactly once. */
export function initMdTrajectoryPrefetch(api) {
  let warm = null
  return {
    start(jobId, stride, count = 8) {
      const indices = Array.from({ length:count }, (_, i) => i)
      warm = { jobId, stride,
        model: api.getMdAtomisticModel(jobId),
        frames: api.getMdFramesAtomistic(jobId, indices, { stride, positionsOnly:true, compact:true }) }
      warm.model.catch(() => {}); warm.frames.catch(() => {})
    },
    model(jobId) {
      const pending = warm?.jobId === jobId ? warm.model : null
      if (pending) warm.model = null
      return pending ?? api.getMdAtomisticModel(jobId)
    },
    frames(jobId, indices, stride) {
      if (warm?.jobId === jobId && warm.stride === stride && warm.frames && indices.every(i => i >= 0 && i < 8)) {
        const pending = warm.frames; warm.frames = null
        return pending
      }
      return api.getMdFramesAtomistic(jobId, indices, { stride, positionsOnly:true, compact:true })
    },
  }
}
