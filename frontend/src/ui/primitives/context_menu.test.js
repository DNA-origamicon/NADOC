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
import { createContextMenu } from './context_menu.js'

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
