/** One fenced batch at a time. GPU timestamps inform future batch sizes but
 * never hold completed work hostage to delayed browser/driver statistics.
 * A small query ring bounds memory; unsupported/disjoint timers use two tiles. */
export function createTraceSchedule(renderer, { budgetMs = 12, maxTiles = 16 } = {}) {
  const gl = renderer.getContext?.(), ext = gl?.getExtension('EXT_disjoint_timer_query_webgl2')
  const fallback = Math.min(2, maxTiles), timers = []
  let fence = null, batch = fallback, gpuMs = null, gpuTimeMs = 0, batches = 0, tiles = 0
  const discardTimers = () => { for (const {query} of timers) gl.deleteQuery(query); timers.length = 0 }
  function collectTiming() {
    if (!ext) return
    if (gl.getParameter(ext.GPU_DISJOINT_EXT)) {
      discardTimers(); batch = fallback; gpuMs = null; return
    }
    while (timers.length && gl.getQueryParameter(timers[0].query, gl.QUERY_RESULT_AVAILABLE)) {
      const {query, count} = timers.shift()
      const elapsed = gl.getQueryParameter(query, gl.QUERY_RESULT) / 1e6
      gl.deleteQuery(query)
      if (Number.isFinite(elapsed) && elapsed > 0 && count > 0) {
        gpuMs = elapsed; gpuTimeMs += elapsed
        batch = Math.max(1, Math.min(maxTiles, Math.floor(budgetMs / Math.max(.05, elapsed / count))))
      }
    }
  }
  function ready() {
    collectTiming()
    if (fence) {
      const status = gl.clientWaitSync(fence, 0, 0)
      if (status === gl.TIMEOUT_EXPIRED) return false
      gl.deleteSync(fence); fence = null
      if (status === gl.WAIT_FAILED) throw new Error('GPU tracing synchronization failed.')
    }
    return true
  }
  return {
    run(engine, target) {
      if (!ready() || engine.samples >= target) return 0
      let submitted = 0
      const query = ext && timers.length < 4 ? gl.createQuery() : null
      if (query) gl.beginQuery(ext.TIME_ELAPSED_EXT, query)
      try {
        while (submitted < batch && engine.samples < target) { engine.step(); submitted++ }
      } finally {
        if (query) { gl.endQuery(ext.TIME_ELAPSED_EXT); timers.push({query, count:submitted}) }
        if (gl?.fenceSync) { fence = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0); gl.flush() }
        batches++; tiles += submitted
      }
      return submitted
    },
    ready,
    get gpuMs() { return gpuMs },
    get diagnostics() { return {gpuBudgetMs:budgetMs, gpuTimeMs, gpuBatches:batches, gpuTiles:tiles, pendingTimers:timers.length, batchTiles:batch} },
    dispose() { if (fence) gl.deleteSync(fence); fence = null; discardTimers() },
  }
}
