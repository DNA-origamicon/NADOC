/** Winding stencils require a closed, consistently oriented triangle surface.
 * Open sheets otherwise project their silhouette onto unrelated parts of the
 * section plane. Weld positions for this check, since normals/UVs split seams.
 * Tube/cylinder end rings can be closed for the stencil without editing the
 * displayed source geometry. Other open surfaces do not define solid volumes.
 */
export function sectionStencilGeometry(geometry) {
  const position = geometry.getAttribute('position')
  if (!position) return null
  const index = geometry.index
  const count = index ? index.count : position.count
  const ids = new Map(), welded = [], representative = []
  if (!geometry.boundingBox) geometry.computeBoundingBox()
  const box = geometry.boundingBox
  const tolerance = Math.max(box.max.distanceTo(box.min) * 1e-6, 1e-9)
  for (let i = 0; i < position.count; i++) {
    const key = [position.getX(i), position.getY(i), position.getZ(i)].map(v => Math.round(v / tolerance)).join(',')
    if (!ids.has(key)) { ids.set(key, ids.size); representative.push(i) }
    welded.push(ids.get(key))
  }
  const edges = new Map()
  function edge(a, b) {
    const key = a < b ? `${a},${b}` : `${b},${a}`
    const existing = edges.get(key)
    if (existing) { existing.count++; existing.balance += a < b ? 1 : -1 }
    else edges.set(key, { a, b, count: 1, balance: a < b ? 1 : -1 })
  }
  const start = geometry.drawRange.start
  const end = Math.min(count, start + geometry.drawRange.count)
  let triangles = 0
  for (let i = start; i + 2 < end; i += 3) {
    const a = welded[index ? index.getX(i) : i]
    const b = welded[index ? index.getX(i + 1) : i + 1]
    const c = welded[index ? index.getX(i + 2) : i + 2]
    if (a === b || b === c || c === a) continue
    triangles++
    edge(a, b); edge(b, c); edge(c, a)
  }
  if (!triangles) return null
  const boundary = []
  for (const entry of edges.values()) {
    if (entry.count === 1) boundary.push(entry)
    else if (entry.balance !== 0) return null
  }
  if (!boundary.length) return geometry
  if (start !== 0 || end !== count) return null
  if (!['TubeGeometry', 'CylinderGeometry'].includes(geometry.type)) return null
  // Only complete circular tubes have convex, planar end rings.
  if (geometry.type === 'CylinderGeometry' && geometry.parameters.thetaLength < Math.PI * 2 - 1e-6) return null
  const next = new Map()
  for (const { a, b } of boundary) {
    if (next.has(a)) return null
    next.set(a, b)
  }
  const indices = index ? Array.from(index.array) : Array.from({ length: count }, (_, i) => i)
  while (next.size) {
    const start = next.keys().next().value, ring = [start]
    let current = start
    do {
      const end = next.get(current)
      if (end === undefined) return null
      next.delete(current)
      current = end
      if (current !== start) ring.push(current)
    } while (current !== start)
    for (let i = 1; i < ring.length - 1; i++) {
      indices.push(representative[ring[0]], representative[ring[i + 1]], representative[ring[i]])
    }
  }
  const closed = geometry.clone()
  // Keep live animation and per-instance visibility attributes synchronized.
  for (const [name, attribute] of Object.entries(geometry.attributes)) closed.setAttribute(name, attribute)
  closed.setIndex(indices)
  // TubeGeometry uses one material; cylinder groups need to include new caps.
  if (closed.groups.length) closed.addGroup(count, indices.length - count, 0)
  return closed
}
