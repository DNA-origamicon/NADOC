import { expect, it } from 'vitest'
import { animationReadinessSegments, keyframeReadiness, readinessKey } from './animation_readiness.js'
const kf = { id: 'a', trajectory_job_id: 'job', trajectory_engine: 'oxdna', trajectory_scope: 'job' }
it('never counts server parsing or bytes transferred as previewable frames', () => {
  for (const phase of ['queued', 'load', 'download', 'decode']) {
    expect(keyframeReadiness(kf, { phase, done: 100, total: 100 }).fraction).toBe(0)
  }
  expect(keyframeReadiness(kf, { phase: 'ready', trajectoryFrames: 10 }).fraction).toBe(1)
})
it('maps actual prepared cells to selected frame ranges, including reversed ranges', () => {
  const progress = { phase: 'frames', trajectoryFrames: 10, grid: [0, 3, 6, 9], readyIndices: [0, 6], capped: true }
  const forward = keyframeReadiness({ ...kf, trajectory_frame_start: 2, trajectory_frame_end: 7 }, progress)
  expect(forward.fraction).toBe(0.5)
  expect(forward.intervals).toEqual([[0.5, 1]])
  const reverse = keyframeReadiness({ ...kf, trajectory_frame_start: 7, trajectory_frame_end: 2 }, progress)
  expect(reverse.intervals).toEqual([[0, 0.5]])
  expect(reverse.capped).toBe(true)
})
it('aligns boundaries with transition plus hold and isolates different resolutions of one job', () => {
  const spec = { engine: 'oxdna', scope: 'job' }
  const states = new Map([[readinessKey('job', spec), { phase: 'ready', trajectoryFrames: 10 }]])
  const result = animationReadinessSegments({ keyframes: [
    { ...kf, transition_duration_s: 1, hold_duration_s: 2 },
    { ...kf, id: 'b', trajectory_scope: 'lineage', transition_duration_s: 0, hold_duration_s: 6 },
    { id: 'camera', hold_duration_s: 1 },
  ] }, states)
  expect(result.duration).toBe(10)
  expect(result.segments.map(s => [s.start, s.duration, s.fraction])).toEqual([[0, 3, 1], [3, 6, 0], [9, 1, 0]])
  expect(result.segments[2].tracked).toBe(false)
})
