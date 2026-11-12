import { expect, it, vi } from 'vitest'
import { compiledTimelineTime, createCompiledInspection } from './compiled_inspection.js'

it('maps a paused video to its encoded sample and held endpoints to their exact time', () => {
  const compiled = { animation: { fps: 10 }, ranges: [{ start: 2, end: 5 }] }
  expect(compiledTimelineTime(compiled, { index: 0, time: 1.29, atEnd: false })).toBe(3.2)
  expect(compiledTimelineTime(compiled, { index: 0, time: 2.9, atEnd: true })).toBe(5)
  expect(() => compiledTimelineTime(compiled, { index: -1, time: 0 })).toThrow()
})
function setup() {
  const player = { play: vi.fn(async () => {}), pause: vi.fn(), stop: vi.fn(), cancelBake: vi.fn(),
    seekTo: vi.fn(), settleFrame: vi.fn(async () => true), getBounce: () => true, getLoopMode: () => true,
    getDisablePoses: () => true, setBounce: vi.fn(), setLoopMode: vi.fn(), setDisablePoses: vi.fn() }
  const compiled = { animation: { fps: 10, keyframes: [{}] }, ranges: [{ start: 0, end: 3 }], initialCamera: { tag: 'compiled' } }
  const applyCamera = vi.fn(), captureCamera = () => ({ tag: 'editor' })
  const controller = createCompiledInspection({ player, captureCamera, applyCamera, isCurrent: () => true })
  return { player, compiled, controller, applyCamera }
}
it('waits for live data, restores the compiled camera basis, and leaves the player paused for orbiting', async () => {
  const f = setup()
  await f.controller.inspect(f.compiled, { index: 0, time: 1.25 })
  expect(f.applyCamera).toHaveBeenCalledWith({ tag: 'compiled' })
  expect(f.player.seekTo).toHaveBeenCalledWith(1.2)
  expect(f.player.setDisablePoses).toHaveBeenLastCalledWith(true)
  f.controller.release()
  expect(f.player.stop).toHaveBeenCalledOnce()
  expect(f.player.setBounce).toHaveBeenLastCalledWith(true)
})
it('cancels a slow handoff without allowing a late seek to replace the video', async () => {
  const f = setup(); let resolve
  f.player.play.mockImplementation(() => new Promise(r => { resolve = r }))
  const pending = f.controller.inspect(f.compiled, { index: 0, time: 1 })
  await Promise.resolve()
  f.controller.release(); resolve()
  expect(await pending).toBe(false)
  expect(f.player.seekTo).not.toHaveBeenCalled()
  expect(f.applyCamera).toHaveBeenLastCalledWith({ tag: 'editor' })
})
it('keeps unavailable frames from being exposed and restores the prior camera', async () => {
  const f = setup(); f.player.settleFrame.mockResolvedValue(false)
  await expect(f.controller.inspect(f.compiled, { index: 0, time: 1 })).rejects.toThrow('not ready')
  expect(f.applyCamera).toHaveBeenLastCalledWith({ tag: 'editor' })
})

it('refuses a changed source before touching the live scene', async () => {
  const f = setup()
  const controller = createCompiledInspection({ player: f.player, isCurrent: () => false })
  await expect(controller.inspect(f.compiled, { index: 0, time: 1 })).rejects.toThrow('matching source')
  expect(f.player.play).not.toHaveBeenCalled()
})
it('does not stop a different animation started during normal app use', async () => {
  const f = setup()
  await f.controller.inspect(f.compiled, { index: 0, time: 1 })
  f.controller.onPlayerEvent({ type: 'stopped' })
  f.player.setDisablePoses.mockClear()
  f.controller.release()
  expect(f.player.stop).not.toHaveBeenCalled()
  expect(f.player.setDisablePoses).not.toHaveBeenCalled()
})

it('relinquishes a pending handoff when normal app use takes over the player', async () => {
  const f = setup(); let resolve
  f.player.play.mockImplementation(() => new Promise(r => { resolve = r }))
  const pending = f.controller.inspect(f.compiled, { index: 0, time: 1 })
  await Promise.resolve()
  f.controller.onPlayerEvent({ type: 'stopped' })
  resolve()
  expect(await pending).toBe(false)
  expect(f.player.stop).not.toHaveBeenCalled()
  expect(f.player.seekTo).not.toHaveBeenCalled()
})

it('inspects a selected clip using its original keyframe and timeline offset', async () => {
  const f = setup()
  f.compiled.animation.keyframes = [{ id: 'before' }, { id: 'selected' }]
  f.compiled.clipKeyframeIds = ['selected']; f.compiled.ranges = [{ start: 5, end: 8 }]
  f.player.getKeyframeRange = vi.fn(id => id === 'selected' ? { start: 5, end: 8 } : { start: 0, end: 5 })
  await f.controller.inspect(f.compiled, { index: 0, time: 1.25 })
  expect(f.player.seekTo).toHaveBeenCalledWith(6.2)
})
