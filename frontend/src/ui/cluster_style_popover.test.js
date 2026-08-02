// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  initClusterStylePopover,
  normaliseHex,
  popoverPosition,
} from './cluster_style_popover.js'

// ── pure helpers ──────────────────────────────────────────────────────────────

describe('normaliseHex', () => {
  it('passes a well-formed hex through, lowercased', () => {
    expect(normaliseHex('#ff8800')).toBe('#ff8800')
    expect(normaliseHex('#FF8800')).toBe('#ff8800')
  })

  it('expands shorthand', () => {
    expect(normaliseHex('#ABC')).toBe('#aabbcc')
  })

  it('adds a missing #', () => {
    expect(normaliseHex('ff8800')).toBe('#ff8800')
  })

  it('converts a packed int (the renderer-side representation)', () => {
    expect(normaliseHex(0xff8800)).toBe('#ff8800')
    expect(normaliseHex(0x000011)).toBe('#000011')
  })

  it('falls back rather than letting the native input silently blacken it', () => {
    // This is the whole reason the helper exists: input.value = 'red' → '#000000'.
    for (const bad of ['red', '#GG0000', '', null, undefined, {}, NaN]) {
      expect(normaliseHex(bad, '#888888')).toBe('#888888')
    }
  })

  it('defaults the fallback to black when none is given', () => {
    expect(normaliseHex('red')).toBe('#000000')
  })
})

describe('popoverPosition', () => {
  const size = { width: 190, height: 120 }
  const viewport = { width: 1000, height: 800 }

  it('opens to the LEFT of the anchor (the panel is in the right sidebar)', () => {
    const { left } = popoverPosition({ left: 800, right: 830, top: 100 }, size, viewport)
    expect(left).toBe(800 - 190 - 8)
  })

  it('flips right when the left side would clip', () => {
    const { left } = popoverPosition({ left: 20, right: 50, top: 100 }, size, viewport)
    expect(left).toBe(50 + 8)
  })

  it('clamps to the margin when neither side fits', () => {
    const narrow = { width: 200, height: 800 }
    const { left } = popoverPosition({ left: 20, right: 50, top: 100 }, size, narrow)
    expect(left).toBeGreaterThanOrEqual(0)
    expect(left + size.width).toBeLessThanOrEqual(narrow.width)
  })

  it('tracks the anchor vertically when it fits', () => {
    expect(popoverPosition({ left: 800, right: 830, top: 250 }, size, viewport).top).toBe(250)
  })

  it('clamps upward so the bottom stays on-screen', () => {
    const { top } = popoverPosition({ left: 800, right: 830, top: 780 }, size, viewport)
    expect(top + size.height).toBeLessThanOrEqual(viewport.height)
  })

  it('never goes above the top margin', () => {
    expect(popoverPosition({ left: 800, right: 830, top: -50 }, size, viewport).top)
      .toBeGreaterThanOrEqual(0)
  })
})

// ── factory contract ──────────────────────────────────────────────────────────

