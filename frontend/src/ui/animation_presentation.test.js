import { afterEach, expect, it, vi } from 'vitest'
import { initAnimationPresentation } from './animation_presentation.js'

let controller
let clock, frames, player, viewport, animation, part
async function step(ms) {
  clock += ms
  const pending = [...frames.values()]; frames.clear()
  for (const callback of pending) await callback(clock)
}
function setup() {
  document.body.innerHTML = '<section id="panel"></section><div id="viewport"></div>'
  viewport = document.getElementById('viewport')
  clock = 0; frames = new Map(); let next = 0, time = 0
  vi.spyOn(window.performance, 'now').mockImplementation(() => clock)
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(fn => { frames.set(++next, fn); return next })
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(id => frames.delete(id))
  animation = { loop: true, keyframes: [1, 2, 3].map(id => ({ id, transition_duration_s: 1, hold_duration_s: 1 })) }
  part = true
  player = { play: vi.fn(async () => { time = 0; controller.onPlayerEvent({ type: 'stopped' }) }),
    pause: vi.fn(), stop: vi.fn(), seekTo: vi.fn(t => { time = t }), settleFrame: vi.fn(async () => true),
    getCurrentTime: () => time, getBounce: () => true, getLoopMode: () => true,
    getDisablePoses: () => true, setBounce: vi.fn(), setLoopMode: vi.fn(), setDisablePoses: vi.fn() }
  controller = initAnimationPresentation({ host: document.getElementById('panel'), viewport, player,
    getAnimation: () => animation, isPart: () => part, stopPreview: vi.fn(), onError: vi.fn() })
}
afterEach(() => { controller?.dispose(); vi.restoreAllMocks(); document.body.replaceChildren() })

it('plays one keyframe at a time, goes back, and exits after the final hold', async () => {
  setup(); await controller.start()
  await step(2000)
  expect(player.getCurrentTime()).toBe(2)
  expect(viewport.classList.contains('animation-presentation-active')).toBe(true)
  await step(5000)
  expect(player.getCurrentTime()).toBe(2)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }))
  await step(2000)
  expect(player.getCurrentTime()).toBe(4)
  viewport.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true }))
  expect(player.getCurrentTime()).toBe(2)
  await Promise.resolve()
  await step(2000)
  expect(player.getCurrentTime()).toBe(2)
  viewport.click(); await step(2000)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' })); await step(2000)
  expect(player.getCurrentTime()).toBe(6)
  expect(viewport.classList.contains('animation-presentation-active')).toBe(false)
  expect(player.setBounce).toHaveBeenLastCalledWith(true)
  expect(player.setLoopMode).toHaveBeenLastCalledWith(true)
  expect(player.setDisablePoses).toHaveBeenLastCalledWith(true)
  expect(animation.loop).toBe(true)
})

it('Esc cancels preparation without late playback or layout changes', async () => {
  setup(); let resolve
  player.play.mockImplementation(() => new Promise(r => { resolve = r }))
  const pending = controller.start()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  resolve(); await pending; await step(5000)
  expect(player.seekTo).not.toHaveBeenCalled()
  expect(document.body.classList.contains('animation-presentation-mode')).toBe(false)
})

it('hides for assemblies and disables empty animations', async () => {
  setup(); part = false; controller.refresh()
  expect(document.querySelector('button').hidden).toBe(true)
  await controller.start(); expect(player.play).not.toHaveBeenCalled()
  part = true; animation.keyframes = []; controller.refresh()
  expect(document.querySelector('button').disabled).toBe(true)
})

it('exits when native fullscreen is dismissed and consumes editor gestures', async () => {
  setup()
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: viewport })
  viewport.requestFullscreen = vi.fn(async () => {})
  await controller.start()
  const click = vi.fn(); viewport.addEventListener('pointerdown', click)
  viewport.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
  expect(click).not.toHaveBeenCalled()
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
  document.dispatchEvent(new Event('fullscreenchange'))
  expect(document.body.classList.contains('animation-presentation-mode')).toBe(false)
})

it('restores the editor when preparation fails or is cancelled', async () => {
  setup()
  player.play.mockRejectedValue(new Error('Missing trajectory'))
  await controller.start()
  expect(document.body.classList.contains('animation-presentation-mode')).toBe(false)
  expect(document.querySelector('button').disabled).toBe(false)
  player.play.mockImplementation(async () => { controller.onPlayerEvent({ type: 'baking_cancelled' }) })
  await controller.start()
  expect(document.body.classList.contains('animation-presentation-mode')).toBe(false)
})

it('supports viewport fallback when fullscreen is denied and stops on document teardown', async () => {
  setup()
  viewport.requestFullscreen = vi.fn().mockRejectedValue(new Error('Denied'))
  await controller.start()
  expect(document.body.classList.contains('animation-presentation-mode')).toBe(true)
  controller.onPlayerEvent({ type: 'stopped' })
  expect(document.body.classList.contains('animation-presentation-mode')).toBe(false)
})

it('interrupts a transition and a hold on forward input, and exits when skipping the last frame', async () => {
  setup(); await controller.start(); await step(250)
  viewport.click()
  expect(player.getCurrentTime()).toBe(2)
  await Promise.resolve(); await step(1500)
  expect(player.getCurrentTime()).toBe(3.5)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
  expect(player.getCurrentTime()).toBe(4)
  await Promise.resolve(); await step(250)
  expect(player.getCurrentTime()).toBe(4.25)
  viewport.click()
  expect(viewport.classList.contains('animation-presentation-active')).toBe(false)
  await step(5000)
  expect(player.getCurrentTime()).toBe(4.25)
})

it('Left jumps directly to the previous endpoint and waits, including at the first frame', async () => {
  setup(); await controller.start(); await step(2000)
  viewport.click(); await step(500)
  player.seekTo.mockClear()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
  expect(player.seekTo).toHaveBeenCalledExactlyOnceWith(2)
  await Promise.resolve(); await step(5000)
  expect(player.seekTo).toHaveBeenCalledTimes(1)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
  expect(player.getCurrentTime()).toBe(2)
})

it('rapid navigation supersedes a frame still waiting for scene work', async () => {
  setup(); await controller.start()
  let settle
  player.settleFrame.mockImplementationOnce(() => new Promise(resolve => { settle = resolve }))
  const pending = step(500)
  viewport.click()
  expect(player.getCurrentTime()).toBe(2)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
  expect(player.getCurrentTime()).toBe(2)
  settle(true); await pending; await Promise.resolve(); await step(5000)
  expect(player.getCurrentTime()).toBe(2)
  expect(frames.size).toBe(0)
})
