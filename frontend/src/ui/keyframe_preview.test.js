import { expect, it, vi } from 'vitest'
import { initKeyframePreview } from './keyframe_preview.js'

function setup() {
  let tick, now = 0
  const win = { performance: { now: () => now }, requestAnimationFrame: fn => { tick = fn; return 1 }, cancelAnimationFrame: vi.fn() }
  const player = { play: vi.fn(async () => {}), pause: vi.fn(), stop: vi.fn(), seekTo: vi.fn(), settleFrame: vi.fn(async () => true), getKeyframeRange: () => ({ start: 2, end: 7 }) }
  const preview = initKeyframePreview({ player, getAnimation: () => ({ keyframes: [{ id: 'k', hold_duration_s: 4 }] }), window: win, onError: vi.fn() })
  return { preview, player, advance: async ms => { now += ms; await tick(now) } }
}
it('pauses and resumes one prepared interval, with first/last/stop inside its hold bounds', async () => {
  const { preview, player, advance } = setup()
  await preview.toggle('k'); await advance(1500)
  expect(preview.getState().status).toBe('playing')
  const time = preview.getState().time
  await preview.toggle('k')
  expect(preview.getState().status).toBe('paused')
  await preview.toggle('k')
  expect(preview.getState().time).toBe(time)
  expect(player.play).toHaveBeenCalledOnce()
  await preview.seek('k', -4); expect(player.seekTo).toHaveBeenLastCalledWith(3)
  await preview.seek('k', 4); expect(player.seekTo).toHaveBeenLastCalledWith(7)
  await preview.stop('k'); expect(player.seekTo).toHaveBeenLastCalledWith(3)
  expect(preview.getState().status).toBe('paused')
  preview.dispose()
})
it('scrubs while paused and replays from the start after reaching the end', async () => {
  const { preview, player } = setup()
  await preview.seek('k', .5)
  expect(player.seekTo).toHaveBeenLastCalledWith(5)
  await preview.seek('k', 1); await preview.toggle('k')
  expect(player.seekTo).toHaveBeenLastCalledWith(2.0000001)
  preview.dispose()
})
it('cancels slow preparation without publishing a stale frame or error', async () => {
  const { preview, player } = setup()
  let reject
  player.play.mockImplementation(() => new Promise((_resolve, failure) => { reject = failure }))
  const work = preview.toggle('k')
  expect(preview.getState().status).toBe('loading')
  await preview.stop('k')
  reject(new Error('cancelled fetch')); await work
  expect(preview.getState().id).toBeNull()
  expect(player.seekTo).not.toHaveBeenCalled()
})
it('the latest scrub wins when frame preparation finishes out of order', async () => {
  const { preview, player } = setup()
  await preview.seek('k', 0)
  let finish
  player.settleFrame.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const first = preview.seek('k', .25)
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  await preview.seek('k', .75)
  finish(false); await first
  expect(preview.getState()).toMatchObject({ id: 'k', status: 'paused', time: 6 })
})