describe('initClusterStylePopover', () => {
  let onPreview, onCommit, pop, anchor

  const colorInput   = () => pop._el.querySelector('input[type=color]')
  const opacityInput = () => pop._el.querySelector('input[type=range]')
  const resetBtn     = () => pop._el.querySelector('button')
  const fire = (elm, type) => elm.dispatchEvent(new Event(type, { bubbles: true }))

  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = ''
    onPreview = vi.fn()
    onCommit = vi.fn()
    pop = initClusterStylePopover({ onPreview, onCommit })
    anchor = document.createElement('button')
    anchor.getBoundingClientRect = () => ({ left: 800, right: 830, top: 100 })
    document.body.appendChild(anchor)
  })

  afterEach(() => {
    pop.destroy()
    vi.useRealTimers()
  })

  it('mounts once, to document.body, hidden', () => {
    expect(pop._el.parentElement).toBe(document.body)
    expect(pop._el.style.display).toBe('none')
  })

  it('openFor shows it with the cluster’s current values reflected', () => {
    pop.openFor('cA', anchor, { color: '#ff8800', opacity: 0.4 })
    expect(pop._el.style.display).toBe('block')
    expect(colorInput().value).toBe('#ff8800')
    expect(parseFloat(opacityInput().value)).toBeCloseTo(0.4)
    expect(pop.isOpenFor('cA')).toBe(true)
    expect(pop.isOpenFor('cB')).toBe(false)
  })

  it('shows a neutral swatch for a cluster with no colour set', () => {
    pop.openFor('cA', anchor, { color: null, opacity: 1 })
    expect(colorInput().value).toBe('#888888')   // not #000000
  })

  it('a slider drag previews but does NOT commit', () => {
    // The pin for "no network on input": committing at frame rate would rebuild
    // the sidebar list under the user's cursor.
    pop.openFor('cA', anchor, { opacity: 1 })
    opacityInput().value = '0.35'
    fire(opacityInput(), 'input')
    vi.advanceTimersByTime(20)                       // previews land on the next frame
    expect(onPreview).toHaveBeenCalledWith('cA', { opacity: 0.35 })
    vi.advanceTimersByTime(1000)
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('coalesces a burst of input events into ONE preview per frame', () => {
    // The lag fix. A drag across the colour map fires `input` far faster than
    // 60 Hz, and each preview is an O(nucleotides) repaint of the whole scene —
    // one per event is what made the picker crawl. Only the newest value matters.
    pop.openFor('cA', anchor, { opacity: 1 })
    for (const v of ['0.9', '0.8', '0.7', '0.6', '0.5']) {
      opacityInput().value = v
      fire(opacityInput(), 'input')
    }
    expect(onPreview).not.toHaveBeenCalled()         // nothing yet — still this frame
    vi.advanceTimersByTime(20)
    expect(onPreview).toHaveBeenCalledTimes(1)
    expect(onPreview).toHaveBeenCalledWith('cA', { opacity: 0.5 })
  })

  it('merges a colour and an opacity input in the same frame into one preview', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    colorInput().value = '#00ffcc'
    fire(colorInput(), 'input')
    opacityInput().value = '0.5'
    fire(opacityInput(), 'input')
    vi.advanceTimersByTime(20)
    expect(onPreview).toHaveBeenCalledTimes(1)
    expect(onPreview).toHaveBeenCalledWith('cA', { color: '#00ffcc', opacity: 0.5 })
  })

  it('still previews across frames during a long drag', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    for (const v of ['0.9', '0.5']) {
      opacityInput().value = v
      fire(opacityInput(), 'input')
      vi.advanceTimersByTime(20)
    }
    expect(onPreview).toHaveBeenCalledTimes(2)
  })

  it('commits once on change, after the debounce', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    opacityInput().value = '0.35'
    fire(opacityInput(), 'change')
    expect(onCommit).not.toHaveBeenCalled()
    vi.advanceTimersByTime(300)
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('cA', { opacity: 0.35 })
  })

  it('collapses a burst of changes (arrow-key stepping) into one commit', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    for (const v of ['0.9', '0.8', '0.7']) {
      opacityInput().value = v
      fire(opacityInput(), 'change')
      vi.advanceTimersByTime(50)
    }
    vi.advanceTimersByTime(300)
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('cA', { opacity: 0.7 })
  })

  it('merges a colour and an opacity change into one commit', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    colorInput().value = '#00ffcc'
    fire(colorInput(), 'change')
    opacityInput().value = '0.5'
    fire(opacityInput(), 'change')
    vi.advanceTimersByTime(300)
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('cA', { color: '#00ffcc', opacity: 0.5 })
  })

  it('the colour picker previews on input too', () => {
    pop.openFor('cA', anchor, {})
    colorInput().value = '#00ffcc'
    fire(colorInput(), 'input')
    vi.advanceTimersByTime(20)
    expect(onPreview).toHaveBeenCalledWith('cA', { color: '#00ffcc' })
    expect(onCommit).not.toHaveBeenCalled()
  })

  it("Reset sends the clear sentinel and full opacity, then closes", () => {
    pop.openFor('cA', anchor, { color: '#ff8800', opacity: 0.4 })
    resetBtn().click()
    // Reset closes, and closing FLUSHES the queued preview synchronously — a
    // discrete click must show immediately, not wait for its PATCH to round-trip.
    expect(onPreview).toHaveBeenCalledWith('cA', { color: '', opacity: 1 })
    expect(onCommit).toHaveBeenCalledWith('cA', { color: '', opacity: 1 })
    expect(pop.isOpenFor('cA')).toBe(false)
  })

  it('close() flushes a pending PREVIEW synchronously', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    opacityInput().value = '0.35'
    fire(opacityInput(), 'input')
    expect(onPreview).not.toHaveBeenCalled()
    pop.close()
    expect(onPreview).toHaveBeenCalledWith('cA', { opacity: 0.35 })
  })

  it('switching clusters DROPS the previous one’s queued preview', () => {
    // It would otherwise repaint cluster A one frame after the popover moved to B.
    pop.openFor('cA', anchor, { opacity: 1 })
    opacityInput().value = '0.35'
    fire(opacityInput(), 'input')
    pop.openFor('cB', anchor, { opacity: 1 })
    vi.advanceTimersByTime(20)
    expect(onPreview).not.toHaveBeenCalled()
  })

  it('close() flushes a pending commit rather than dropping it', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    opacityInput().value = '0.35'
    fire(opacityInput(), 'change')
    pop.close()
    expect(onCommit).toHaveBeenCalledWith('cA', { opacity: 0.35 })
  })

  it('Escape closes, flushes, and does not leak to the app’s global handler', () => {
    const global = vi.fn()
    document.addEventListener('keydown', global)
    pop.openFor('cA', anchor, { opacity: 1 })
    opacityInput().value = '0.35'
    fire(opacityInput(), 'change')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(pop.isOpenFor('cA')).toBe(false)
    expect(onCommit).toHaveBeenCalledWith('cA', { opacity: 0.35 })
    expect(global).not.toHaveBeenCalled()
    document.removeEventListener('keydown', global)
  })

  it('a pointerdown outside closes it', () => {
    pop.openFor('cA', anchor, {})
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(pop.isOpenFor('cA')).toBe(false)
  })

  it('a pointerdown INSIDE does not', () => {
    pop.openFor('cA', anchor, {})
    pop._el.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(pop.isOpenFor('cA')).toBe(true)
  })

  it('switching clusters flushes the previous one’s pending edit to the right id', () => {
    pop.openFor('cA', anchor, { opacity: 1 })
    opacityInput().value = '0.35'
    fire(opacityInput(), 'change')
    pop.openFor('cB', anchor, { opacity: 1 })
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('cA', { opacity: 0.35 })
  })

  it('closeIfMissing closes when its cluster is gone, keeps it when present', () => {
    pop.openFor('cA', anchor, {})
    pop.closeIfMissing(new Set(['cA', 'cB']))
    expect(pop.isOpenFor('cA')).toBe(true)
    pop.closeIfMissing(new Set(['cB']))
    expect(pop.isOpenFor('cA')).toBe(false)
  })

  it('destroy() removes the element and every document-level listener', () => {
    pop.openFor('cA', anchor, {})
    pop.destroy()
    expect(document.body.contains(pop._el)).toBe(false)
    // A stray capture-phase listener left behind would swallow Escape app-wide.
    const after = vi.fn()
    document.addEventListener('keydown', after)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(after).toHaveBeenCalledTimes(1)
    document.removeEventListener('keydown', after)
  })
})
