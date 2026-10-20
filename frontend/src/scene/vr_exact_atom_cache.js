/** Exact simulation coordinates only. One in-flight batch; byte-bounded retention.
 * Copies compact views so evicting a frame also releases its response buffer.
 * Context includes the display epoch: a cancelled load cannot warm the next one.
 */
export function createVRExactAtomCache({ context, fetchFrames, budgetBytes = 32 * 1024 * 1024 }) {
  let key = '', frames = new Map(), bytes = 0, tail = Promise.resolve(), revision = 0, prepared = new WeakMap()
  const size = data => (data?.byteLength ?? (data?.length ?? 0) * 8) + (data?.serialMap?.byteLength ?? 0)
  const copy = data => data?.dense ? { ...data, dense: data.dense.slice(), serialMap: data.serialMap.slice() }
    : data.slice()
  function clear() { key = ''; frames.clear(); bytes = 0; prepared = new WeakMap() }
  function reset() { revision++; clear() }
  async function get(indices) {
    const expected = context(), started = revision
    const live = () => context() === expected && revision === started
    const work = tail.catch(() => {}).then(async () => {
      if (!live()) return null
      if (key !== expected) { clear(); key = expected }
      const missing = indices.filter(i => !frames.has(i))
      const result = missing.length ? await fetchFrames(missing, live) : {}
      if (!live()) return null
      const out = {}
      for (const i of indices) {
        const data = frames.get(i) ?? result?.[String(i)]
        if (!data) throw new Error(`Missing exact atomic trajectory frame ${i + 1}`)
        out[i] = data
        if (!frames.has(i) && size(data) <= budgetBytes) {
          const retained = copy(data), cost = size(retained)
          while (bytes + cost > budgetBytes && frames.size) {
            const oldest = frames.keys().next().value
            bytes -= size(frames.get(oldest)); frames.delete(oldest)
          }
          frames.set(i, retained); bytes += cost; out[i] = retained
        }
      }
      return out
    })
    tail = work
    return work
  }
  return { get, reset, has: index => key === context() && frames.has(index), async prepare(payload) {
    const expected = context(), started = revision
    if (prepared.get(payload)?.key === expected) return prepared.get(payload).capacity
    const indices = payload.frames.map((_, i) => payload.frame_start + i * payload.frame_step)
    // Batches keep transient response/decode memory bounded too.
    let capacity = Infinity
    for (let start = 0; start < indices.length; start += 8) {
      if (context() !== expected || revision !== started) return 0
      const result = await get(indices.slice(start, start + 8))
      if (!result) return 0
      for (const data of Object.values(result)) capacity = Math.min(capacity, Math.floor(budgetBytes / Math.max(1, size(data))))
    }
    if (context() === expected && revision === started) prepared.set(payload, { key: expected, capacity })
    return capacity
  } }
}
