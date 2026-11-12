import { afterEach, expect, it, vi } from 'vitest'
import { offlinePresentation } from './offline_presentation.js'
import { presentationHTML } from './compiled_presentation.js'

function setup() {
  document.body.innerHTML = presentationHTML('Talk', [])
  URL.createObjectURL = vi.fn(() => 'blob:video')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function () { Object.defineProperty(this, 'paused', { configurable: true, value: true }) })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function () {
    Object.defineProperty(this, 'paused', { configurable: true, value: false })
    this.dispatchEvent(new Event('playing')); return Promise.resolve()
  })
  offlinePresentation([1, 2, 3].map(n => ({ name: `Clip ${n}`, first: `data:image/png;base64,${n}`, last: `data:image/png;base64,last${n}`, video: 'data:video/webm;base64,AA==' })))
}
afterEach(() => { window.dispatchEvent(new Event('pagehide')); vi.restoreAllMocks(); document.body.replaceChildren() })
it('skips without waiting for the current clip and ignores its late completion', () => {
  setup(); document.getElementById('replay').click()
  const old = document.querySelector('video')
  document.getElementById('next').click()
  old.dispatchEvent(new Event('ended'))
  expect(document.getElementById('status').textContent).toBe('2 / 3 · Playing')
  expect(URL.revokeObjectURL).toHaveBeenCalled()
  document.querySelector('video').dispatchEvent(new Event('ended'))
  expect(document.getElementById('poster').src).toContain('last2')
  expect(document.getElementById('poster').hidden).toBe(false)
})
it('holds previous endpoints, replays, and pauses without changing slides', () => {
  setup(); document.getElementById('next').click()
  document.getElementById('back').click()
  expect(document.querySelector('video')).toBe(null)
  expect(document.getElementById('status').textContent).toBe('1 / 3 · Held')
  document.getElementById('replay').click()
  document.getElementById('pause').click()
  expect(document.getElementById('status').textContent).toBe('1 / 3 · Paused')
  document.getElementById('pause').click()
  expect(document.getElementById('status').textContent).toBe('1 / 3 · Playing')
})
