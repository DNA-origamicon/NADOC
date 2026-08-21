import { describe, expect, it } from 'vitest'
import { buildIdtStrandNames } from './idt_order.js'

describe('buildIdtStrandNames', () => {
  it('numbers group strands by physical plate/well order', () => {
    const design = {
      strands: [
        { id: 'later', strand_type: 'staple' },
        { id: 'first', strand_type: 'staple' },
        { id: 'second', strand_type: 'staple' },
      ],
      overhangs: [],
      plate_layout: {
        wells: [
          { strand_id: 'later', plate: 1, row: 0, col: 0 },
          { strand_id: 'second', plate: 0, row: 0, col: 1 },
          { strand_id: 'first', plate: 0, row: 0, col: 0 },
        ],
        tubes: [],
      },
    }
    const groups = [{ name: 'Body', strandIds: ['later', 'first', 'second'] }]
    expect(buildIdtStrandNames(design, groups)).toEqual({
      first: 'Body_1', second: 'Body_2', later: 'Body_3',
    })
  })

  it('counts each group independently while following well order', () => {
    const design = {
      strands: ['cap2', 'body2', 'body1', 'cap1'].map(id => ({ id, strand_type: 'staple' })),
      overhangs: [],
      plate_layout: {
        wells: ['body1', 'cap1', 'body2', 'cap2'].map((strand_id, col) => (
          { strand_id, plate: 0, row: 0, col }
        )),
        tubes: [],
      },
    }
    const groups = [
      { name: 'Body', strandIds: ['body1', 'body2'] },
      { name: 'Cap', strandIds: ['cap1', 'cap2'] },
    ]
    expect(buildIdtStrandNames(design, groups)).toEqual({
      body1: 'Body_1', cap1: 'Cap_1', body2: 'Body_2', cap2: 'Cap_2',
    })
  })
})
