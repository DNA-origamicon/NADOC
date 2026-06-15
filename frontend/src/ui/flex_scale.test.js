// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { clampBounds, valueToFraction, fractionToValue, initFlexScale } from './flex_scale.js'

describe('clampBounds', () => {
  it('orders, swaps reversed pairs, and never collapses the span', () => {
    expect(clampBounds(0.2, 1.0)).toEqual({ lo: 0.2, hi: 1.0 })
    expect(clampBounds(1.0, 0.2)).toEqual({ lo: 0.2, hi: 1.0 })   // swapped
    const eq = clampBounds(0.5, 0.5)
    expect(eq.lo).toBe(0.5)
    expect(eq.hi).toBeGreaterThan(0.5)                            // nudged apart
    expect(clampBounds(NaN, NaN)).toEqual({ lo: 0, hi: 1e-6 })    // NaN-safe
  })
})

describe('valueToFraction / fractionToValue', () => {
  it('round-trip within the range and clamp outside it', () => {
    expect(valueToFraction(0.5, 0, 1)).toBeCloseTo(0.5)
    expect(valueToFraction(-1, 0, 1)).toBe(0)        // clamp low
    expect(valueToFraction(2, 0, 1)).toBe(1)         // clamp high
    expect(valueToFraction(0.3, 1, 1)).toBe(0)       // zero span → 0
    expect(fractionToValue(0.25, 0, 4)).toBe(1)
    expect(fractionToValue(5, 0, 4)).toBe(4)         // clamp
    // inverse
    expect(fractionToValue(valueToFraction(1.3, 0.2, 2.2), 0.2, 2.2)).toBeCloseTo(1.3)
  })
})

describe('initFlexScale', () => {
  const SPEC = {
    'flex-scale': 'div', 'flex-scale-track': 'div',
    'flex-scale-handle-hi': 'div', 'flex-scale-handle-lo': 'div',
    'flex-scale-max': 'input', 'flex-scale-min': 'input', 'flex-scale-reset': 'button',
  }
  const $ = (id) => document.getElementById(id)
  beforeEach(() => { clearDom(); mountIds(SPEC) })
  afterEach(() => clearDom())

  it('show seeds inputs + handle positions with the data min→max and reveals; hide conceals', () => {
    const fs = initFlexScale({})
    fs.show(0.0, 1.0)
    expect($('flex-scale').style.display).not.toBe('none')
    expect($('flex-scale-min').value).toBe('0.00')
    expect($('flex-scale-max').value).toBe('1.00')
    expect($('flex-scale-handle-hi').style.top).toBe('0%')     // max at top
    expect($('flex-scale-handle-lo').style.top).toBe('100%')   // min at bottom
    fs.hide()
    expect($('flex-scale').style.display).toBe('none')
  })

  it('editing a bound emits the clamped (lo, hi)', () => {
    const cb = vi.fn()
    const fs = initFlexScale({ onBoundsChange: cb })
    fs.show(0.2, 1.0)
    $('flex-scale-max').value = '0.6'
    $('flex-scale-max').dispatchEvent(new Event('change'))
    expect(cb).toHaveBeenLastCalledWith(0.2, 0.6)
  })

  it('reset restores the data min→max and re-emits', () => {
    const cb = vi.fn()
    const fs = initFlexScale({ onBoundsChange: cb })
    fs.show(0.3, 1.1)
    $('flex-scale-min').value = '0.5'
    $('flex-scale-min').dispatchEvent(new Event('change'))
    cb.mockClear()
    $('flex-scale-reset').dispatchEvent(new Event('click'))
    expect(cb).toHaveBeenLastCalledWith(0.3, 1.1)
    expect($('flex-scale-min').value).toBe('0.30')
  })

  it('dragging the upper handle windows the range, recolours live, and repositions the handle', () => {
    const cb = vi.fn()
    const fs = initFlexScale({ onBoundsChange: cb })
    fs.show(0, 1)
    const track = $('flex-scale-track')
    track.getBoundingClientRect = () => ({ top: 0, height: 100, left: 0, right: 18, bottom: 100, width: 18, x: 0, y: 0 })

    $('flex-scale-handle-hi').dispatchEvent(new MouseEvent('pointerdown', { clientY: 0, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientY: 50 }))   // mid track → 0.5
    expect(cb).toHaveBeenLastCalledWith(0, 0.5)
    expect(fs.getBounds()).toEqual({ lo: 0, hi: 0.5 })
    expect($('flex-scale-handle-hi').style.top).toBe('50%')

    window.dispatchEvent(new MouseEvent('pointerup', {}))
    cb.mockClear()
    window.dispatchEvent(new MouseEvent('pointermove', { clientY: 20 }))   // drag ended → ignored
    expect(cb).not.toHaveBeenCalled()
  })

  it('dragging the lower handle cannot cross the upper handle', () => {
    const cb = vi.fn()
    const fs = initFlexScale({ onBoundsChange: cb })
    fs.show(0, 1)
    const track = $('flex-scale-track')
    track.getBoundingClientRect = () => ({ top: 0, height: 100, left: 0, right: 18, bottom: 100, width: 18, x: 0, y: 0 })

    $('flex-scale-handle-lo').dispatchEvent(new MouseEvent('pointerdown', { clientY: 100, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientY: 0 }))    // tries to drag lo to the top (1.0)
    const { lo, hi } = fs.getBounds()
    expect(hi).toBe(1)
    expect(lo).toBeLessThan(hi)            // clamped below hi by the min gap
    expect(lo).toBeGreaterThan(0.9)
  })

  it('tolerates a missing root (no DOM) without throwing', () => {
    clearDom()
    const fs = initFlexScale({})
    expect(() => { fs.show(0, 1); fs.hide() }).not.toThrow()
    expect(fs.isVisible()).toBe(false)
  })
})
