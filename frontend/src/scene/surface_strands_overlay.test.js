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

  // Preview chains are rebuilt per _draw, so identity always misses. One card edit
  // calls _draw three times (setHighlight, setShapePreview, update); without a content
  // key that was three full design rebuilds for one keystroke.
  it('dedupes preview redraws by content key, not array identity', () => {
    const sink = vi.fn()
    const emit = createSurfaceStrandEmitter(sink)
    const key = 'preview|circle|100|3000|1'
    expect(emit([[[0, 0, 0]]], true, key)).toBe(true)
    expect(emit([[[0, 0, 0]]], true, key)).toBe(false)  // fresh array, same geometry
    expect(emit([[[0, 0, 0]]], true, key)).toBe(false)
    expect(sink).toHaveBeenCalledTimes(1)
  })

  it('re-emits when the preview key or highlight changes', () => {
    const sink = vi.fn()
    const emit = createSurfaceStrandEmitter(sink)
    emit([[[0, 0, 0]]], true, 'preview|a')
    expect(emit([[[1, 0, 0]]], true, 'preview|b')).toBe(true)   // spec changed
    expect(emit([[[1, 0, 0]]], false, 'preview|b')).toBe(true)  // highlight flipped
    expect(sink).toHaveBeenCalledTimes(3)
  })

  it('crossing between preview and results always emits', () => {
    const sink = vi.fn()
    const emit = createSurfaceStrandEmitter(sink)
    const results = [[[9, 9, 9]]]
    emit([[[0, 0, 0]]], true, 'preview|a')
    expect(emit(results, false)).toBe(true)                     // job displayed
    expect(emit(results, false)).toBe(false)                    // redraw of same results
    expect(emit([[[0, 0, 0]]], true, 'preview|a')).toBe(true)   // display off → preview back
    expect(sink).toHaveBeenCalledTimes(3)
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
