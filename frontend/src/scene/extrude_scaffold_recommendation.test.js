import { describe, expect, it } from 'vitest'
import { recommendedExtrudeBp } from './extrude_scaffold_recommendation.js'

describe('extrude scaffold recommendation', () => {
  it('sizes one selected helix independently of the existing design', () => {
    expect(recommendedExtrudeBp({ targetNt: 7249, selectedCount: 1 })).toBe(7235)
    expect(recommendedExtrudeBp({ targetNt: 8064, selectedCount: 1 })).toBe(8050)
  })

  it('divides the target across only the current selection', () => {
    expect(recommendedExtrudeBp({ targetNt: 7249, selectedCount: 4 })).toBe(1798)
    expect(recommendedExtrudeBp({ targetNt: 8064, selectedCount: 4 })).toBe(2002)
  })

  it('returns zero without a selection', () => {
    expect(recommendedExtrudeBp({ targetNt: 7249, selectedCount: 0 })).toBe(0)
  })
})
