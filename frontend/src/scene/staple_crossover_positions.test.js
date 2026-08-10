import { describe, expect, it } from 'vitest'
import { stapleCrossoverNeighbor } from './staple_crossover_positions.js'

describe('stapleCrossoverNeighbor', () => {
  it('maps the reported square bp 87 site to exactly cell (17,26)', () => {
    expect(stapleCrossoverNeighbor('SQUARE', 16, 26, 87)).toEqual([17, 26])
  })

  it('returns no candidate at a non-crossover bp', () => {
    expect(stapleCrossoverNeighbor('SQUARE', 16, 26, 86)).toBeNull()
  })
})
