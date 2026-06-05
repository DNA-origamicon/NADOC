/**
 * Tests for scene/create_seam.js — Create Seam pure core + factory wiring.
 *
 * Oracles are derived by hand from the HC/SQ scaffold-crossover lookup tables
 * and the bow-direction sets, NOT by restating the implementation.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { isForward, scaffoldXoverNeighbor, nickBpForStrand, computeSeamPlacements, initCreateSeam } from './create_seam.js'

describe('isForward (pure)', () => {
  it('even (row+col) is FORWARD, odd is REVERSE', () => {
    expect(isForward(0, 0)).toBe(true)
    expect(isForward(2, 0)).toBe(true)
    expect(isForward(1, 0)).toBe(false)
    expect(isForward(0, 1)).toBe(false)
    expect(isForward(3, 1)).toBe(true)
  })
  it('handles negative grid coordinates (mod is normalized)', () => {
    expect(isForward(-1, 0)).toBe(false)
    expect(isForward(-2, 0)).toBe(true)
    expect(isForward(-1, -1)).toBe(true)
  })
})

describe('scaffoldXoverNeighbor (pure)', () => {
  // SQUARE (period 32). Forward cell (0,0): map entry 1_7:[+1,0] (mod 7 → row+1),
  // 1_4:[0,+1] (mod 4 → col+1), 1_0:[0,-1] (mod 0 → col-1).
  it('SQ forward cell resolves the lookup-table direction at the matching mod', () => {
    expect(scaffoldXoverNeighbor(0, 0, 7, false)).toEqual([1, 0])   // 1_7 → [+1,0]
    expect(scaffoldXoverNeighbor(0, 0, 4, false)).toEqual([0, 1])   // 1_4 → [0,+1]
    expect(scaffoldXoverNeighbor(0, 0, 0, false)).toEqual([0, -1])  // 1_0 → [0,-1]
  })
  it('SQ wraps bp by period (bp=39 ≡ mod 7)', () => {
    expect(scaffoldXoverNeighbor(0, 0, 39, false)).toEqual([1, 0])
  })
  it('SQ reverse cell uses the 0_* table (opposite directions)', () => {
    // Reverse cell (1,0): 0_7:[-1,0], 0_2:[+1,0].
    expect(scaffoldXoverNeighbor(1, 0, 7, false)).toEqual([0, 0])   // [-1,0]
    expect(scaffoldXoverNeighbor(1, 0, 2, false)).toEqual([2, 0])   // [+1,0]
  })
  it('returns null when bp mod period is not a crossover position', () => {
    expect(scaffoldXoverNeighbor(0, 0, 6, false)).toBeNull()  // mod 6 absent in SQ forward map
  })
  it('HC forward cell uses period 21 and the HC table', () => {
    // HC forward (0,0): 1_1:[0,+1], 1_8:[-1,0]. period 21 → bp 22 ≡ mod 1.
    expect(scaffoldXoverNeighbor(0, 0, 1, true)).toEqual([0, 1])
    expect(scaffoldXoverNeighbor(0, 0, 8, true)).toEqual([-1, 0])
    expect(scaffoldXoverNeighbor(0, 0, 22, true)).toEqual([0, 1])
    expect(scaffoldXoverNeighbor(0, 0, 1, false)).toBeNull()  // mod 1 absent in SQ forward map
  })
})

describe('nickBpForStrand (pure)', () => {
  // SQ bow-right set = {0,3,5,8,11,13,16,19,21,24,27,29}; mod 3 ∈, mod 7 ∉.
  it('bow-right mod: lowerBp = xoverBp-1; FORWARD→lower, REVERSE→lower+1', () => {
    // bp 3 ≡ mod 3 ∈ SQ bow-right → lowerBp = 2
    expect(nickBpForStrand(3, 'FORWARD', false)).toBe(2)
    expect(nickBpForStrand(3, 'REVERSE', false)).toBe(3)
  })
  it('non-bow-right mod: lowerBp = xoverBp', () => {
    // bp 7 ≡ mod 7 ∉ SQ bow-right → lowerBp = 7
    expect(nickBpForStrand(7, 'FORWARD', false)).toBe(7)
    expect(nickBpForStrand(7, 'REVERSE', false)).toBe(8)
  })
  it('HC bow-right set (period 21) differs from SQ', () => {
    // HC bow-right includes mod 2; bp 23 ≡ mod 2 → lowerBp = 22
    expect(nickBpForStrand(23, 'FORWARD', true)).toBe(22)
    expect(nickBpForStrand(23, 'REVERSE', true)).toBe(23)
    // mod 7 ∉ HC bow-right → lowerBp = 7
    expect(nickBpForStrand(7, 'FORWARD', true)).toBe(7)
  })
})

describe('computeSeamPlacements (pure core)', () => {
  // 4 scaffold helices in a square-lattice column (col 0, rows 0..3), each
  // covering bp 0..63 (two periods). The von-Neumann adjacency yields a linear
  // graph 0–1–2–3 → a Hamiltonian path; the single interior pair (helices 1,2)
  // gets one Holliday junction (2 placements, one per crossover bp).
  function sqColumnDesign(nRows = 4) {
    const rows = Array.from({ length: nRows }, (_, r) => r)
    return {
      lattice_type: 'SQUARE',
      helices: rows.map(r => ({ id: r, grid_pos: [r, 0] })),
      strands: rows.map(r => ({
        strand_type: 'scaffold',
        domains: [{ helix_id: r, start_bp: 0, end_bp: 63 }],
      })),
    }
  }

  it('returns [] for a missing design', () => {
    expect(computeSeamPlacements(null)).toEqual([])
    expect(computeSeamPlacements(undefined)).toEqual([])
  })

  it('returns [] when the component has fewer than 4 chainable helices', () => {
    expect(computeSeamPlacements(sqColumnDesign(3))).toEqual([])
  })

  it('places one Holliday junction (2 crossover bps) for the interior pair of a 4-helix column', () => {
    const placements = computeSeamPlacements(sqColumnDesign(4))
    expect(placements).toHaveLength(2)

    // Both placements are between the two interior helices (1 and 2).
    for (const p of placements) {
      const ids = [p.halfA.helix_id, p.halfB.helix_id].sort((a, b) => a - b)
      expect(ids).toEqual([1, 2])
      // The two halves sit on opposite strand polarities.
      expect(p.halfA.strand).not.toBe(p.halfB.strand)
      expect(p.halfA.index).toBe(p.halfB.index)
      // Nick bp lands within ±1 of the crossover index.
      expect(Math.abs(p.nickBpA - p.halfA.index)).toBeLessThanOrEqual(1)
      expect(Math.abs(p.nickBpB - p.halfB.index)).toBeLessThanOrEqual(1)
    }

    // The interior junction nearest the coverage midpoint (32) is the bp 34/35 pair.
    const indices = placements.map(p => p.halfA.index).sort((a, b) => a - b)
    expect(indices).toEqual([34, 35])
  })

  it('ignores staple strands (only scaffold coverage drives the graph)', () => {
    const d = sqColumnDesign(4)
    d.strands.push({ strand_type: 'staple', domains: [{ helix_id: 0, start_bp: 0, end_bp: 63 }] })
    expect(computeSeamPlacements(d)).toHaveLength(2)
  })
})

describe('initCreateSeam (factory wiring)', () => {
  let store, api
  beforeEach(() => {
    clearDom()
    mountIds(['menu-create-seam'])
    store = createMockStore({ currentDesign: null })
    api = { placeCrossoverBatch: vi.fn().mockResolvedValue(undefined) }
  })

  function sqColumnDesign() {
    const rows = [0, 1, 2, 3]
    return {
      lattice_type: 'SQUARE',
      helices: rows.map(r => ({ id: r, grid_pos: [r, 0] })),
      strands: rows.map(r => ({
        strand_type: 'scaffold',
        domains: [{ helix_id: r, start_bp: 0, end_bp: 63 }],
      })),
    }
  }

  it('does not call the API when there is no current design', async () => {
    initCreateSeam({ store, api })
    document.getElementById('menu-create-seam').click()
    await Promise.resolve()
    expect(api.placeCrossoverBatch).not.toHaveBeenCalled()
  })

  it('does not call the API when the design yields no placements', async () => {
    store.setState({ currentDesign: { lattice_type: 'SQUARE', helices: [], strands: [] } })
    initCreateSeam({ store, api })
    document.getElementById('menu-create-seam').click()
    await Promise.resolve()
    expect(api.placeCrossoverBatch).not.toHaveBeenCalled()
  })

  it('posts the computed placements when the design yields seam crossovers', async () => {
    store.setState({ currentDesign: sqColumnDesign() })
    initCreateSeam({ store, api })
    document.getElementById('menu-create-seam').click()
    await Promise.resolve()
    expect(api.placeCrossoverBatch).toHaveBeenCalledTimes(1)
    const arg = api.placeCrossoverBatch.mock.calls[0][0]
    expect(arg).toHaveLength(2)
    expect(arg[0]).toHaveProperty('halfA')
    expect(arg[0]).toHaveProperty('nickBpA')
  })
})
