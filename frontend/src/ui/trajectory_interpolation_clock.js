/** Playback-only subframes. Endpoint preparation never advances the saved-frame cursor. */
export function initTrajectoryInterpolationClock({ current, count, fps, ensure, draw, commit,
  canBlend = () => true, buffering = () => {}, failed = () => {},
  request = cb => requestAnimationFrame(cb), cancel = id => cancelAnimationFrame(id), now = () => performance.now() }) {
  let generation = 0, raf = null, active = false, blended = false
  async function segment(token) {
    const from = current(), to = from + 1 < count() ? from + 1 : 0
    const blend = to > from && canBlend(from, to)
    buffering(true)
    try {
      if (await ensure(from, to, blend) === false) throw new Error('Missing frame')
    } catch {
      if (token === generation) failed()
      return
    }
    if (!active || token !== generation) return
    buffering(false)
    const start = now()
    const tick = timestamp => {
      if (!active || token !== generation) return
      const t = Math.min(1, (timestamp - start) * fps / 1000)
      if (t >= 1) {
        blended = false
        commit(to)
        void segment(token)
      } else {
        if (blend && t > 0) { draw(from, to, t); blended = true }
        raf = request(tick)
      }
    }
    raf = request(tick)
  }
  return {
    start() { active = true; void segment(++generation) },
    stop() {
      active = false; generation++
      if (raf !== null) cancel(raf)
      raf = null
      const restore = blended
      blended = false
      return restore
    },
  }
}
