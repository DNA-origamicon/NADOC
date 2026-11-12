import { interpolationNeighbors } from './trajectory_interpolation.js'

/** Adjacent saved frames only; never spline across stages or outside authored bounds. */
export function trajectorySample(start, end, progress, markers = []) {
  const position = start + (end - start) * Math.max(0, Math.min(1, progress))
  const from = Math.floor(position), to = Math.ceil(position)
  if (from === to) return { frame: from }
  if (markers.some(m => Number(m.frame) === to)) return { frame: Math.round(position) }
  const neighbors = interpolationNeighbors(from, to, Math.max(start, end) + 1, markers)
  if (neighbors.before < Math.min(start, end)) neighbors.before = null
  return { frame: from, from, to, t: position - from, neighbors }
}

/** Export and live playback await the same saved-endpoint readiness before drawing. */
export function initKeyframeSmoothing() {
  let current = null, prepared = null
  return {
    set(request) { current = request },
    clear() { current = prepared = null },
    async settle(ctrl, companion, markers = []) {
      const request = current
      if (!request) return true
      const sample = trajectorySample(request.start, request.end, request.progress, markers)
      if (!ctrl?.ensureInterpolationFrames || !ctrl?.showInterpolatedFrame) throw new Error('Smooth trajectory playback is unavailable')
      const { from, to, t, neighbors } = sample.to == null
        ? { from: sample.frame, to: sample.frame, t: 0, neighbors: { before: null, after: null } } : sample
      const key = JSON.stringify([request.jobId, ctrl.trajectoryPreparationKey?.(), request.companions, from, to, neighbors])
      if (prepared?.key !== key || prepared.ctrl !== ctrl) {
        const work = (async () => {
          if (await ctrl.ensureInterpolationFrames(from, to, neighbors) === false) return false
          for (const index of [from, to, neighbors.before, neighbors.after].filter(i => i != null)) {
            if (await companion?.ensureFrame?.(index) === false) return false
          }
          return true
        })()
        prepared = { key, ctrl, work }
      }
      const ok = await prepared.work
      if (request !== current) return false
      if (!ok) throw new Error('Could not prepare smooth trajectory frames')
      ctrl.showInterpolatedFrame(from, to, t, neighbors)
      companion?.showInterpolatedFrame?.(from, to, t, neighbors)
      return true
    },
  }
}
