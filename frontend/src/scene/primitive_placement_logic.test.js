import { describe, it, expect } from 'vitest'
import {
  translateFootprint,
  latticeCompatible,
  placementPreservesShape,
  validParityCandidates,
} from './primitive_placement_logic.js'
import { honeycombCellWorldPos } from './slice_plane/lattice_math.js'

// 6hb closed-ring footprint (from workspace/Primitives/6hb_primitive.nadoc).
const SIX_HB = [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]]
const SIX_HB_ANCHOR = [0, 1]   // min row, then min col

// Relative XY geometry of a footprint placed at (row,col) → world, normalized so the
// anchor (first cell) sits at the origin. Two placements with equal relative geometry
// are congruent (same physical shape). Rounded to kill float noise.
function relShape(cells) {
  const p0 = honeycombCellWorldPos(cells[0][0], cells[0][1], 'XY', 0)
  return cells.map(([r, c]) => {
    const p = honeycombCellWorldPos(r, c, 'XY', 0)
    return [Math.round((p.x - p0.x) * 1e4) / 1e4, Math.round((p.y - p0.y) * 1e4) / 1e4]
  })
}

describe('translateFootprint', () => {
  const cells = [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]]   // 6hb footprint
  const anchor = [0, 1]                                            // min row, then min col

  it('places the anchor cell exactly on the hovered cell', () => {
    const out = translateFootprint(cells, anchor, { row: 5, col: 7 })
    expect(out[0]).toEqual([5, 7])   // anchor moved to hover
  })

  it('translates the whole footprint rigidly, preserving relative shape', () => {
    const out = translateFootprint(cells, anchor, { row: 5, col: 7 })
    // every cell shifted by (hover - anchor) = (+5, +6)
    expect(out).toEqual([[5, 7], [6, 7], [6, 8], [6, 9], [5, 9], [5, 8]])
  })

  it('is identity when the anchor is hovered', () => {
    expect(translateFootprint(cells, anchor, { row: 0, col: 1 })).toEqual(cells)
  })

  it('handles negative translation', () => {
    const out = translateFootprint([[2, 2]], [2, 2], { row: 0, col: 0 })
    expect(out).toEqual([[0, 0]])
  })

  it('returns fresh arrays (does not mutate input)', () => {
    const src = [[0, 0]]
    translateFootprint(src, [0, 0], { row: 3, col: 3 })
    expect(src).toEqual([[0, 0]])
  })
})

describe('placementPreservesShape (honeycomb parity)', () => {
  it('allows shifts with even (dRow+dCol) — same anchor parity', () => {
    // anchor (0,1) parity = 1 (odd). Same-parity hover cells are valid.
    expect(placementPreservesShape([0, 1], { row: 0, col: 1 }, 'HONEYCOMB')).toBe(true)   // identity
    expect(placementPreservesShape([0, 1], { row: 0, col: 3 }, 'HONEYCOMB')).toBe(true)   // dCol=2
    expect(placementPreservesShape([0, 1], { row: 2, col: 1 }, 'HONEYCOMB')).toBe(true)   // dRow=2
    expect(placementPreservesShape([0, 1], { row: 1, col: 2 }, 'HONEYCOMB')).toBe(true)   // dRow+dCol=2
  })

  it('rejects shifts with odd (dRow+dCol) — flipped parity (the "I"-shape bug)', () => {
    expect(placementPreservesShape([0, 1], { row: 0, col: 2 }, 'HONEYCOMB')).toBe(false)  // dCol=1
    expect(placementPreservesShape([0, 1], { row: 1, col: 1 }, 'HONEYCOMB')).toBe(false)  // dRow=1
    expect(placementPreservesShape([0, 1], { row: 5, col: 9 }, 'HONEYCOMB')).toBe(false)  // (5+9)=14, anchor parity 1 → mismatch
  })

  it('allows any shift on the square lattice (no parity stagger)', () => {
    expect(placementPreservesShape([0, 0], { row: 1, col: 0 }, 'SQUARE')).toBe(true)
    expect(placementPreservesShape([0, 0], { row: 3, col: 4 }, 'SQUARE')).toBe(true)
  })

  it('the 6hb ring keeps its exact shape under an allowed shift, distorts under a forbidden one', () => {
    const base = relShape(SIX_HB)
    // Allowed: anchor (0,1)→(2,3), dRow+dCol = 4 (even). Congruent.
    const allowed = translateFootprint(SIX_HB, SIX_HB_ANCHOR, { row: 2, col: 3 })
    expect(relShape(allowed)).toEqual(base)
    // Forbidden: anchor (0,1)→(0,2), dRow+dCol = 1 (odd). NOT congruent (the "I").
    const forbidden = translateFootprint(SIX_HB, SIX_HB_ANCHOR, { row: 0, col: 2 })
    expect(relShape(forbidden)).not.toEqual(base)
  })
})

describe('validParityCandidates', () => {
  it('returns the cell itself when it already preserves the shape', () => {
    expect(validParityCandidates({ row: 2, col: 3 }, [0, 1], 'HONEYCOMB')).toEqual([[2, 3]])
  })

  it('returns the four edge-neighbours for a wrong-parity honeycomb hover', () => {
    // raw (0,2) is wrong parity for anchor (0,1); neighbours all flip back to parity 1.
    const cands = validParityCandidates({ row: 0, col: 2 }, [0, 1], 'HONEYCOMB')
    expect(cands).toEqual([[0, 1], [0, 3], [-1, 2], [1, 2]])
    // every candidate must itself preserve the shape (same parity as the anchor).
    for (const [r, c] of cands) {
      expect(placementPreservesShape([0, 1], { row: r, col: c }, 'HONEYCOMB')).toBe(true)
    }
  })

  it('returns the cell itself on the square lattice (every cell valid)', () => {
    expect(validParityCandidates({ row: 3, col: 5 }, [0, 0], 'SQUARE')).toEqual([[3, 5]])
  })
})

describe('latticeCompatible', () => {
  it('accepts any primitive onto an empty design', () => {
    expect(latticeCompatible('SQUARE', 'HONEYCOMB', true)).toBe(true)
    expect(latticeCompatible(null, 'HONEYCOMB', true)).toBe(true)
  })

  it('requires a matching lattice on a populated design', () => {
    expect(latticeCompatible('HONEYCOMB', 'HONEYCOMB', false)).toBe(true)
    expect(latticeCompatible('HONEYCOMB', 'SQUARE', false)).toBe(false)
    expect(latticeCompatible('SQUARE', 'HONEYCOMB', false)).toBe(false)
  })

  it('defaults a missing lattice to HONEYCOMB', () => {
    expect(latticeCompatible(undefined, 'HONEYCOMB', false)).toBe(true)
    expect(latticeCompatible('HONEYCOMB', undefined, false)).toBe(true)
  })
})
