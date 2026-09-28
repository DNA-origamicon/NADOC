import { it, expect, vi, afterEach } from 'vitest'
import { initSnupiTrajectoryPlayer } from './snupi_trajectory_player.js'
function frame(i) {
  const h = new TextEncoder().encode(JSON.stringify({ kind: 'deform', count: 1, identities: false, frame: i, frames: 3 }))
  const offset = Math.ceil((12+h.length)/4)*4, b = new ArrayBuffer(offset+16)
  const v = new DataView(b); [0x5A495643,1,h.length].forEach((n,j) => v.setUint32(j*4,n,true))
  new Uint8Array(b,12,h.length).set(h)
  return b
}
afterEach(() => vi.useRealTimers())
it('backpressures playback, reuses buffers, and cancels an in-flight frame on Off', async () => {
  vi.useFakeTimers()
  const view = { update: vi.fn(), updatePositions: vi.fn(), clear: vi.fn() }
  const api = { getSnupiTrajectoryFrameBin: vi.fn(async (_, i) => frame(i)) }
  const player = initSnupiTrajectoryPlayer({ api, view })
  const start = player.show('job'); await vi.advanceTimersByTimeAsync(20); await start
  expect(player.info()).toEqual({ frame: 1, total: 3 })
  let finish, signal
  api.getSnupiTrajectoryFrameBin.mockImplementationOnce((_, i, opts) => { signal = opts.signal; return new Promise(r => { finish = () => r(frame(i)) }) })
  await vi.advanceTimersByTimeAsync(100)
  expect(api.getSnupiTrajectoryFrameBin).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(1000)
  expect(api.getSnupiTrajectoryFrameBin).toHaveBeenCalledTimes(2)
  finish(); await vi.advanceTimersByTimeAsync(20)
  expect(view.update).toHaveBeenCalledTimes(1)
  expect(view.updatePositions).toHaveBeenCalledTimes(1)
  player.pause()
  api.getSnupiTrajectoryFrameBin.mockImplementationOnce((_, i, opts) => { signal = opts.signal; return new Promise(r => { finish = () => r(frame(i)) }) })
  const pending = player.seek(2)
  player.stop(); finish(); await pending
  expect(signal.aborted).toBe(true)
  expect(player.info()).toBeNull()
  expect(view.updatePositions).toHaveBeenCalledTimes(1)
})
it('a superseded scrub response cannot replace the newest frame', async () => {
  const view = { update: vi.fn(), updatePositions: vi.fn(), clear: vi.fn() }
  let finish
  const api = { getSnupiTrajectoryFrameBin: vi.fn(async (_, i) => frame(i)) }
  const player = initSnupiTrajectoryPlayer({ api, view })
  await player.show('job'); player.pause()
  api.getSnupiTrajectoryFrameBin.mockImplementationOnce(() => new Promise(r => { finish = r }))
  const old = player.seek(1)
  await player.seek(2); finish(frame(1)); await old
  expect(player.info().frame).toBe(3)
  player.stop()
})
it('reads the requested scrubber position before pausing refreshes its value', async () => {
  document.body.innerHTML = '<input id="snupi-traj-scrubber" type="range"><span id="snupi-traj-frame"></span>'
  const view = { update: vi.fn(), updatePositions: vi.fn(), clear: vi.fn() }
  const api = { getSnupiTrajectoryFrameBin: vi.fn(async (_, i) => frame(i)) }
  const player = initSnupiTrajectoryPlayer({ api, view })
  await player.show('job')
  const scrubber = document.getElementById('snupi-traj-scrubber')
  scrubber.value = '2'; scrubber.dispatchEvent(new Event('input'))
  await vi.waitFor(() => expect(player.info().frame).toBe(3))
  expect(document.getElementById('snupi-traj-frame').textContent).toBe('3/3')
  player.stop(); document.body.innerHTML = ''
})
