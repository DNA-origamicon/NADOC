import { describe, it, expect } from 'vitest'
import { surfaceOpposesField } from './field_anchor_rules.js'

describe('surfaceOpposesField', () => {
  it('is true when the field presses straight into the surface', () => {
    // Surface normal +Z, field pushing down −Z → deposition, no strand anchor needed.
    expect(surfaceOpposesField({ dir: [0, 0, -1] }, { dir: [0, 0, 1] })).toBe(true)
  })

  it('is false when the field lifts off the surface', () => {
    expect(surfaceOpposesField({ dir: [0, 0, 1] }, { dir: [0, 0, 1] })).toBe(false)
  })

  it('is false when the field runs along the surface', () => {
    expect(surfaceOpposesField({ dir: [1, 0, 0] }, { dir: [0, 0, 1] })).toBe(false)
  })

  it('holds inside the ~25° cone and releases outside it', () => {
    const at = (deg) => {
      const r = (deg * Math.PI) / 180
      return { dir: [Math.sin(r), 0, -Math.cos(r)] }
    }
    expect(surfaceOpposesField(at(20), { dir: [0, 0, 1] })).toBe(true)
    expect(surfaceOpposesField(at(30), { dir: [0, 0, 1] })).toBe(false)
  })

  it('normalizes, so magnitude does not matter', () => {
    expect(surfaceOpposesField({ dir: [0, 0, -37] }, { dir: [0, 0, 0.001] })).toBe(true)
  })

  it('is false for missing or malformed vectors', () => {
    expect(surfaceOpposesField(null, { dir: [0, 0, 1] })).toBe(false)
    expect(surfaceOpposesField({ dir: [0, 0, -1] }, null)).toBe(false)
    expect(surfaceOpposesField({ dir: [0, -1] }, { dir: [0, 0, 1] })).toBe(false)
    expect(surfaceOpposesField({ dir: [0, 0, 0] }, { dir: [0, 0, 1] })).toBe(false)
  })
})
