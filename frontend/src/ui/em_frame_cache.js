/** Own compact numeric arrays; keep scientific values at float64 precision. */
export function compactEMVolume(value) {
  for (const key of ['intensity','outside','sample_positions_nm','cell_sizes_nm']) {
    if (!Array.isArray(value[key])) continue
    const source = Array.isArray(value[key][0]) ? value[key].flat(Infinity) : value[key]
    value[key] = key === 'outside' ? Uint8Array.from(source) : Float64Array.from(source)
  }
  return value
}
function volumeBytes(value) {
  return Object.values(value).reduce((sum, v) => sum + (ArrayBuffer.isView(v) ? v.byteLength : 0), 4096)
    + (value.intensity?.length ?? 1)*24 // prepared display positions and colours
}

/** Bounded cache with one look-ahead lane and one latest-frame demand lane. */
export function createEMFrameCache({load, prepare = () => {}, onReady = () => {}, onError = () => {}, budget = 128*1024*1024, lookAhead = 32}) {
  const entries = new Map(), sizes = new Map(), pending = new Map(), held = new Map()
  let protectedFrames = new Set()
  const protectedFrame = index => index === target?.index || protectedFrames.has(index) || held.has(index)
  let bytes = 0, disposed = false, target = null, revision = 0, demanding = false, retryAt = 0
  function get(index) {
    const entry = entries.get(index)
    if (!entry) return null
    entries.delete(index); entries.set(index,entry)
    return entry.value
  }
  async function fetchFrame(index, ordinal, allowance = budget) {
    if (entries.has(index)) return entries.get(index)
    if (pending.has(index)) {
      const existing = pending.get(index)
      try { return await existing.task }
      catch (error) { if (existing.controller.signal.aborted) return null; throw error }
    }
    const controller = new AbortController()
    const task = (async () => {
      const value = await load(index, ordinal, controller.signal)
      if (disposed || controller.signal.aborted) return null
      compactEMVolume(value)
      const size = volumeBytes(value)
      sizes.set(index,size)
      if (!protectedFrame(index) && size > allowance) return null
      prepare(value)
      while (entries.size && bytes+size > budget) {
        const oldest = [...entries.keys()].find(key => !protectedFrame(key))
        if (oldest === undefined) {
          if (!protectedFrame(index)) return null
          break
        }
        bytes -= entries.get(oldest).size; entries.delete(oldest)
      }
      const entry = {value,size}; entries.set(index,entry); bytes += size
      onReady(index)
      return entry
    })()
    pending.set(index,{task,controller})
    try { return await task } catch (error) { if (controller.signal.aborted) return null; throw error } finally { if (pending.get(index)?.task === task) pending.delete(index) }
  }
  function demand(ready, index, {playing = false} = {}) {
    const ordinal = ready.indexOf(index)
    if (disposed || ordinal < 0) return
    if (target?.index !== index) {
      // Playback advances must not repeatedly abort useful in-flight downloads.
      // Explicit scrubbing still bypasses a stalled request immediately.
      if (!playing) {
        const obsolete = pending.get(target?.index)
        obsolete?.controller.abort()
        if (target) pending.delete(target.index)
        revision++; demanding = false
      }
      target = {index,ordinal}; retryAt = 0
    }
    if (demanding || entries.has(index) || Date.now() < retryAt) return
    demanding = true
    const token = revision
    void (async () => {
      try {
        while (!disposed && token === revision && target && !entries.has(target.index)) {
          const requested = target
          try { await fetchFrame(requested.index,requested.ordinal,Infinity) }
          catch (error) { if (requested === target) { retryAt = Date.now()+1000; onError(error); break } }
        }
      } finally { if (token === revision) demanding = false }
    })()
  }
  return {
    get, demand,
    protect(indices) { protectedFrames = new Set(indices) },
    async ensure(ready, indices) {
      for (const index of indices) held.set(index,(held.get(index) || 0)+1)
      try {
        for (const index of indices) {
          const ordinal = ready.indexOf(index)
          if (disposed || ordinal < 0 || !await fetchFrame(index,ordinal,Infinity)) return false
        }
        return !disposed
      } finally {
        for (const index of indices) {
          const count = held.get(index)-1
          if (count) held.set(index,count); else held.delete(index)
        }
      }
    },
    async prefetch(ready, current) {
      if (!ready.length || disposed) return
      const token = revision, start = Math.max(0, ready.indexOf(current))
      let windowBytes = 0
      for (let offset = 0; offset < Math.min(lookAhead,ready.length); offset++) {
        if (disposed || token !== revision) return
        const ordinal = (start+offset)%ready.length, index = ready[ordinal]
        if (offset && sizes.has(index) && windowBytes+sizes.get(index) > budget) return
        const entry = await fetchFrame(index,ordinal,offset ? budget-windowBytes : Infinity)
        if (!entry) return
        windowBytes += entry.size
        if (windowBytes >= budget) return
      }
    },
    dispose() { disposed = true; for (const entry of pending.values()) entry.controller.abort(); pending.clear(); entries.clear(); sizes.clear(); bytes = 0 },
  }
}
