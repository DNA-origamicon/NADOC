/**
 * Scaffold-coverage graph helpers extracted from main.js, where they were
 * defined verbatim 3× (intersectCoverage) and 2× (findHamiltonianPath) across
 * the auto-scaffold routers. Pure: parameters + Math/Set/Array only — no
 * scene/store/DOM. Unit-tested in scaffold_coverage.test.js.
 */

/** Overlapping {lo,hi} sub-intervals of two scaffold-coverage interval lists. */
export function intersectCoverage(cA, cB) {
  const result = []
  for (const a of cA) {
    for (const b of cB) {
      const lo = Math.max(a.lo, b.lo)
      const hi = Math.min(a.hi, b.hi)
      if (lo <= hi) result.push({ lo, hi })
    }
  }
  return result
}

/**
 * Hamiltonian path via DFS with degree-ascending neighbour ordering.
 * `startFrom`, if provided, is tried as the first starting candidate.
 *
 * @param {Array} ids                node ids to cover
 * @param {Map<any, Set<any>>} adjMap  adjacency (each id → Set of neighbour ids)
 * @param {*} [startFrom]             optional preferred start node
 * @returns {Array|null} an ordering visiting every id once, or null if none exists
 */
export const findHamiltonianPath = (ids, adjMap, startFrom = null) => {
  const vis = new Set(), p = []
  const dfs = id => {
    vis.add(id); p.push(id)
    if (p.length === ids.length) return true
    const nbs = [...adjMap.get(id)].filter(nb => !vis.has(nb))
      .sort((a, b) => adjMap.get(a).size - adjMap.get(b).size)
    for (const nb of nbs) { if (dfs(nb)) return true }
    vis.delete(id); p.pop(); return false
  }
  const sorted = [...ids].sort((a, b) => adjMap.get(a).size - adjMap.get(b).size)
  const starters = startFrom != null
    ? [startFrom, ...sorted.filter(id => id !== startFrom)]
    : sorted
  for (const s of starters) { if (dfs(s)) return p }
  return null
}
