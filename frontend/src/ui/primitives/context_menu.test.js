/**
 * Unit tests for the shared createContextMenu primitive.
 *
 * Focus: the `{ type: 'custom', el }` passthrough item type added for
 * ISSUE-1 Phase 2a-orientation (the overhang-orientation menu embeds a
 * hover-flyout submenu the primitive can't express). Also pins that an
 * outside click into a custom item's subtree does NOT dismiss the menu
 * (the flyout is a DOM child of the menu).
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { createContextMenu, placeMenu } from './context_menu.js'

const flush = () => new Promise((r) => setTimeout(r, 0))

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('createContextMenu — custom item passthrough', () => {
  it('appends the caller-owned element into the menu', () => {
    const custom = document.createElement('div')
    custom.id = 'my-flyout'
    custom.textContent = 'Representation ▸'
    createContextMenu({ x: 0, y: 0, items: [{ type: 'custom', el: custom }] })

    const menu = document.querySelector('.context-menu')
    expect(menu).toBeTruthy()
    expect(menu.contains(custom)).toBe(true)
    // A custom item is NOT a clickable menu item (no .context-menu__item wrapper).
    expect(document.querySelector('.context-menu__item')).toBeFalsy()
  })

  it('tolerates a custom item with no el (renders nothing for it)', () => {
    createContextMenu({ x: 0, y: 0, items: [{ type: 'custom' }, { label: 'Real', onClick: vi.fn() }] })
    const items = document.querySelectorAll('.context-menu__item')
    expect(items.length).toBe(1)
    expect(items[0].textContent.trim()).toBe('Real')
  })

  it('does not dismiss the menu when a click lands inside a custom item', async () => {
    const custom = document.createElement('div')
    const inner = document.createElement('span')
    custom.appendChild(inner)
    createContextMenu({ x: 0, y: 0, items: [{ type: 'custom', el: custom }] })
    await flush() // outside-click listener is bound on the next tick

    inner.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(document.querySelector('.context-menu')).toBeTruthy()
  })

  it('dismisses on a genuine outside click', async () => {
    createContextMenu({ x: 0, y: 0, items: [{ label: 'A', onClick: vi.fn() }] })
    await flush()
    document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(document.querySelector('.context-menu')).toBeFalsy()
  })
})

// ── placeMenu (pure viewport fitting) ────────────────────────────────────────
// Ported from the 3D viewport's _placeMenu when the two strand menus were folded
// onto this primitive; without these rules the tall strand menu was clipped.
describe('placeMenu', () => {
  const VP = { viewportW: 1000, viewportH: 800 }

  it('leaves a menu that already fits exactly where it was anchored', () => {
    expect(placeMenu({ x: 100, y: 100, width: 200, height: 300, ...VP }))
      .toEqual({ left: 100, top: 100, maxHeight: null })
  })

  it('shifts left when it would overflow the right edge', () => {
    const { left } = placeMenu({ x: 950, y: 100, width: 200, height: 300, ...VP })
    expect(left).toBe(1000 - 200 - 8)
  })

  it('grows upward instead of clipping at the bottom edge', () => {
    const { top } = placeMenu({ x: 100, y: 700, width: 200, height: 300, ...VP })
    expect(top).toBe(800 - 300 - 8)
  })

  it('caps and scrolls a menu taller than the viewport', () => {
    const r = placeMenu({ x: 100, y: 400, width: 200, height: 2000, ...VP })
    expect(r.maxHeight).toBe(800 - 16)
    expect(r.top).toBe(8)
  })

  it('never lands closer than the margin to the top or left edge', () => {
    const r = placeMenu({ x: -50, y: -50, width: 200, height: 100, ...VP })
    expect(r.left).toBe(8)
    expect(r.top).toBe(8)
  })

  it('clamps left to the margin when the menu is wider than the viewport', () => {
    const { left } = placeMenu({ x: 10, y: 10, width: 2000, height: 100, ...VP })
    expect(left).toBe(8)
  })

  it('honours a custom margin', () => {
    const { left } = placeMenu({ x: 995, y: 10, width: 200, height: 100, margin: 20, ...VP })
    expect(left).toBe(1000 - 200 - 20)
  })
})
