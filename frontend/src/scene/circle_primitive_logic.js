/**
 * Pure geometry for the parametric *circle* (flat disc) primitive — the JS mirror
 * of `backend/core/circle_primitive.py`. A circle is a single row of helices whose
 * lengths trace a circular chord profile; the disc lives in the plane containing the
 * helix axis (column direction × along-helix), one helix-layer thick.
 *
 * These functions turn a radius (nm) into a placement footprint (lattice cells +
 * per-cell bp lengths) so the placement ghost can follow the cursor and update live
 * as the user edits the radius — no backend round-trip per keystroke. Both sides are
 * pinned to the same numeric oracle (see circle_primitive_logic.test.js) so the
 * client-side preview and the server-side build never diverge. No THREE.js, no DOM.
 */
import { BDNA_RISE_PER_BP, SQUARE_HELIX_SPACING } from '../constants.js'

/** A column is included only if its ideal chord ≥ this many bp (the disc edge cutoff). */
export const DEFAULT_MIN_CHORD_BP = 16

/**
 * Per-column even-bp lengths for a disc of `radiusNm`, centred ON a column.
 * @returns {Array<[number,number]>} `[colOffset, lengthBp]` pairs, centre-symmetric,
 *   each length even and ≥ minChordBp. Empty when the radius admits no column.
 */
export function columnLengths(radiusNm, {
  colPitchNm = SQUARE_HELIX_SPACING,
  riseNm = BDNA_RISE_PER_BP,
  minChordBp = DEFAULT_MIN_CHORD_BP,
} = {}) {
  if (!(radiusNm > 0)) return []
  const maxCol = Math.floor(radiusNm / colPitchNm) + 1
  const out = []
  for (let col = -maxCol; col <= maxCol; col++) {
    const x = col * colPitchNm
    if (Math.abs(x) >= radiusNm) continue
    const chordNm = 2 * Math.sqrt(radiusNm * radiusNm - x * x)
    let bp = Math.round(chordNm / riseNm)
    bp -= bp % 2                       // force even → symmetric trim
    if (bp >= minChordBp) out.push([col, bp])
  }
  return out
}

/**
 * Placement footprint for a disc of `radiusNm`, or null if no column qualifies.
 * Cells are a single row (row 0), columns 0…N-1; the caller translates the anchor
 * `[0,0]` onto the cursor cell.
 * @returns {{cells:Array<[number,number]>, cellLengths:number[], anchorCell:[number,number], radiusNm:number}|null}
 */
export function circleFootprint(radiusNm, opts = {}) {
  const cols = columnLengths(radiusNm, opts)
  if (!cols.length) return null
  return {
    cells: cols.map((_, i) => [0, i]),
    cellLengths: cols.map(([, bp]) => bp),
    // Anchor on the CENTRE column (longest chord) so the cursor sits at the disc's
    // tangent point with the plane, not at the first helix. Odd N → exact middle.
    anchorCell: [0, (cols.length - 1) >> 1],
    radiusNm,
  }
}

/**
 * Per-column implied radius `√(x² + (L/2)²)` for a centred disc — its spread is the
 * circularity error. Assumes `cellLengths` is centre-symmetric (a contiguous row).
 * @returns {number[]}
 */
export function impliedRadii(cellLengths, {
  colPitchNm = SQUARE_HELIX_SPACING,
  riseNm = BDNA_RISE_PER_BP,
} = {}) {
  const n = cellLengths.length
  if (!n) return []
  const centre = (n - 1) / 2
  return cellLengths.map((length, i) => {
    const x = (i - centre) * colPitchNm
    const halfNm = (length * riseNm) / 2
    return Math.sqrt(x * x + halfNm * halfNm)
  })
}

/** Circularity error (nm): max − min implied radius. 0 = perfect circle. */
export function circularitySpread(cellLengths, opts = {}) {
  const radii = impliedRadii(cellLengths, opts)
  if (!radii.length) return 0
  return Math.max(...radii) - Math.min(...radii)
}
