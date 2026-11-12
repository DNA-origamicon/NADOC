import { afterEach, expect, it, vi } from 'vitest'
import { initCompiledPresentationPlayer } from './compiled_presentation_player.js'

let ui
function setup() {
  document.body.innerHTML = '<main id="viewport"></main>'
  const player = { play: vi.fn(async () => {}), pause: vi.fn(), stop: vi.fn(), cancelBake: vi.fn(), seekTo: vi.fn(),
    settleFrame: vi.fn(async () => true), getBounce: () => true, getLoopMode: () => false, getDisablePoses: () => false,
    setBounce: vi.fn(), setLoopMode: vi.fn(), setDisablePoses: vi.fn() }
  const camera = { position: { fromArray: vi.fn() }, up: { fromArray: vi.fn() }, updateProjectionMatrix: vi.fn() }
  ui = initCompiledPresentationPlayer({ viewport: document.getElementById('viewport'), player, camera,
    controls: { target: { fromArray: vi.fn() }, update: vi.fn() },
    captureCamera: () => ({ position: [0, 0, 1], up: [0, 1, 0], target: [0, 0, 0], fov: 55 }), isCurrent: () => true })
  ui.open('about:blank', { animation: { fps: 10, keyframes: [{ id: 'a' }] }, ranges: [{ start: 0, end: 5 }] })
  const frame = document.querySelector('iframe'), post = vi.spyOn(frame.contentWindow, 'postMessage')
  frame.dispatchEvent(new Event('load'))
  const token = post.mock.calls[0][0].token
  const message = (command, state, source = frame.contentWindow, key = token) => window.dispatchEvent(new MessageEvent('message', {
    source, data: { type: 'nadoc-compiled', token: key, command, state },
  }))
  message('ready')
  return { player, frame, message, post }
}
afterEach(() => { ui?.dispose(); document.body.replaceChildren(); vi.restoreAllMocks() })
it('uses only its own iframe messages and returns to the retained video after inspection', async () => {
  const f = setup()
  f.message('snapshot', { index: 0, time: 1 }, window)
  f.message('snapshot', { index: 0, time: 1 }, f.frame.contentWindow, 'wrong-token')
  expect(f.player.play).not.toHaveBeenCalled()
  f.message('snapshot', { index: 0, time: 1.25 })
  await vi.waitFor(() => expect(document.querySelector('.compiled-inspect').textContent).toBe('Return to presentation'))
  expect(f.frame.hidden).toBe(true)
  expect(f.player.seekTo).toHaveBeenCalledWith(1.2)
  document.querySelector('.compiled-inspect').click()
  expect(f.frame.hidden).toBe(false)
  expect(f.post.mock.lastCall[0].command).toBe('resume')
})
it('keeps video available after failed live readiness', async () => {
  const f = setup(); f.player.settleFrame.mockResolvedValue(false)
  f.message('snapshot', { index: 0, time: 1 })
  await vi.waitFor(() => expect(document.querySelector('[role="status"]').textContent).toContain('not ready'))
  expect(f.frame.hidden).toBe(false)
  expect(document.querySelector('.compiled-inspect').disabled).toBe(false)
  expect(f.post.mock.lastCall[0].command).toBe('unlock')
})
it('cancels a pending live load and rejects its late result', async () => {
  const f = setup(); let finish
  f.player.play.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  f.message('snapshot', { index: 0, time: 1 })
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  document.querySelector('.compiled-cancel').click()
  finish(); await Promise.resolve(); await Promise.resolve()
  expect(f.player.seekTo).not.toHaveBeenCalled()
  expect(f.frame.hidden).toBe(false)
  expect(document.querySelector('[role="status"]').textContent).toContain('cancelled')
})

it('opens prepared video when randomUUID is unavailable on a plain HTTP origin', () => {
  vi.spyOn(crypto, 'randomUUID').mockImplementation(() => { throw new Error('Unavailable on HTTP') })
  const f = setup()
  expect(f.post.mock.calls[0][0].token).toMatch(/^[a-f0-9]{32}$/)
  expect(document.querySelector('.compiled-inspect').disabled).toBe(false)
})
