import { afterEach, describe, it, expect, vi } from 'vitest'
import { deferrableContextMenu } from './right_click_menu.js'

afterEach(() => { window.dispatchEvent(new Event('blur')); document.body.replaceChildren() })

function setup({ capture = false } = {}) {
  const canvas = document.createElement('canvas')
  document.body.appendChild(canvas)
  const body = vi.fn(e => e.stopPropagation())
  canvas.addEventListener('contextmenu', deferrableContextMenu(canvas, body, { capture }), capture)
  const fire = (type, options = {}, target = canvas) => {
    const event = new MouseEvent(type, {
      bubbles: true, cancelable: true, button: 2, buttons: type === 'pointerup' ? 0 : 2,
      clientX: 20, clientY: 20, ...options,
    })
    target.dispatchEvent(event)
    return event
  }
  return { canvas, body, fire }
}

describe('deferrableContextMenu', () => {
  it('opens a release-time right-click menu', () => {
    const { body, fire } = setup()
    fire('pointerdown')
    fire('pointerup')
    const e = fire('contextmenu', { buttons: 0 })
    expect(e.defaultPrevented).toBe(true)
    expect(body).toHaveBeenCalledExactlyOnceWith(e)
  })

  it.each([false, true])('defers a press-time menu until release finishes (capture=%s)', async capture => {
    const { canvas, body, fire } = setup({ capture })
    const orbitRelease = vi.fn()
    canvas.addEventListener('pointerup', orbitRelease)
    fire('pointerdown')
    fire('contextmenu')
    expect(body).not.toHaveBeenCalled()
    fire('pointerup')
    expect(orbitRelease).toHaveBeenCalledOnce()
    expect(body).not.toHaveBeenCalled()
    await Promise.resolve()
    expect(body).toHaveBeenCalledOnce()
    expect(body.mock.calls[0][0].type).toBe('contextmenu')
  })

  it.each(['press', 'release'])('suppresses a drag menu on %s-time platforms, including out-and-back drags', async timing => {
    const { body, fire } = setup()
    fire('pointerdown')
    if (timing === 'press') fire('contextmenu')
    fire('pointermove', { clientX: 100 })
    fire('pointermove', { clientX: 20 })
    fire('pointerup')
    if (timing === 'release') fire('contextmenu', { buttons: 0 })
    await Promise.resolve()
    expect(body).not.toHaveBeenCalled()
    // The following real click still opens normally.
    fire('pointerdown')
    fire('pointerup')
    fire('contextmenu', { buttons: 0 })
    expect(body).toHaveBeenCalledOnce()
  })

  it('tracks movement outside the canvas and tolerates small click jitter', () => {
    const { body, fire } = setup()
    fire('pointerdown')
    fire('pointermove', { clientX: 100 }, window)
    fire('pointerup', {}, window)
    fire('contextmenu', { buttons: 0 })
    expect(body).not.toHaveBeenCalled()
    fire('pointerdown')
    fire('pointerup', { clientX: 22 })
    fire('contextmenu', { buttons: 0, clientX: 22 })
    expect(body).toHaveBeenCalledOnce()
  })

  it.each(['pointercancel', 'blur'])('cancels a pending menu on %s', async type => {
    const { body, fire } = setup()
    fire('pointerdown')
    fire('contextmenu')
    fire(type, {}, window)
    fire('pointerup')
    fire('contextmenu', { buttons: 0 })
    await Promise.resolve()
    expect(body).not.toHaveBeenCalled()
  })

  it('delivers one menu event to multiple handlers without duplicate native/replayed menus', async () => {
    const { canvas, body, fire } = setup()
    const second = vi.fn()
    canvas.addEventListener('contextmenu', deferrableContextMenu(canvas, second))
    fire('pointerdown')
    fire('contextmenu')
    fire('pointerup')
    await Promise.resolve()
    fire('contextmenu', { buttons: 0 })
    expect(body).toHaveBeenCalledOnce()
    expect(second).toHaveBeenCalledOnce()
  })
})
