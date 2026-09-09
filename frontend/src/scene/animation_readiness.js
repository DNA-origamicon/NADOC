import { keyframeTrajSpec } from './trajectory_keyframes.js'
import { clampRange } from './trajectory_range.js'

export function readinessKey(jobId, spec) {
  return JSON.stringify([jobId, spec.engine || 'oxdna', spec.scope || 'lineage', spec.stride ?? null])
}

/** Availability of the exact playback cache cells covering this authored range.
 * Parsing/transfer counters are work progress, never evidence of usable frames.
 * Heavy playback snaps to nearest grid cells (ties go to the lower cell).
 */
export function keyframeReadiness(kf, progress = {}) {
  if (!kf.trajectory_job_id) return { tracked: false, fraction: 0, intervals: [], phase: 'none' }
  const total = Math.max(0, Number(progress.trajectoryFrames) || 0)
  const { start, end } = clampRange(kf.trajectory_frame_start, kf.trajectory_frame_end, total)
  const low = Math.min(start, end), high = Math.max(start, end), count = high - low + 1
  const intervals = []
  if (progress.phase === 'ready') intervals.push([0, 1])
  else if (progress.phase === 'frames' && total > 0) {
    const grid = progress.grid || [], ready = new Set(progress.readyIndices || [])
    for (let i = 0; i < grid.length; i++) {
      if (!ready.has(grid[i])) continue
      const a = Math.max(low, i ? Math.floor((grid[i - 1] + grid[i]) / 2) + 1 : 0)
      const b = Math.min(high, i + 1 < grid.length ? Math.floor((grid[i] + grid[i + 1]) / 2) : total - 1)
      if (b < a) continue
      const left = (a - low) / count, right = (b - low + 1) / count
      intervals.push(start <= end ? [left, right] : [1 - right, 1 - left])
    }
  }
  intervals.sort((a, b) => a[0] - b[0])
  const fraction = Math.min(1, intervals.reduce((sum, [a, b]) => sum + b - a, 0))
  return { tracked: true, fraction, intervals, total: total ? count : 0,
    phase: progress.phase || 'queued', capped: !!progress.capped,
    workFraction: progress.total > 0 ? Math.max(0, Math.min(1, progress.done / progress.total)) : null }
}

/** Segment widths follow the same transition + hold timing as the player. */
export function animationReadinessSegments(animation, progressByKey = new Map()) {
  let cursor = 0
  const segments = (animation?.keyframes || []).map((kf, index) => {
    const transition = Math.max(0, Number(kf.transition_duration_s) || 0)
    const hold = Math.max(0, Number(kf.hold_duration_s) || 0)
    const duration = transition + hold
    const ready = keyframeReadiness(kf, progressByKey.get(readinessKey(kf.trajectory_job_id, keyframeTrajSpec(kf))))
    const lead = duration ? transition / duration : 0
    const intervals = ready.intervals.map(([a, b]) => [lead + (1 - lead) * a, lead + (1 - lead) * b])
    if (lead && ready.intervals.some(([a, b]) => a === 0 && b > 0)) intervals.unshift([0, lead])
    const segment = { ...ready, id: kf.id, label: kf.name || `Keyframe ${index + 1}`, index,
      start: cursor, duration, intervals }
    cursor += duration
    return segment
  })
  return { segments, duration: cursor }
}
