/** Boundary edge identities are constant while one occupancy hull is built. */
export function latticeCellEdges(polygon) {
  const vertexKey = p => `${Math.round(p.x * 1e7)},${Math.round(p.z * 1e7)}`
  return polygon.map((a, i) => {
    const b = polygon[(i + 1) % polygon.length], ak = vertexKey(a), bk = vertexKey(b)
    return { a, b, ak, bk, key: `${ak}>${bk}`, reverse: `${bk}>${ak}` }
  })
}

/** No cross-build cache: cell coordinates and lattice may change after edits. */
export function createLatticeEdgeCache(polygonForCell) {
  const edges = new Map()
  return cell => {
    if (!edges.has(cell)) edges.set(cell, latticeCellEdges(polygonForCell(cell)))
    return edges.get(cell)
  }
}
