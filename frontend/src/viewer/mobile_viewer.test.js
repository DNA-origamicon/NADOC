import { it, expect, vi, afterEach } from 'vitest'
import { mountMobileViewer } from './mobile_viewer.js'
afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = ''; document.body.className = '' })
it('waits until sign-in, tolerates denied orientation lock, and exposes graphics recovery', async () => {
  document.body.innerHTML = '<header></header><h1 id="title"></h1><main><canvas></canvas></main><dialog id="join" open></dialog>'
  vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(390)
  vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(844)
  const viewer = { mobile: true, current: {} }, dispose = mountMobileViewer({ viewer })
  const notice = document.querySelector('.mobile-landscape'), canvas = document.querySelector('canvas')
  expect(notice.hidden).toBe(true)
  document.querySelector('#join').removeAttribute('open')
  await Promise.resolve(); expect(notice.hidden).toBe(false)
  document.documentElement.requestFullscreen = vi.fn().mockRejectedValue(new Error('Unsupported'))
  document.querySelector('[data-fullscreen]').click()
  await vi.waitFor(() => expect(document.querySelector('[data-orientation-status]').textContent).toContain('rotate your phone'))
  document.querySelector('[data-dismiss]').click(); expect(notice.hidden).toBe(true)
  canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }))
  expect(document.querySelector('.mobile-recovery').hidden).toBe(false)
  canvas.dispatchEvent(new Event('webglcontextrestored'))
  expect(document.querySelector('.mobile-recovery').hidden).toBe(true)
  dispose(); expect(document.querySelector('.mobile-landscape')).toBeNull()
  expect(document.body.classList.contains('mobile-viewer')).toBe(false)
  delete document.documentElement.requestFullscreen
})
