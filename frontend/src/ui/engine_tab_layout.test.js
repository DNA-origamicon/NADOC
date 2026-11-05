// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { initEngineTabLayout } from './engine_tab_layout.js'

it('collapses on overflow, restores labels after widening, and observes late badges', async () => {
  let resize
  const disconnect = vi.fn()
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback) { resize = callback }
    observe() {}
    disconnect() { disconnect() }
  })
  const mount = document.createElement('div')
  mount.style.cssText = 'padding:0 6px;column-gap:2px'
  mount.innerHTML = '<button class="engine-selector-btn"><span>CanDo</span></button><button class="engine-selector-btn"><span>oxDNA</span></button>'
  document.body.append(mount)
  for (const label of mount.querySelectorAll('span')) Object.defineProperty(label, 'scrollWidth', { value: 40 })
  let width = 140
  mount.getBoundingClientRect = () => ({ width })
  const layout = initEngineTabLayout(mount)
  expect(mount.classList.contains('is-compact')).toBe(false)
  width = 110
  resize()
  expect(mount.classList.contains('is-compact')).toBe(true)
  width = 140
  resize()
  expect(mount.classList.contains('is-compact')).toBe(false)
  const badge = document.createElement('span')
  Object.defineProperty(badge, 'scrollWidth', { value: 20 })
  mount.firstChild.append(badge)
  await Promise.resolve()
  expect(mount.classList.contains('is-compact')).toBe(true)
  badge.hidden = true
  await Promise.resolve()
  expect(mount.classList.contains('is-compact')).toBe(false)
  layout.dispose()
  expect(disconnect).toHaveBeenCalledOnce()
  mount.remove()
  vi.unstubAllGlobals()
})
