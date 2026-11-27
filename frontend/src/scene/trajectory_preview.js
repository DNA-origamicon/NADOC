// A small stage-aware grid. Never interpolate across a protocol boundary.
export function previewIndices(count, markers = [], cap = 16) {
  if (count < 1 || cap < 1) return []
  const boundaries = [...new Set([0, ...markers.map(m => m.frame)
    .filter(i => Number.isInteger(i) && i > 0 && i < count), count])].sort((a, b) => a - b)
  const stages = boundaries.slice(0, -1).map((lo, i) => ({ lo, hi: boundaries[i + 1] - 1,
    slots: Math.min(2, boundaries[i + 1] - lo) }))
  let slots = stages.reduce((n, s) => n + s.slots, 0)
  if (slots > cap) return [] // Too many stages for this memory budget.
  while (slots < Math.min(cap, count)) {
    const available = stages.filter(s => s.slots <= s.hi - s.lo)
    available.sort((a, b) => (b.hi - b.lo) / b.slots - (a.hi - a.lo) / a.slots)
    if (!available.length) break
    available[0].slots++; slots++
  }
  return stages.flatMap(({lo, hi, slots}) => {
    const step = Math.max(1, Math.ceil((hi - lo) / Math.max(1, slots - 1)))
    const indices = []
    for (let i = lo; i < hi; i += step) indices.push(i)
    indices.push(hi)
    return indices
  })
}

export function previewPair(indices, position, markers = []) {
  let hi = indices.findIndex(i => i >= position)
  if (hi < 0) hi = indices.length - 1
  let lo = Math.max(0, hi - 1)
  if (indices[hi] === position) lo = hi
  if (markers.some(m => m.frame > indices[lo] && m.frame <= indices[hi])) hi = lo
  const a = indices[lo], b = indices[hi]
  return [a, b, a === b ? 0 : Math.max(0, Math.min(1, (position - a) / (b - a)))]
}

// Pack arithmetic stretches into sparse range requests. Each response contains
// only selected samples, never all intermediate frames.
export function previewRuns(indices) {
  const runs = []
  for (let i = 0; i < indices.length;) {
    const start = i, step = indices[i + 1] - indices[i] || 1
    let end = i
    while (end + 1 < indices.length && indices[end + 1] - indices[end] === step) end++
    runs.push({ start: indices[start], end: indices[end], step })
    i = end + 1
  }
  return runs
}

/** Match the server NTRJ preview layout (backbone + a1); never retain a page. */
export function loadedPreviewFrames(frames, indices, keyCount) {
  const result = new Map()
  if (!keyCount) return result
  for (const index of indices) {
    const frame = frames[index]
    const stride = frame?.length / keyCount
    if (stride === 6) result.set(index, Float32Array.from(frame))
    else if (stride === 9) {
      // The full oxDNA transport has the same first six values, then a3.
      // Exact frames retain all nine; only the existing coarse preview uses six.
      const compact = new Float32Array(keyCount*6)
      for (let row=0; row<keyCount; row++) {
        for (let axis=0; axis<6; axis++) compact[row*6+axis] = frame[row*9+axis]
      }
      result.set(index,compact)
    }
  }
  return result
}
