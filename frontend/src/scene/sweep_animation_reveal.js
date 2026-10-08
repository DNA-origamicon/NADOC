import { BufferAttribute } from 'three'
/** Sweep bp order is path order, including continuations authored toward lower bp.
 * Only newly added/removed sweeps participate; edits of an existing sweep retain
 * the ordinary positional interpolation. No coordinates or topology are changed.
 */
export function sweepAnimationReveal(from, to, t) {
  const before = from?.displayDesign?.deformations ?? []
  const after = to?.displayDesign?.deformations ?? []
  const ranges = new Map()
  for (const [ops, other, progress] of [[after, before, t], [before, after, 1 - t]]) {
    const ids = new Set(other.map(op => op.id))
    for (const op of ops) {
      if (op.type !== 'sweep' || ids.has(op.id)) continue
      for (const id of op.affected_helix_ids ?? []) ranges.set(id, {
        lo: op.plane_a_bp, hi: op.plane_b_bp, reverse: op.params.direction === -1,
        progress: Math.max(0, Math.min(1, progress)),
      })
    }
  }
  if (!ranges.size) return null
  return {
    ranges,
    scale(nuc, fallback = 1) {
      const range = ranges.get(nuc?.helix_id)
      if (!range || nuc.bp_index < range.lo || nuc.bp_index > range.hi) return fallback
      const offset = range.reverse ? range.hi - nuc.bp_index : nuc.bp_index - range.lo
      return Math.max(0, Math.min(1, range.progress * (range.hi - range.lo + 1) - offset))
    },
  }
}

// Tube indices follow longitudinal rings, then optional end caps. Reorder only
// triangle draw order, never vertex placement, so a draw range reveals the path.
const tubeOrders = new WeakMap()
export function revealSweepTube(mesh, range, lo, hi) {
  const geometry = mesh?.geometry
  if (!geometry?.index) return
  if (!range) { geometry.setDrawRange(0, Infinity); return }
  let cached = tubeOrders.get(geometry)
  if (!cached) {
    const indices = Array.from(geometry.index.array), uv = geometry.attributes.uv
    if (!uv) return
    const bodyCount = geometry.userData.sweepBodyIndexCount ?? indices.length
    const capCount = (indices.length - bodyCount) / 2
    const triangles = []
    for (let i = 0; i < indices.length; i += 3) {
      const vertices = indices.slice(i, i + 3)
      const u = i >= bodyCount ? (i < bodyCount + capCount ? 0 : 1)
        : vertices.reduce((sum, v) => sum + uv.getX(v), 0) / 3
      triangles.push({ vertices, u })
    }
    triangles.sort((a, b) => a.u - b.u)
    geometry.setIndex(triangles.flatMap(triangle => triangle.vertices))
    cached = triangles.map(triangle => triangle.u)
    tubeOrders.set(geometry, cached)
  }
  const bp = range.reverse ? range.hi + 1 - range.progress * (range.hi - range.lo + 1)
    : range.lo + range.progress * (range.hi - range.lo + 1)
  const boundary = (bp - lo) / Math.max(1, hi - lo + 1)
  let index = 0
  while (index < cached.length && cached[index] < boundary) index++
  if (range.progress === 0) geometry.setDrawRange(0, 0)
  else if (range.progress === 1) geometry.setDrawRange(0, Infinity)
  else geometry.setDrawRange(range.reverse ? index * 3 : 0,
    (range.reverse ? cached.length - index : index) * 3)
}


const surfaceOrders = new WeakMap()
export function revealSweepSurface(mesh, frame, reveal) {
  if (!mesh?.geometry || !frame?.vertex_nuc_ids?.length) return
  let cached = surfaceOrders.get(frame)
  if (!cached) {
    const thresholds = frame.vertex_nuc_ids.map(key => {
      const parts = key.split(':')
      const bp = Number(parts.at(-2)), hid = parts.slice(0, -2).join(':')
      const range = reveal.ranges.get(hid)
      if (!range || bp < range.lo || bp > range.hi) return 0
      return ((range.reverse ? range.hi - bp : bp - range.lo) + 1) / (range.hi - range.lo + 1)
    })
    const triangles = []
    for (let i = 0; i < frame.faces.length; i += 3) {
      const vertices = frame.faces.slice(i, i + 3)
      triangles.push({ vertices, threshold: Math.max(...vertices.map(v => thresholds[v])) })
    }
    triangles.sort((a, b) => a.threshold - b.threshold)
    cached = { thresholds: triangles.map(triangle => triangle.threshold),
      index: new BufferAttribute(new Uint32Array(triangles.flatMap(triangle => triangle.vertices)), 1) }
    surfaceOrders.set(frame, cached)
  }
  const progress = [...reveal.ranges.values()][0].progress
  let lo = 0, hi = cached.thresholds.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (cached.thresholds[mid] <= progress) lo = mid + 1
    else hi = mid
  }
  mesh.geometry.setIndex(cached.index)
  mesh.geometry.setDrawRange(0, lo * 3)
}
