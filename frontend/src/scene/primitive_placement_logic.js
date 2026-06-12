/**
 * Pure helpers for placing a primitive's cross-section on the lattice grid.
 *
 * A primitive's footprint is a fixed set of `[row, col]` lattice cells with one
 * deterministic `anchorCell` (its lowest row, then lowest col). Placement slides
 * the whole rigid footprint so the anchor lands on whatever cell the cursor is
 * over, preserving the relative shape. These functions are the geometry of that
 * translation — no THREE.js, no DOM, so they're unit-testable on their own.
 */

/**
 * Translate every footprint cell so `anchorCell` lands on `hoverCell`.
 * @param {Array<[number,number]>} cells       footprint cells, lattice coords
 * @param {[number,number]} anchorCell         the footprint's reference cell
 * @param {{row:number,col:number}} hoverCell  the cell the cursor snapped to
 * @returns {Array<[number,number]>}           translated cells (new arrays)
 */
export function translateFootprint(cells, anchorCell, hoverCell) {
  const dRow = hoverCell.row - anchorCell[0]
  const dCol = hoverCell.col - anchorCell[1]
  return cells.map(([r, c]) => [r + dRow, c + dCol])
}

const _parity = (r, c) => (((r + c) % 2) + 2) % 2

/**
 * Does translating the footprint so `anchorCell` lands on `hoverCell` preserve the
 * primitive's physical cross-section AND its per-helix topology?
 *
 * Honeycomb cells carry a parity-dependent term, `(row+col)%2`, that sets BOTH the
 * y-stagger of the cell (see honeycombCellWorldPos) AND the scaffold FORWARD/REVERSE
 * direction. A rigid translation preserves every cell's parity only when the shift
 * `dRow+dCol` is EVEN; an odd shift flips every cell's parity, which simultaneously
 * distorts the shape (a closed 6hb ring collapses toward an "I") and inverts each
 * helix's polarity. So a honeycomb placement is valid iff the hover cell has the same
 * `(row+col)` parity as the anchor. Square lattice has no stagger/parity → any shift.
 * (Mechanical rule, not geometric reasoning — see feedback_crossover_no_reasoning.)
 */
export function placementPreservesShape(anchorCell, hoverCell, lattice) {
  if ((lattice ?? 'HONEYCOMB') === 'SQUARE') return true
  return _parity(anchorCell[0], anchorCell[1]) === _parity(hoverCell.row, hoverCell.col)
}

/**
 * Candidate cells to snap the placement anchor to, given the raw cell under the
 * cursor. If that cell already preserves the shape (square lattice, or matching
 * parity on honeycomb), it's the only candidate. Otherwise — a wrong-parity honeycomb
 * cell — the valid cells are its four edge-neighbours (each flips parity back to the
 * anchor's), and the caller picks whichever is physically nearest the cursor. Pure:
 * returns `[row, col]` pairs; the geometric nearest-pick lives in the scene layer.
 */
export function validParityCandidates(rawCell, anchorCell, lattice) {
  if (placementPreservesShape(anchorCell, { row: rawCell.row, col: rawCell.col }, lattice)) {
    return [[rawCell.row, rawCell.col]]
  }
  const { row, col } = rawCell
  return [[row, col - 1], [row, col + 1], [row - 1, col], [row + 1, col]]
}

/**
 * True if the primitive can be placed onto a design with `designLattice`.
 * An empty design (no lattice committed yet, falsy) accepts any primitive; a
 * populated design must match the primitive's lattice (we don't mix lattices).
 * @param {string|null|undefined} designLattice  current design's lattice_type
 * @param {string} primitiveLattice              primitive's lattice
 * @param {boolean} designIsEmpty                true when the design has no helices
 */
export function latticeCompatible(designLattice, primitiveLattice, designIsEmpty) {
  if (designIsEmpty) return true
  return (designLattice ?? 'HONEYCOMB') === (primitiveLattice ?? 'HONEYCOMB')
}
