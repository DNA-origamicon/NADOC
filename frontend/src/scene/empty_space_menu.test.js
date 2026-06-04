import { describe, it, expect, vi } from 'vitest'
import { initEmptySpaceMenu } from './empty_space_menu.js'

function setup() {
  document.body.innerHTML = ''
  const menuEl = document.createElement('div')
  const extrudeBtn = document.createElement('button')
  menuEl.appendChild(extrudeBtn)
  const outside = document.createElement('div')
  document.body.append(menuEl, outside)
  const onExtrude = vi.fn()
  const menu = initEmptySpaceMenu({ menuEl, extrudeBtn, onExtrude })
  return { menu, menuEl, extrudeBtn, outside, onExtrude }
}

describe('initEmptySpaceMenu', () => {
  it('show() positions and displays the menu', () => {
    const { menu, menuEl } = setup()
    menu.show(120, 80)
    expect(menuEl.style.display).toBe('block')
    expect(menuEl.style.left).toBe('120px')
    expect(menuEl.style.top).toBe('80px')
  })

  it('hides on an outside pointerdown, stays on an inside one', () => {
    const { menu, menuEl, extrudeBtn, outside } = setup()
    menu.show(0, 0)
    extrudeBtn.dispatchEvent(new Event('pointerdown', { bubbles: true })) // inside menu
    expect(menuEl.style.display).toBe('block')
    outside.dispatchEvent(new Event('pointerdown', { bubbles: true }))    // outside menu
    expect(menuEl.style.display).toBe('none')
  })

  it('hides on Escape', () => {
    const { menu, menuEl } = setup()
    menu.show(0, 0)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(menuEl.style.display).toBe('none')
  })

  it('Extrude button hides the menu and fires onExtrude', () => {
    const { menu, menuEl, extrudeBtn, onExtrude } = setup()
    menu.show(0, 0)
    extrudeBtn.click()
    expect(onExtrude).toHaveBeenCalledTimes(1)
    expect(menuEl.style.display).toBe('none')
  })

  it('detaches dismiss listeners after teardown (no leak)', () => {
    const { menu, menuEl, outside } = setup()
    menu.show(0, 0)
    outside.dispatchEvent(new Event('pointerdown', { bubbles: true })) // teardown
    menuEl.style.display = 'block'                                     // pretend re-shown
    outside.dispatchEvent(new Event('pointerdown', { bubbles: true })) // stray — listener gone
    expect(menuEl.style.display).toBe('block')
  })
})
