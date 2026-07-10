/**
 * Pure helpers for cluster copy/paste (Ctrl+C / Ctrl+V in the 3D part editor).
 *
 * No THREE, no store, no DOM — everything here is input → output so it can be
 * unit-tested directly. The stateful ghost/clipboard lives in cluster_clipboard.js.
 *
 * PHASE PRESERVATION (the reason this feature is more than a 3D copy):
 * a helix's FORWARD/REVERSE polarity is `(row + col) % 2` on BOTH lattices, and
 * crossover legality is a table lookup keyed on `(is_forward, bp_index % period)`.
 * A paste copies helices verbatim at Δbp = 0, so it stays legal iff the grid shift
 * has EVEN parity — `(Δrow + Δcol) % 2 === 0`.
 *
 * NOTE this is deliberately NOT `placementPreservesShape` from
 * primitive_placement_logic.js. That predicate answers "does the footprint keep its
 * SHAPE", and correctly returns true for any square-lattice shift (square has no
 * y-stagger). Primitive placement re-derives each helix from its destination cell,
 * so polarity fixes itself. A cluster paste GRAFTS helices verbatim, so an odd
 * square shift keeps the shape but silently inverts every polarity. Same parity
 * arithmetic, different question — hence a separate predicate.
 */

const _parity = (r, c) => (((r + c) % 2) + 2) % 2

/** True iff translating `anchorCell` onto `hoverCell` preserves helix polarity + crossover phase. */
export function pastePreservesPhase(anchorCell, hoverCell) {
  return _parity(anchorCell[0], anchorCell[1]) === _parity(hoverCell.row, hoverCell.col)
}

/**
 * Cells the paste anchor may snap to, given the raw cell under the cursor.
 * Same-parity cell → it's the only candidate. Wrong parity → its four edge
 * neighbours (each flips parity back); the caller picks the nearest to the cursor.
 * Unlike validParityCandidates this applies to the SQUARE lattice too.
 */
export function pasteParityCandidates(rawCell, anchorCell) {
  if (pastePreservesPhase(anchorCell, rawCell)) return [[rawCell.row, rawCell.col]]
  const { row, col } = rawCell
  return [[row, col - 1], [row, col + 1], [row - 1, col], [row + 1, col]]
}

/** The (Δrow, Δcol) implied by dropping `anchorCell` on `hoverCell`. */
export function pasteGridDelta(anchorCell, hoverCell) {
  return [hoverCell.row - anchorCell[0], hoverCell.col - anchorCell[1]]
}

/**
 * Transitively close a cluster selection over `parent_cluster_id`, BOTH directions.
 *
 * A child cluster's transform is expressed in its parent's rest frame, so a child
 * without its parent is meaningless; a parent without its children loses the
 * sub-poses. Selecting either end pulls in the other. Mirrors the backend's
 * `cluster_closure` — the backend is authoritative, this is for the UI's ghost +
 * "copied 2 clusters (+1 child)" message.
 *
 * @returns {{closureIds: string[], addedIds: string[]}} both in design order
 */
export function clusterClosure(clusterIds, clusters) {
  const byId = new Map((clusters ?? []).map(c => [c.id, c]))
  const requested = new Set(clusterIds.filter(id => byId.has(id)))
  if (!requested.size) return { closureIds: [], addedIds: [] }

  const children = new Map()
  for (const c of clusters) {
    if (!c.parent_cluster_id) continue
    if (!children.has(c.parent_cluster_id)) children.set(c.parent_cluster_id, [])
    children.get(c.parent_cluster_id).push(c.id)
  }

  const closure = new Set(requested)
  const stack = [...requested]
  while (stack.length) {
    const id = stack.pop()
    const parent = byId.get(id)?.parent_cluster_id
    if (parent && byId.has(parent) && !closure.has(parent)) {
      closure.add(parent)
      stack.push(parent)
    }
    for (const child of children.get(id) ?? []) {
      if (!closure.has(child)) {
        closure.add(child)
        stack.push(child)
      }
    }
  }

  const closureIds = clusters.filter(c => closure.has(c.id)).map(c => c.id)
  return { closureIds, addedIds: closureIds.filter(id => !requested.has(id)) }
}

/** Construction plane of a helix, from its `h_{XY|XZ|YZ}_{row}_{col}` id. */
export function planeOfHelixId(helixId) {
  const m = /^h_(XY|XZ|YZ)_/.exec(helixId ?? '')
  return m ? m[1] : null
}

/**
 * The lattice footprint of a set of clusters: the cells their helices occupy, the
 * anchor cell (min row, then min col — matching the backend's `primitive_anchor_cell`),
 * and the construction plane.
 *
 * @returns {{cells: number[][], anchorCell: number[], plane: string, latticeType: string,
 *            helixIds: string[]} | null} null when nothing copyable was found
 */
export function footprintForClusters(closureIds, design) {
  const wanted = new Set(closureIds)
  const helixIds = new Set()
  for (const c of design?.cluster_transforms ?? []) {
    if (wanted.has(c.id)) for (const h of c.helix_ids ?? []) helixIds.add(h)
  }
  if (!helixIds.size) return null

  const cells = []
  let plane = null
  for (const h of design.helices ?? []) {
    if (!helixIds.has(h.id) || !h.grid_pos) continue
    cells.push([h.grid_pos[0], h.grid_pos[1]])
    plane = plane ?? planeOfHelixId(h.id)
  }
  if (!cells.length) return null

  const anchorCell = cells.reduce((a, c) =>
    c[0] < a[0] || (c[0] === a[0] && c[1] < a[1]) ? c : a
  )

  return {
    cells,
    anchorCell,
    plane: plane ?? 'XY',
    latticeType: design.lattice_type ?? 'HONEYCOMB',
    helixIds: [...helixIds],
  }
}

/**
 * Why this cluster selection can't be copied yet, or null when it can.
 *
 * Mirrors the backend's `_refuse_unsupported` (`cluster_copy.py`) so the user finds out
 * at Ctrl+C instead of after aiming a ghost. The backend stays authoritative — this only
 * moves the message earlier. Overhangs/extensions are REFUSED rather than dropped:
 * dropping an OverhangSpec while keeping its backing Domain would leave a dangling
 * `Domain.overhang_id` and silently render an ssDNA overhang as duplex.
 */
export function unsupportedCopyReason(helixIds, design) {
  const helices = new Set(helixIds)
  const ohs = (design?.overhangs ?? []).filter(o => helices.has(o.helix_id))
  if (ohs.length) {
    return `Can't copy: the selected cluster carries ${ohs.length} overhang${ohs.length === 1 ? '' : 's'}.`
      + ' Copying overhangs, extensions and linkers is not supported yet.'
  }
  const strandIds = new Set(
    (design?.strands ?? [])
      .filter(s => (s.domains ?? []).some(d => helices.has(d.helix_id)))
      .map(s => s.id)
  )
  const exts = (design?.extensions ?? []).filter(e => strandIds.has(e.strand_id))
  if (exts.length) {
    return `Can't copy: the selected cluster carries ${exts.length} strand extension${exts.length === 1 ? '' : 's'}.`
      + ' Copying overhangs, extensions and linkers is not supported yet.'
  }
  return null
}

/** Human-readable summary of what a copy grabbed, for the toast. */
export function describeCopy(closureIds, addedIds, helixCount) {
  const n = closureIds.length
  let msg = `Copied ${n} cluster${n === 1 ? '' : 's'} (${helixCount} helices)`
  if (addedIds.length) {
    msg += ` — pulled in ${addedIds.length} linked cluster${addedIds.length === 1 ? '' : 's'}`
  }
  return msg
}
