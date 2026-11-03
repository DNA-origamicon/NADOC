import { describe, expect, it } from 'vitest'
import { crossoverCellKey } from './crossover_cells.js'

describe('crossover neighbor cell identity', () => {
  it('keeps original and swept sections separate at identical local cells', () => {
    const original = { lattice_frame_id: 'original' }
    const sweep = { lattice_frame_id: 'sweep' }
    const cells = new Map([
      [crossoverCellKey(original, 0, 1), 'original-neighbor'],
      [crossoverCellKey(sweep, 0, 1), 'swept-neighbor'],
    ])
    expect(cells.get(crossoverCellKey(original, 0, 1))).toBe('original-neighbor')
    expect(cells.get(crossoverCellKey(sweep, 0, 1))).toBe('swept-neighbor')
    expect(cells.get(crossoverCellKey({ lattice_frame_id: 'other' }, 0, 1))).toBeUndefined()
  })

  it('preserves legacy unframed neighbor lookup without aliasing explicit frames', () => {
    expect(crossoverCellKey({}, 0, 1)).toBe(crossoverCellKey({ lattice_frame_id: null }, 0, 1))
    expect(crossoverCellKey({}, 0, 1)).not.toBe(crossoverCellKey({ lattice_frame_id: 'null' }, 0, 1))
    expect(crossoverCellKey({}, 0, 1)).not.toBe(crossoverCellKey({}, 1, 0))
  })
})
