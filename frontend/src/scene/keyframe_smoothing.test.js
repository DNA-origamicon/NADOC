import { it, expect, vi } from 'vitest'
import { trajectorySample, initKeyframeSmoothing } from './keyframe_smoothing.js'
it('samples adjacent knots in either direction, bounded by the selection and stages', () => {
  expect(trajectorySample(10, 12, .25)).toEqual({ frame: 10, from: 10, to: 11, t: .5, neighbors: { before: null, after: 12 } })
  expect(trajectorySample(12, 10, .75)).toEqual(trajectorySample(10, 12, .25))
  expect(trajectorySample(10, 12, 1)).toEqual({ frame: 12 })
  expect(trajectorySample(10, 10, .5)).toEqual({ frame: 10 })
  expect(trajectorySample(0, 4, .4, [{ frame: 2 }])).toEqual({ frame: 2 })
  expect(trajectorySample(0, 4, .6, [{ frame: 2 }]).neighbors.before).toBeNull()
})
it('waits for exact endpoints and companions, reuses readiness and draws subframes', async () => {
  let ready
  const ctrl = { ensureInterpolationFrames: vi.fn(() => new Promise(r => { ready = r })), showInterpolatedFrame: vi.fn() }
  const companion = { ensureFrame: vi.fn(async () => true), showInterpolatedFrame: vi.fn() }
  const smooth = initKeyframeSmoothing()
  smooth.set({ jobId: 'a', start: 10, end: 12, progress: .25 })
  const work = smooth.settle(ctrl, companion)
  expect(ctrl.showInterpolatedFrame).not.toHaveBeenCalled()
  ready(true); expect(await work).toBe(true)
  expect(ctrl.showInterpolatedFrame).toHaveBeenLastCalledWith(10, 11, .5, { before: null, after: 12 })
  expect(companion.ensureFrame.mock.calls.flat()).toEqual([10, 11, 12])
  smooth.set({ jobId: 'a', start: 10, end: 12, progress: .3 })
  await smooth.settle(ctrl, companion)
  expect(ctrl.ensureInterpolationFrames).toHaveBeenCalledTimes(1)
  expect(companion.showInterpolatedFrame).toHaveBeenCalledTimes(2)
})
it('does not paint an obsolete request after cancellation', async () => {
  let ready
  const ctrl = { ensureInterpolationFrames: () => new Promise(r => { ready = r }), showInterpolatedFrame: vi.fn() }
  const smooth = initKeyframeSmoothing()
  smooth.set({ jobId: 'a', start: 0, end: 2, progress: .25 })
  const work = smooth.settle(ctrl)
  smooth.clear(); ready(true)
  expect(await work).toBe(false)
  expect(ctrl.showInterpolatedFrame).not.toHaveBeenCalled()
})
