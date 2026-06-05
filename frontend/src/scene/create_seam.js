// Create Seam — places scaffold Holliday junctions ("seam" crossovers) along a
// Hamiltonian path through the bundle's scaffold helices.
//
// Extracted from main.js (the `menu-create-seam` click handler). The bulk is a
// PURE core, `computeSeamPlacements(design) → placements[]`, that reads only the
// design topology (strands + helices + lattice_type) and the already-extracted
// scaffold-coverage helpers. `initCreateSeam({ store, api })` is the thin wiring
// that reads the current design and posts the batch.
//
// See `scene/scaffold_coverage.js` for `intersectCoverage` / `findHamiltonianPath`.

import { intersectCoverage, findHamiltonianPath } from './scaffold_coverage.js'

// Scaffold crossover lookup tables (mirrors pathview.js constants).
const HC_SCAF_XOVER_MAP = {
  '1_1':[ 0,+1],'1_2':[ 0,+1],'1_11':[ 0,+1],'1_12':[ 0,+1],
  '1_8':[-1, 0],'1_9':[-1, 0],'1_18':[-1, 0],'1_19':[-1, 0],
  '1_4':[ 0,-1],'1_5':[ 0,-1],'1_15':[ 0,-1],'1_16':[ 0,-1],
  '0_1':[ 0,-1],'0_2':[ 0,-1],'0_11':[ 0,-1],'0_12':[ 0,-1],
  '0_8':[+1, 0],'0_9':[+1, 0],'0_18':[+1, 0],'0_19':[+1, 0],
  '0_4':[ 0,+1],'0_5':[ 0,+1],'0_15':[ 0,+1],'0_16':[ 0,+1],
}
const SQ_SCAF_XOVER_MAP = {
  '1_4':[ 0,+1],'1_5':[ 0,+1],'1_15':[ 0,+1],'1_16':[ 0,+1],'1_26':[ 0,+1],'1_27':[ 0,+1],
  '1_7':[+1, 0],'1_8':[+1, 0],'1_18':[+1, 0],'1_19':[+1, 0],'1_28':[+1, 0],'1_29':[+1, 0],
  '1_0':[ 0,-1],'1_10':[ 0,-1],'1_11':[ 0,-1],'1_20':[ 0,-1],'1_21':[ 0,-1],'1_31':[ 0,-1],
  '1_2':[-1, 0],'1_3':[-1, 0],'1_12':[-1, 0],'1_13':[-1, 0],'1_23':[-1, 0],'1_24':[-1, 0],
  '0_4':[ 0,-1],'0_5':[ 0,-1],'0_15':[ 0,-1],'0_16':[ 0,-1],'0_26':[ 0,-1],'0_27':[ 0,-1],
  '0_7':[-1, 0],'0_8':[-1, 0],'0_18':[-1, 0],'0_19':[-1, 0],'0_28':[-1, 0],'0_29':[-1, 0],
  '0_0':[ 0,+1],'0_10':[ 0,+1],'0_11':[ 0,+1],'0_20':[ 0,+1],'0_21':[ 0,+1],'0_31':[ 0,+1],
  '0_2':[+1, 0],'0_3':[+1, 0],'0_12':[+1, 0],'0_13':[+1, 0],'0_23':[+1, 0],'0_24':[+1, 0],
}
// mods where bowDir=+1 (lowerBp = bp-1) — mirrors pathview.js _XOVER_BOW_RIGHT_*_SCAF
const HC_SCAF_BOW_RIGHT = new Set([2,5,9,12,16,19])
const SQ_SCAF_BOW_RIGHT = new Set([0,3,5,8,11,13,16,19,21,24,27,29])

// Lattice-derived constants (HC = honeycomb period 21, SQ = square period 32).
function latticeParams(isHC) {
  return {
    period:      isHC ? 21 : 32,
    xoverMap:    isHC ? HC_SCAF_XOVER_MAP : SQ_SCAF_XOVER_MAP,
    bowRightSet: isHC ? HC_SCAF_BOW_RIGHT : SQ_SCAF_BOW_RIGHT,
  }
}

// A grid cell carries a FORWARD scaffold strand when (row+col) is even.
export function isForward(row, col) {
  return (((row + col) % 2) + 2) % 2 === 0
}

// The grid neighbor a scaffold crossover at (row,col,bp) bridges to, or null if
// `bp` (mod period) is not a valid scaffold-crossover position for this cell.
export function scaffoldXoverNeighbor(row, col, bp, isHC) {
  const { period, xoverMap } = latticeParams(isHC)
  const fwd = isForward(row, col)
  const mod = ((bp % period) + period) % period
  const d   = xoverMap[`${fwd ? 1 : 0}_${mod}`]
  return d ? [row + d[0], col + d[1]] : null
}

// The nick bp for the given strand of a seam crossover at `xoverBp`. The bow
// direction (whether the crossover "leans" left or right within its period)
// decides which of the two adjacent bp the nick falls on.
export function nickBpForStrand(xoverBp, strand, isHC) {
  const { period, bowRightSet } = latticeParams(isHC)
  const mod     = ((xoverBp % period) + period) % period
  const lowerBp = bowRightSet.has(mod) ? xoverBp - 1 : xoverBp
  return strand === 'FORWARD' ? lowerBp : lowerBp + 1
}

