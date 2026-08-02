/**
 * Frame steppers — the ◂ / ▸ buttons that flank a trajectory scrub slider.
 *
 * Dragging a range input across a few hundred frames moves several frames per pixel,
 * so landing on one exact frame (the one where a crossover frays, where a clash first
 * appears) was luck.  These step the frame by exactly ±1.
 *
 * The buttons themselves are declared in index.html next to each scrubber, like every
 * other panel control; this module owns only the step arithmetic, the click wiring and
 * the greyed-out-at-the-ends state.
 *
 * Factory: initFrameSteppers({ prevBtn, nextBtn, count, current, onStep, wrap })
 *   count()   → total frames          current() → current frame index
 *   onStep(i) → apply frame i         wrap      → last→first instead of stopping
 * Returns { step, prev, next, refresh }.  Call `refresh()` whenever the frame or the
 * frame count changes so the buttons grey out at the ends.
 */

/**
 * Pure: the frame index reached by stepping `delta` from `current` in a `count`-frame
 * trajectory.  Clamps to [0, count-1], or wraps around when `wrap` is set.
 */
export function stepFrameIndex(current, delta, count, { wrap = false } = {}) {
  const n = Math.max(0, Math.trunc(count) || 0)
  if (n <= 0) return 0
  const i = (Math.trunc(current) || 0) + (Math.trunc(delta) || 0)
  if (wrap) return ((i % n) + n) % n
  return Math.max(0, Math.min(n - 1, i))
}

/**
 * Pure: which of the two buttons should be disabled.  Both are dead for a trajectory
 * with fewer than two frames; a wrapping trajectory has no ends, so neither is.
 */
export function frameStepperDisabled(current, count, { wrap = false } = {}) {
  const n = Math.max(0, Math.trunc(count) || 0)
  if (n < 2) return { prev: true, next: true }
  if (wrap) return { prev: false, next: false }
  const cur = Math.max(0, Math.min(n - 1, Math.trunc(current) || 0))
  return { prev: cur <= 0, next: cur >= n - 1 }
}

export function initFrameSteppers({
  prevBtn = null, nextBtn = null, count, current, onStep = null, wrap = false,
} = {}) {
  const _count = () => (typeof count === 'function' ? count() : count) || 0
  const _current = () => (typeof current === 'function' ? current() : current) || 0

  function refresh() {
    const d = frameStepperDisabled(_current(), _count(), { wrap })
    if (prevBtn) prevBtn.disabled = d.prev
    if (nextBtn) nextBtn.disabled = d.next
  }

  function step(delta) {
    const n = _count()
    if (n < 2) return
    const i = stepFrameIndex(_current(), delta, n, { wrap })
    if (i !== _current()) onStep?.(i)
    refresh()
  }

  prevBtn?.addEventListener('click', () => step(-1))
  nextBtn?.addEventListener('click', () => step(+1))
  refresh()

  return { step, prev: () => step(-1), next: () => step(+1), refresh }
}
