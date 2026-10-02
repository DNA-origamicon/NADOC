import { afterEach, expect, it, vi } from 'vitest'
import { initVRDesktopDisplay, VR_DESKTOP_DISPLAY_KEY } from './vr_desktop_display.js'

afterEach(() => { document.body.innerHTML = ''; localStorage.clear() })
function setup(storage = localStorage) {
  document.body.innerHTML = '<button id="menu-help-vr-desktop-3d"></button><div id="vr-desktop-paused" hidden><button id="vr-desktop-resume"></button></div>'
  const setNativeVRActive = vi.fn(), setNativeVRDesktopEnabled = vi.fn()
  const controller = initVRDesktopDisplay({ document, storage, setNativeVRActive, setNativeVRDesktopEnabled })
  return { controller, setNativeVRActive, setNativeVRDesktopEnabled, toggle: document.querySelector('button'), notice: document.querySelector('div') }
}
it('persists a draw preference, clearly marks paused VR, and offers resume without ending VR', () => {
  const h = setup()
  expect(h.toggle.getAttribute('aria-pressed')).toBe('true')
  h.toggle.click()
  expect(localStorage.getItem(VR_DESKTOP_DISPLAY_KEY)).toBe('off')
  expect(h.notice.hidden).toBe(true)
  h.controller.setActive(true)
  expect(h.setNativeVRActive).toHaveBeenLastCalledWith(true)
  expect(h.setNativeVRDesktopEnabled).toHaveBeenLastCalledWith(false)
  expect(h.notice.hidden).toBe(false)
  document.getElementById('vr-desktop-resume').click()
  expect(h.notice.hidden).toBe(true)
  expect(h.setNativeVRDesktopEnabled).toHaveBeenLastCalledWith(true)
  expect(h.setNativeVRActive).toHaveBeenCalledTimes(1)
  h.toggle.click()
  h.controller.setActive(false)
  expect(h.notice.hidden).toBe(true)
  h.controller.dispose()
  const calls = h.setNativeVRDesktopEnabled.mock.calls.length
  h.toggle.click()
  expect(h.setNativeVRDesktopEnabled).toHaveBeenCalledTimes(calls)
})
it('restores an off preference on reopening, without pausing normal desktop viewing', () => {
  localStorage.setItem(VR_DESKTOP_DISPLAY_KEY, 'off')
  const h = setup()
  expect(h.toggle.getAttribute('aria-pressed')).toBe('false')
  expect(h.setNativeVRDesktopEnabled).toHaveBeenLastCalledWith(false)
  expect(h.notice.hidden).toBe(true)
  h.controller.dispose()
})
it('supports a session-only toggle when browser storage is unavailable', () => {
  const h = setup({ getItem() { throw Error('blocked') }, setItem() { throw Error('blocked') } })
  h.toggle.click(); h.controller.setActive(true)
  expect(h.notice.hidden).toBe(false)
  h.controller.dispose()
})
