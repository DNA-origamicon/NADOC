/**
 * φ ticker — drives the reaction coordinate over time when Play is pressed.
 *
 * Much simpler than the design animation player (no baking, no keyframes, no
 * API). A single linear progress `u` ∈ [0,1] advances with time at `speed`
 * φ-units/sec; φ = ease(u) for hybridize, 1−ease(u) for dehybridize. Honors
 * loop / bounce at the [0,1] boundaries. Play resumes from the current φ.
 */

// Easing curves — copied from scene/animation_player.js (kept local so this
// standalone page has no dependency on the 990-line player).
function _ease(t, curve) {
  switch (curve) {
    case 'linear': return t
    case 'ease-in': return t * t
    case 'ease-out': return t * (2 - t)
    case 'ease-in-out':
    default: return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t
  }
}

const clamp01 = (v) => Math.max(0, Math.min(1, v))

// Numerically invert the (monotonic) easing so Play resumes from a scrubbed φ
// without a velocity jump. 24 bisections → ~1e-7 precision.
function _invEase(target, curve) {
  let lo = 0, hi = 1
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) * 0.5
    if (_ease(mid, curve) < target) lo = mid
    else hi = mid
  }
  return (lo + hi) * 0.5
}

/**
 * @param {object} io
 * @param {() => object} io.getState - returns the param snapshot (speed, easing, …)
 * @param {(phi:number) => void} io.setPhi
 * @param {(playing:boolean) => void} [io.onState] - notified on play/pause/stop
 * @returns {{play:()=>void, pause:()=>void, toggle:()=>void, stop:()=>void, isPlaying:()=>boolean}}
 */
export function createPhiTicker({ getState, setPhi, onState }) {
  let raf = null
  let last = 0
  let u = 0          // linear progress [0,1]
  let du = 1         // direction of u advance (+1/−1), flips on bounce

  function _emit() {
    const s = getState()
    const e = _ease(clamp01(u), s.easing)
    setPhi(s.direction === 'hybridize' ? e : 1 - e)
  }

  function _frame(now) {
    if (!raf) return
    const s = getState()
    // Clamp dt ≥ 0 (a first rAF timestamp can predate play()'s clock read) and
    // ≤ 0.1 (tab-switch gaps).
    const dt = Math.max(0, Math.min(0.1, (now - last) / 1000))
    last = now
    u += du * s.speed * dt

    // Direction-aware boundary: only "hit" the end we're actually heading
    // toward, so pressing Play exactly at a boundary (e.g. φ=0 hybridize) sweeps
    // inward instead of instantly finishing.
    let hit = null
    if (du > 0 && u >= 1) { u = 1; hit = 'hi' }
    else if (du < 0 && u <= 0) { u = 0; hit = 'lo' }
    if (hit) {
      if (s.bounce) { du = -du }
      else if (s.loop) { u = hit === 'hi' ? 0 : 1 }
      else { _emit(); return _finish() }
    }
    _emit()
    raf = requestAnimationFrame(_frame)
  }

  function _finish() {
    raf = null
    onState?.(false)
  }

  function play() {
    if (raf) return
    // Seed u so playback continues from wherever φ currently is.
    const s = getState()
    const cur = clamp01(s.phi)
    u = _invEase(s.direction === 'hybridize' ? cur : 1 - cur, s.easing)
    du = 1
    last = performance.now()
    raf = requestAnimationFrame(_frame)
    onState?.(true)
  }

  function pause() {
    if (!raf) return
    cancelAnimationFrame(raf)
    raf = null
    onState?.(false)
  }

  function stop() { pause() }
  function toggle() { (raf ? pause : play)() }
  function isPlaying() { return !!raf }

  return { play, pause, toggle, stop, isPlaying }
}
