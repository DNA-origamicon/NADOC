import { afterEach, expect, it, vi } from 'vitest'
import { createVRSimulationTrajectory } from './vr_simulation_trajectory.js'

let player
afterEach(() => { player?.dispose(); vi.useRealTimers() })
async function ready(available = 30) {
  vi.useFakeTimers()
  const frames = []
  const display = { showTrajectory: async (_job, _progress, { frame }) => { frames.push(frame); return { ok: true } },
    seekFullTrajectoryFrame: async frame => { frames.push(frame); return { ok: true } } }
  player = createVRSimulationTrajectory({ api: { getSnupiTrajectoryMeta: async () => ({ n_frames: available }) },
    controller: () => display, ensureFull: async () => {} })
  await player.select('snupi', 'job')
  player.configure(available > 1 ? { first: 7, last: 21, interval: 5 } : { first: 1, last: 1, interval: 1 })
  await player.load()
  return frames
}

it('stops at the last sampled frame by default, including an unsampled end', async () => {
  const frames = await ready()
  player.toggle()
  await vi.advanceTimersByTimeAsync(500)
  expect(frames).toEqual([6, 11, 16])
  expect(player.snapshot()).toMatchObject({ loop: false, playing: false, source: 17, index: 2 })
})

it('loops the selected interval repeatedly, then stops at its end when disabled during play', async () => {
  const frames = await ready()
  player.loop(); player.toggle()
  await vi.advanceTimersByTimeAsync(430)
  expect(frames).toEqual([6, 11, 16, 6, 11, 16, 6])
  expect(player.snapshot().playing).toBe(true)
  player.loop()
  await vi.advanceTimersByTimeAsync(500)
  expect(frames.slice(-3)).toEqual([6, 11, 16])
  expect(player.snapshot()).toMatchObject({ loop: false, playing: false, source: 17 })
})

it('pause halts repetition, reload preserves the choice, and another job resets it', async () => {
  const frames = await ready()
  player.loop(); player.toggle()
  await vi.advanceTimersByTimeAsync(250)
  player.pause()
  const drawn = frames.length
  await vi.advanceTimersByTimeAsync(1000)
  expect(frames).toHaveLength(drawn)
  player.configure({ interval: 7 }); await player.load()
  expect(player.snapshot()).toMatchObject({ loop: true, playing: false, source: 7 })
  await player.select('snupi', 'other-job')
  expect(player.snapshot()).toMatchObject({ loop: false, playing: false })
})

it('a single selected frame cannot start a looping timer', async () => {
  const frames = await ready(1)
  player.loop(); player.toggle()
  await vi.advanceTimersByTimeAsync(1000)
  expect(frames).toEqual([0])
  expect(player.snapshot().playing).toBe(false)
})
