import { requestTrajectoryFrame, cancelTrajectoryFrame } from './trajectory_render_clock.js'

/** Playback-only subframes, with one prepared segment ahead of the display. */
export function initTrajectoryInterpolationClock({ current, count, fps, ensure, draw, commit,
  canBlend = () => true, buffering = () => {}, failed = () => {},
  request = requestTrajectoryFrame, cancel = cancelTrajectoryFrame, now = () => performance.now() }) {
  let generation = 0, raf = null, active = false, blended = false
  const duration = 1000 / fps
  const live = token => active && token === generation
  function prepare(from, token) {
    const to = from + 1 < count() ? from + 1 : 0
    const item = { from, to, blend: to > from && canBlend(from, to), ready: false, ok: false }
    // Capture failures now, but only stop playback if this segment is needed.
    item.promise = Promise.resolve().then(() => live(token) ? ensure(from, to, item.blend) : false)
      .then(ok => { item.ok = ok !== false; item.ready = true }, () => { item.ready = true })
    return item
  }
  async function run(token) {
    buffering(true)
    let segment = prepare(current(), token)
    await segment.promise
    if (!live(token)) return
    if (!segment.ok) { failed(); return }
    buffering(false)
    let start = now(), next = prepare(segment.to, token)
    const tick = timestamp => {
      if (!live(token)) return
      if (timestamp >= start + duration) {
        blended = false
        commit(segment.to)
        if (!live(token)) return
        if (!next.ready) {
          // A real cache miss holds the saved endpoint. Resume without a burst
          // of catch-up frames when storage finally delivers the next window.
          buffering(true)
          void next.promise.then(() => {
            if (!live(token)) return
            if (!next.ok) { failed(); return }
            buffering(false)
            segment = next; start = now(); next = prepare(segment.to, token)
            raf = request(tick)
          })
          return
        }
        if (!next.ok) { failed(); return }
        segment = next
        start += duration
        // Bound recovery after a suspended tab or a render taking whole frames.
        if (timestamp >= start + duration) start = timestamp
        next = prepare(segment.to, token)
      }
      const t = Math.max(0, (timestamp - start) / duration)
      if (segment.blend && t > 0) { draw(segment.from, segment.to, t); blended = true }
      raf = request(tick)
    }
    raf = request(tick)
  }
  return {
    start() { active = true; void run(++generation) },
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
