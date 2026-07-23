import { describe, it, expect, vi } from 'vitest'
import { deferrableContextMenu } from './right_click_menu.js'

// Minimal fake canvas: records listeners so the test can dispatch synthetic events
// deterministically without a real DOM.
function makeCanvas() {
  const listeners = new Map() // `${type}:${capture}` -> Set<fn>
  const key = (type, capture) => `${type}:${!!capture}`
  return {
    listeners,
    addEventListener(type, fn, opts) {
      const cap = typeof opts === 'object' ? !!opts.capture : !!opts
      const k = key(type, cap)
      if (!listeners.has(k)) listeners.set(k, new Set())
      listeners.get(k).add(fn)
    },
    removeEventListener(type, fn, opts) {
      const cap = typeof opts === 'object' ? !!opts.capture : !!opts
      listeners.get(key(type, cap))?.delete(fn)
    },
    dispatch(type, ev, capture = false) {
      for (const fn of listeners.get(key(type, capture)) ?? []) fn(ev)
    },
    count(type, capture = false) {
      return listeners.get(key(type, capture))?.size ?? 0
    },
  }
}

const ctxEvent = ({ buttons }) => ({ buttons, preventDefault: vi.fn() })

describe('deferrableContextMenu', () => {
  it('runs the body immediately when the button is already released (Windows/mac)', () => {
    const canvas = makeCanvas()
    const body = vi.fn()
    const handler = deferrableContextMenu(canvas, body)

    const e = ctxEvent({ buttons: 0 }) // released at contextmenu time
    handler(e)

    expect(e.preventDefault).toHaveBeenCalledOnce()
    expect(body).toHaveBeenCalledOnce()
    expect(body).toHaveBeenCalledWith(e)
    expect(canvas.count('pointerup')).toBe(0) // no deferral registered
  })

  it('defers to pointerup when the right button is still held (Linux press-time)', () => {
    const canvas = makeCanvas()
    const body = vi.fn()
    const handler = deferrableContextMenu(canvas, body)

    const e = ctxEvent({ buttons: 2 }) // right button still down
    handler(e)

    expect(e.preventDefault).toHaveBeenCalledOnce()
    expect(body).not.toHaveBeenCalled() // nothing shown at press time
    expect(canvas.count('pointerup')).toBe(1)

    const up = { clientX: 40, clientY: 12 }
    canvas.dispatch('pointerup', up)

    expect(body).toHaveBeenCalledOnce()
    expect(body).toHaveBeenCalledWith(up) // body sees the release position
    expect(canvas.count('pointerup')).toBe(0)      // listener cleaned up
    expect(canvas.count('pointercancel')).toBe(0)
  })

  it('cancels the deferral without running the body on pointercancel', () => {
    const canvas = makeCanvas()
    const body = vi.fn()
    const handler = deferrableContextMenu(canvas, body)

    handler(ctxEvent({ buttons: 2 }))
    canvas.dispatch('pointercancel', {})

    expect(body).not.toHaveBeenCalled()
    expect(canvas.count('pointerup')).toBe(0)
    expect(canvas.count('pointercancel')).toBe(0)
  })

  it('registers deferred listeners in the requested phase', () => {
    const canvas = makeCanvas()
    const handler = deferrableContextMenu(canvas, vi.fn(), { capture: true })
    handler(ctxEvent({ buttons: 2 }))
    expect(canvas.count('pointerup', true)).toBe(1)
    expect(canvas.count('pointerup', false)).toBe(0)
  })
})
