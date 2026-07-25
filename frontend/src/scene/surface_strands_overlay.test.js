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
    const a = [[[0, 0, 0]]], b = [[[1, 0, 0]]]
    emit(a, true)
    expect(emit(a, false)).toBe(true)   // highlight flipped
    expect(emit(b, false)).toBe(true)   // different result array
    expect(sink).toHaveBeenCalledTimes(3)
  })

  it('empty→empty is a no-op even with a fresh array (no CG rebuild per displayJob)', () => {
    const sink = vi.fn()
    const emit = createSurfaceStrandEmitter(sink)
    expect(emit([], false)).toBe(true)    // first emit syncs the renderer to "no strands"
    expect(emit([], false)).toBe(false)   // _draw's fresh [] must NOT rebuild again
    expect(emit([], false)).toBe(false)
    expect(sink).toHaveBeenCalledTimes(1)
  })

  it('still emits when leaving the empty state and when returning to it', () => {
    const sink = vi.fn()
    const emit = createSurfaceStrandEmitter(sink)
    const results = [[[0, 0, 0]]]
    emit([], false)
    expect(emit(results, false)).toBe(true)   // strands appeared
    expect(emit([], false)).toBe(true)        // display turned off → strands must be removed
    expect(sink).toHaveBeenCalledTimes(3)
  })
})
