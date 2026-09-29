import { expect, it, vi } from 'vitest'
import { initTrajectoryInterpolationClock } from './trajectory_interpolation_clock.js'

const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
function fixture(ensure = vi.fn(async () => true), canBlend = () => true) {
  let time = 0, cursor = 0, callback = null
  const draw = vi.fn(), commit = vi.fn(i => { cursor = i }), buffering = vi.fn(), failed = vi.fn()
  const clock = initTrajectoryInterpolationClock({ current: () => cursor, count: () => 6, fps: 10,
    ensure, canBlend, draw, commit, buffering, failed, now: () => time,
    request: cb => { callback = cb; return 1 }, cancel: () => { callback = null } })
  return { clock, draw, commit, ensure, buffering, failed,
    async tick(t) { time = t; const cb = callback; callback = null; cb?.(t); await flush() },
    async start() { clock.start(); await flush() } }
}
it('prepares ahead and preserves residual time across saved-frame boundaries', async () => {
  const v = fixture(); await v.start()
  expect(v.ensure.mock.calls).toEqual([[0, 1, true], [1, 2, true]])
  await v.tick(96); await v.tick(112)
  expect(v.commit).toHaveBeenLastCalledWith(1)
  expect(v.draw).toHaveBeenLastCalledWith(1, 2, .12)
  await v.tick(224)
  expect(v.draw).toHaveBeenLastCalledWith(2, 3, .24)
  expect(v.buffering.mock.calls).toEqual([[true], [false]])
  expect(v.clock.stop()).toBe(true)
})
it('holds an exact endpoint on a cache miss and resumes without catch-up', async () => {
  let release
  const v = fixture(vi.fn(from => from === 1 ? new Promise(r => { release = r }) : true))
  await v.start(); await v.tick(50); await v.tick(112)
  expect(v.commit).toHaveBeenLastCalledWith(1)
  expect(v.buffering).toHaveBeenLastCalledWith(true)
  await v.tick(500); release(true); await flush(); await v.tick(525)
  expect(v.draw).toHaveBeenLastCalledWith(1, 2, .25)
  v.clock.stop()
})
it('ignores pending prefetch completion after pausing', async () => {
  let release
  const v = fixture(vi.fn(from => from === 1 ? new Promise(r => { release = r }) : true))
  await v.start(); await v.tick(112)
  expect(v.clock.stop()).toBe(false)
  release(true); await flush(); await v.tick(150)
  expect(v.commit).toHaveBeenCalledTimes(1)
  expect(v.draw).not.toHaveBeenCalled()
})
it('stops at the endpoint if upcoming preparation fails', async () => {
  const v = fixture(vi.fn(async from => from !== 1))
  await v.start(); await v.tick(50)
  expect(v.failed).not.toHaveBeenCalled()
  await v.tick(112)
  expect(v.commit).toHaveBeenLastCalledWith(1)
  expect(v.failed).toHaveBeenCalledOnce()
  v.clock.stop()
})
it('does not blend across stage boundaries or drain a suspended-tab backlog', async () => {
  const v = fixture(undefined, (_from, to) => to !== 2)
  await v.start(); await v.tick(112)
  expect(v.draw).not.toHaveBeenCalled()
  await v.tick(20000)
  expect(v.commit.mock.calls).toEqual([[1], [2]])
  await v.tick(20025)
  expect(v.draw).toHaveBeenLastCalledWith(2, 3, .25)
  v.clock.stop()
})
