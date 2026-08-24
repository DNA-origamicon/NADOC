import { beforeEach, describe, expect, it } from 'vitest'
import { initMenuFlyouts } from './menu_flyouts.js'

describe('menu flyout positioning', () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="menu-bar"><div class="menu-item"><button>Export</button><div class="dropdown"><div class="submenu-item">Atomistic<div class="submenu"><button>PDB</button></div></div></div></div></div>`
  })

  it('opens a submenu left when its right edge would leave the viewport', () => {
    const item = document.querySelector('.submenu-item')
    const submenu = document.querySelector('.submenu')
    item.getBoundingClientRect = () => ({ right: 780 })
    submenu.getBoundingClientRect = () => ({ width: 220 })
    initMenuFlyouts(document, { innerWidth: 900, addEventListener() {}, removeEventListener() {} })
    item.dispatchEvent(new PointerEvent('pointerover', { bubbles: true }))
    expect(submenu.classList.contains('submenu--open-left')).toBe(true)
  })

  it('keeps a submenu opening right when it fits', () => {
    const item = document.querySelector('.submenu-item')
    const submenu = document.querySelector('.submenu')
    item.getBoundingClientRect = () => ({ right: 200 })
    submenu.getBoundingClientRect = () => ({ width: 220 })
    initMenuFlyouts(document, { innerWidth: 900, addEventListener() {}, removeEventListener() {} })
    item.dispatchEvent(new PointerEvent('pointerover', { bubbles: true }))
    expect(submenu.classList.contains('submenu--open-left')).toBe(false)
  })
})
