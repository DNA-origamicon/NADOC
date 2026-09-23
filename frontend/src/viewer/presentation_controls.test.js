import { it, expect, vi, afterEach } from 'vitest'
import { initPresentationControls } from './presentation_controls.js'
afterEach(() => { document.body.innerHTML = '' })
it('anchors a persistent indicator to the canvas and toggles perspective accessibly', async () => {
  document.body.innerHTML = '<div id="canvas-area"></div>'
  const onPerspective = vi.fn(), onEnd = vi.fn()
  const controls = initPresentationControls({ onPerspective, onEnd })
  const bar = document.querySelector('#canvas-area #presentation-controls'), button = bar.querySelector('.presentation-perspective')
  expect(bar.hidden).toBe(true); controls.setActive(true)
  expect(bar.textContent).toContain('Presenting'); expect(button.textContent.trim()).toBe('')
  expect(button.title).toContain('follow your camera'); button.click()
  await vi.waitFor(() => expect(button.getAttribute('aria-pressed')).toBe('true'))
  expect(onPerspective).toHaveBeenCalledWith(true)
  button.click(); await vi.waitFor(() => expect(button.getAttribute('aria-pressed')).toBe('false'))
  expect(onPerspective).toHaveBeenLastCalledWith(false)
  controls.setActive(true); expect(bar.hidden).toBe(false)
  bar.querySelector('[data-end-presentation]').click(); await vi.waitFor(() => expect(onEnd).toHaveBeenCalledOnce())
  controls.setActive(false); expect(bar.hidden).toBe(true); controls.dispose()
  expect(document.getElementById('presentation-controls')).toBeNull()
})
it('retains the off state and surfaces a failed camera request without removing the presentation', async () => {
  const controls = initPresentationControls({ onPerspective: async () => { throw new Error('Camera unavailable') }, onEnd: vi.fn() })
  controls.setActive(true); document.querySelector('.presentation-perspective').click()
  await vi.waitFor(() => expect(document.querySelector('.presentation-error').textContent).toBe('Camera unavailable'))
  expect(controls.perspective).toBe(false); expect(document.querySelector('#presentation-controls').hidden).toBe(false)
  controls.dispose()
})