// PURE: compute the full batch of seam-crossover placements for a design.
// Reads only design topology; returns the placement list to POST (empty if the
// design has fewer than 4 chainable scaffold helices or no valid junctions).
export function computeSeamPlacements(design) {
  if (!design) return []

  const isHC = design.lattice_type === 'HONEYCOMB'

  // Build scaffold coverage map: helixId → [{lo, hi}] bp intervals from scaffold
  // strands. Intervals are merged post-collection so that scaffold strands already
  // split by prior seam crossovers collapse back into their original contiguous
  // regions.
  const scaffoldCoverage = new Map()
  for (const s of design.strands) {
    if (s.strand_type !== 'scaffold') continue
    for (const d of s.domains) {
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      if (!scaffoldCoverage.has(d.helix_id)) scaffoldCoverage.set(d.helix_id, [])
      scaffoldCoverage.get(d.helix_id).push({ lo, hi })
    }
  }
  // Merge overlapping or adjacent (gap ≤ 1 bp) intervals per helix.
  for (const [id, ivs] of scaffoldCoverage) {
    const s = ivs.slice().sort((a, b) => a.lo - b.lo)
    const m = [{ ...s[0] }]
    for (let i = 1; i < s.length; i++) {
      if (s[i].lo <= m[m.length - 1].hi + 1) m[m.length - 1].hi = Math.max(m[m.length - 1].hi, s[i].hi)
      else m.push({ ...s[i] })
    }
    scaffoldCoverage.set(id, m)
  }

  // Build lookups.
  const allHelixById = new Map()
  for (const h of design.helices) allHelixById.set(h.id, h)

  // Collect all scaffold helices that have a grid position.
  const scaffoldHelices = []
  for (const [helixId] of scaffoldCoverage) {
    const h = allHelixById.get(helixId)
    if (h?.grid_pos) scaffoldHelices.push(h)
  }

  // Build a global adjacency graph: edge between hA and hB exists if there is at
  // least one bp that (a) lies in the intersection of their scaffold coverage and
  // (b) is a valid HC/SQ scaffold crossover from hA to hB.
  // This naturally produces cross-section-change edges (arm ↔ core) alongside
  // same-section edges, so a single Hamiltonian path handles all structure types.
  const globalAdj = new Map(scaffoldHelices.map(h => [h.id, new Set()]))
  for (let ai = 0; ai < scaffoldHelices.length; ai++) {
    const hA = scaffoldHelices[ai]
    const [rowA, colA] = hA.grid_pos
    const covA = scaffoldCoverage.get(hA.id)
    for (let bi = ai + 1; bi < scaffoldHelices.length; bi++) {
      const hB = scaffoldHelices[bi]
      if (!hB.grid_pos) continue
      const covB = scaffoldCoverage.get(hB.id)
      const overlap = intersectCoverage(covA, covB)
      if (!overlap.length) continue
      let found = false
      outer: for (const { lo, hi } of overlap) {
        for (let bp = lo; bp <= hi; bp++) {
          const nb = scaffoldXoverNeighbor(rowA, colA, bp, isHC)
          if (nb && nb[0] === hB.grid_pos[0] && nb[1] === hB.grid_pos[1]) { found = true; break outer }
        }
      }
      if (found) {
        globalAdj.get(hA.id).add(hB.id)
        globalAdj.get(hB.id).add(hA.id)
      }
    }
  }

  // Find connected components (handles fully-disconnected sub-structures).
  const _visited = new Set()
  const components = []
  for (const h of scaffoldHelices) {
    if (_visited.has(h.id)) continue
    const comp = []
    const stack = [h.id]
    while (stack.length) {
      const id = stack.pop()
      if (_visited.has(id)) continue
      _visited.add(id); comp.push(id)
      for (const nb of globalAdj.get(id)) { if (!_visited.has(nb)) stack.push(nb) }
    }
    components.push(comp)
  }

  const placements = []

  for (const comp of components) {
    if (comp.length < 4) continue

    // Group helices by coverage signature (sorted lo:hi intervals).
    // In a dumbbell, arm helices and core helices have different signatures and must
    // be chained via exactly one bridge edge so each arm has exactly one rail.
    const covSig = id => scaffoldCoverage.get(id)
      .slice().sort((a, b) => a.lo - b.lo).map(({lo, hi}) => `${lo}:${hi}`).join('|')
    const sigMap = new Map()
    for (const id of comp) {
      const sig = covSig(id)
      if (!sigMap.has(sig)) sigMap.set(sig, [])
      sigMap.get(sig).push(id)
    }
    const groups = [...sigMap.values()]

    let path
    if (groups.length === 1) {
      path = findHamiltonianPath(comp, globalAdj)
    } else {
      // Multi-section design (dumbbell etc.).
      // Sort groups ascending by total scaffold bp so arm groups come before core.
      groups.sort((a, b) => {
        const bp = ids => scaffoldCoverage.get(ids[0]).reduce((s, {lo, hi}) => s + hi - lo + 1, 0)
        return bp(a) - bp(b)
      })

      // Local adjacency within each group (no cross-group edges).
      const localAdjs = groups.map(grpIds => {
        const idSet = new Set(grpIds)
        const adj = new Map(grpIds.map(id => [id, new Set()]))
        for (const id of grpIds)
          for (const nb of globalAdj.get(id))
            if (idSet.has(nb)) adj.get(id).add(nb)
        return adj
      })

      // Chain: find path within arm group, orient its bridge endpoint last,
      // then find path within core group starting from the bridge core helix.
      // This gives: arm_rail…arm_bridge | core_bridge…core_rail
      // producing exactly 1 outer rail, 1 outer↔outer pair, 1 outer↔core junction.
      path = findHamiltonianPath(groups[0], localAdjs[0]) ?? groups[0].slice()
      for (let gi = 1; gi < groups.length; gi++) {
        const nextIds  = groups[gi]
        const nextSet  = new Set(nextIds)

        // Orient current path so its last element has a cross-group edge into nextIds.
        const endHasEdge = id => [...(globalAdj.get(id) ?? [])].some(nb => nextSet.has(nb))
        if (!endHasEdge(path[path.length - 1]) && endHasEdge(path[0])) path.reverse()

        const bridgeCore = [...(globalAdj.get(path[path.length - 1]) ?? [])].find(nb => nextSet.has(nb))
        if (bridgeCore) {
          // Find path in next group starting at the bridge core helix.
          let nextPath = findHamiltonianPath(nextIds, localAdjs[gi], bridgeCore)
            ?? findHamiltonianPath(nextIds, localAdjs[gi])
          if (nextPath && nextPath[0] !== bridgeCore) nextPath.reverse()
          path = [...path, ...(nextPath ?? nextIds)]
        } else {
          path = [...path, ...(findHamiltonianPath(nextIds, localAdjs[gi]) ?? nextIds)]
        }
      }
    }

    if (!path || path.length < 4) {
      console.warn(`[CreateSeam] No Hamiltonian path for component of ${comp.length} helices`)
      continue
    }

    // path[0] and path[last] are rails. Interior consecutive pairs get Holliday junctions.
    for (let i = 1; i < path.length - 2; i += 2) {
      const hA = allHelixById.get(path[i])
      const hB = allHelixById.get(path[i + 1])
      if (!hA?.grid_pos || !hB?.grid_pos) continue

      const [rowA, colA] = hA.grid_pos
      const fwdA    = isForward(rowA, colA)
      const strandA = fwdA ? 'FORWARD' : 'REVERSE'
      const strandB = fwdA ? 'REVERSE' : 'FORWARD'

      // One Holliday junction per merged intersection interval.
      // Core↔core pairs have a single interval [0,N] → one junction.
      // Outer↔outer and bridge pairs have two intervals (one per arm) → one junction each.
      // Interval merging earlier ensures re-run split strands don't produce spurious extras.
      const covA = scaffoldCoverage.get(hA.id)
      const covB = scaffoldCoverage.get(hB.id)
      const overlap = intersectCoverage(covA, covB)
      if (!overlap.length) continue

      for (const { lo, hi } of overlap) {
        const intervalMid = Math.round((lo + hi) / 2)

        const validBps = []
        for (let bp = lo; bp <= hi; bp++) {
          const nb = scaffoldXoverNeighbor(rowA, colA, bp, isHC)
          if (nb && nb[0] === hB.grid_pos[0] && nb[1] === hB.grid_pos[1]) validBps.push(bp)
        }
        if (validBps.length < 2) continue

        let bp1 = validBps[0], bp2 = validBps[1], bestDist = Infinity
        for (let j = 0; j < validBps.length - 1; j++) {
          if (validBps[j + 1] === validBps[j] + 1) {
            const dist = Math.abs((validBps[j] + validBps[j + 1]) / 2 - intervalMid)
            if (dist < bestDist) { bestDist = dist; bp1 = validBps[j]; bp2 = validBps[j + 1] }
          }
        }
        if (bestDist === Infinity) continue

        for (const xoverBp of [bp1, bp2]) {
          placements.push({
            halfA: { helix_id: hA.id, index: xoverBp, strand: strandA },
            halfB: { helix_id: hB.id, index: xoverBp, strand: strandB },
            nickBpA: nickBpForStrand(xoverBp, strandA, isHC),
            nickBpB: nickBpForStrand(xoverBp, strandB, isHC),
          })
        }
      }
    }
  }

  return placements
}

// Wire the "Create Seam" menu item: read the current design, compute the seam
// placements, and post the batch. Display/topology mutation happens server-side
// via `api.placeCrossoverBatch` (returns the new design through the store sync).
export function initCreateSeam({ store, api }) {
  document.getElementById('menu-create-seam')?.addEventListener('click', async function () {
    const design = store.getState().currentDesign
    if (!design) return
    const placements = computeSeamPlacements(design)
    if (placements.length > 0) await api.placeCrossoverBatch(placements)
  })
}
