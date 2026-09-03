import { describe, expect, it } from 'vitest'
import { sliderCount, countSliderStep, manualStrandCount, conjugationSummary } from './nanoparticle_conjugate_logic.js'

describe('nanoparticle conjugation coverage controls', () => {
  it('preserves the exact low-valency 1, 2, and 3 ticks', () => {
    expect([0, 1, 2].map(step => sliderCount(step, 100))).toEqual([1, 2, 3])
  })
  it('maps percentage ticks against chemistry capacity', () => {
    expect([5, 6, 7, 8].map(step => sliderCount(step, 40))).toEqual([10, 20, 30, 40])
    expect(countSliderStep(30, 40)).toBe(7)
  })
  it('reports density and spacing from spherical surface area', () => {
    const result = conjugationSummary(10, { surface_area_nm2: 100, estimated_capacity: 20 })
    expect(result).toEqual({ count: 10, density: 0.1, spacing: Math.sqrt(10), capacity: 20 })
  })
  it('allows typed counts above the estimated slider capacity', () => {
    expect(manualStrandCount(47)).toBe(47)
  })
  it('normalizes invalid and out-of-safety-range typed counts', () => {
    expect(manualStrandCount(0)).toBe(1)
    expect(manualStrandCount(10001)).toBe(10000)
  })
})
