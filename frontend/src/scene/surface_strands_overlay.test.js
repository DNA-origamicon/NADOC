import { describe, expect, it, vi } from 'vitest'
import { createSurfaceStrandEmitter } from './surface_strands_overlay.js'

describe('surface-strand native renderer emission', () => {
  it('does not rebuild for repeated redraws of the same result chains', () => {
    const sink = vi.fn()
    const emit = createSurfaceStrandEmitter(sink)
    const results = [[[0, 0, 0], [0, 1, 0]]]
    expect(emit(results, false)).toBe(true)
    expect(emit(results, false)).toBe(false) // plane/card redraw: exact same results
    expect(sink).toHaveBeenCalledTimes(1)
  })

  it('emits when result identity or effective preview highlight changes', () => {
    const sink = vi.fn()
    const emit = createSurfaceStrandEmitter(sink)
    const a = [], b = []
    emit(a, true)
    expect(emit(a, false)).toBe(true)
    expect(emit(b, false)).toBe(true)
    expect(sink).toHaveBeenCalledTimes(3)
  })
})
