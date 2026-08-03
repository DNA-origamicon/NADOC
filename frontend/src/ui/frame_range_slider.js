/**
 * frame_range_slider.js — one bar carrying a trajectory keyframe's start, end and
 * currently-previewed frame.
 *
 * It replaces two stacked `<input type="range">` elements in the animation panel's
 * trajectory keyframe row. Two natives could express the RANGE but never the third
 * value, and they cost three lines of vertical space in a sidebar that has none: the
 * authored window and the frame you are looking at now sit on the same axis, so they
 * belong on the same axis on screen.
 *
 * Split the way everything else in this codebase is: the geometry and the drag rules are
 * pure functions (unit-tested against numbers, no DOM), and `initFrameRangeSlider` is the
 * thin DOM shell around them.
 *
 * Frame indices are COMPOSITE indices — they only mean anything relative to the
 * resolution the trajectory was loaded at (see `scene/trajectory_keyframes.js`
 * → `keyframeTrajSpec`). This widget just moves integers in [0, n-1]; the caller owns
 * what they address.
 */

import { markerPositions } from './oxdna_trajectory_player.js'

/** Pure: pixel offset within a track of width `w` → a frame index in [0, n-1]. */
export function frameAtOffset(offsetX, width, n) {
  if (!(n > 1) || !(width > 0)) return 0
  const pct = Math.max(0, Math.min(1, offsetX / width))
  return Math.max(0, Math.min(n - 1, Math.round(pct * (n - 1))))
}

/** Pure: frame index → percentage across the track. A single-frame trajectory pins to 0
 *  rather than dividing by zero. */
export function pctForFrame(i, n) {
  if (!(n > 1)) return 0
  const f = Math.max(0, Math.min(n - 1, i | 0))
  return (100 * f) / (n - 1)
}

/**
 * Pure: which of the three handles a press at `frame` grabs.
 *
 * Nearest wins. Ties go to the playhead, because it is the one that moves constantly
 * while start/end are set once — and the two bounds stay reachable anyway: at a tie the
 * playhead is already sitting on that bound, so dragging from there moves the playhead
 * off it and the bound becomes the unique nearest on the next press.
 *
 * `playhead: null` (preview not loaded) removes it from the contest entirely.
 */
export function pickHandle(frame, { start = 0, end = 0, playhead = null } = {}) {
  const cands = [['start', start], ['end', end]]
  if (playhead != null) cands.unshift(['playhead', playhead])
  let best = cands[0]
  let bestD = Math.abs(frame - cands[0][1])
  for (const c of cands.slice(1)) {
    const d = Math.abs(frame - c[1])
    if (d < bestD) { best = c; bestD = d }
  }
  return best[0]
}

/**
 * Pure: move one handle to `frame` and return the whole new state.
 *
 * Start and end PUSH each other rather than blocking — dragging start past end carries
 * end along, which is how every range control behaves and avoids a dead zone.
 *
 * Moving a BOUND also drags the playhead back inside the window. Dragging the playhead
 * itself does not: while you are hunting for the bounds you want to look anywhere in the
 * trajectory, but once the window is set, a needle parked outside it is showing a frame
 * this keyframe will never render.
 */
export function applyDrag(handle, frame, { start = 0, end = 0, playhead = null } = {}, n = 0) {
  const hi = Math.max(0, (n | 0) - 1)
  const f = Math.max(0, Math.min(hi, frame | 0))
  const inWindow = (s, e) => (playhead == null ? null : Math.max(s, Math.min(e, playhead)))
  if (handle === 'start') {
    const e = Math.max(f, Math.min(hi, end))
    return { start: f, end: e, playhead: inWindow(f, e) }
  }
  if (handle === 'end') {
    const s = Math.min(f, Math.max(0, start))
    return { start: s, end: f, playhead: inWindow(s, f) }
  }
  return { start, end, playhead: f }
}

const _C = {
  accent: '#c050d0',
  rail:   '#21262d',
  tick:   '#6e7681',
  head:   '#e6edf3',
  edge:   '#0d1117',
}

/**
 * @param {object} opts
 * @param {function({start,end}): void} [opts.onRangeChange]  per pointer move — CHEAP work only
 *   (labels). Never persist from here: a drag emits one of these per pixel, and a save that
 *   round-trips the store rebuilds this widget out from under the finger holding it.
 * @param {function({start,end}): void} [opts.onRangeCommit]  once, on release. Persist here.
 * @param {function(number): void}      [opts.onPlayhead]     playhead moved (fires per move).
 *   Also fires when a bound drags the playhead back into the window.
 */
export function initFrameRangeSlider({
  onRangeChange = null, onRangeCommit = null, onPlayhead = null,
} = {}) {
  let _n = 0
  let _start = 0
  let _end = 0
  let _playhead = null       // null = no preview loaded; the handle is not drawn
  let _enabled = false
  let _drag = null           // the handle name while a pointer is down
  let _dragFrom = null       // the range as it was at pointerdown, so release can tell
                             // whether anything actually needs saving

  const el = document.createElement('div')
  el.style.cssText = 'position:relative;height:18px;margin:0 7px;touch-action:none;cursor:pointer'

  const rail = document.createElement('div')
  rail.style.cssText =
    `position:absolute;left:0;right:0;top:7px;height:4px;border-radius:2px;background:${_C.rail}`

  const band = document.createElement('div')
  band.style.cssText =
    `position:absolute;top:7px;height:4px;border-radius:2px;background:${_C.accent}`

  const ticks = document.createElement('div')
  ticks.style.cssText = 'position:absolute;left:0;right:0;top:2px;height:14px;pointer-events:none'

  const _handle = (title) => {
    const h = document.createElement('div')
    h.title = title
    h.style.cssText =
      `position:absolute;top:3px;width:7px;height:12px;border-radius:2px;` +
      `background:${_C.accent};border:1px solid ${_C.edge};transform:translateX(-50%);` +
      'box-sizing:border-box;pointer-events:none'
    return h
  }
  const hStart = _handle('Range start')
  const hEnd   = _handle('Range end')

  // The playhead reads as a different KIND of thing from the two bounds — it is where you
  // are looking, not what gets rendered — so it is a capital-I needle spanning the full
  // height, not a grip. The serifs are what make it legible: a bare 2 px line disappears
  // against the stage ticks and reads as just another marker.
  const hPlay = document.createElement('div')
  hPlay.title = 'Previewed frame'
  hPlay.style.cssText =
    'position:absolute;top:0;width:11px;height:18px;transform:translateX(-50%);' +
    'pointer-events:none;display:none'
  const _serif = (edge) => {
    const d = document.createElement('div')
    d.style.cssText =
      `position:absolute;${edge}:0;left:0;right:0;height:3px;border-radius:1px;` +
      `background:${_C.head};box-shadow:0 0 0 1px ${_C.edge}`
    return d
  }
  const playStem = document.createElement('div')
  playStem.style.cssText =
    `position:absolute;top:0;bottom:0;left:50%;width:3px;transform:translateX(-50%);` +
    `background:${_C.head};box-shadow:0 0 0 1px ${_C.edge}`
  hPlay.append(_serif('top'), playStem, _serif('bottom'))

  el.append(rail, band, ticks, hStart, hEnd, hPlay)

  function _render() {
    const on = _enabled && _n > 0
    el.style.opacity = on ? '1' : '0.4'
    el.style.cursor = on ? 'pointer' : 'default'
    band.style.left  = `${pctForFrame(_start, _n)}%`
    band.style.width = `${Math.max(0, pctForFrame(_end, _n) - pctForFrame(_start, _n))}%`
    hStart.style.left = `${pctForFrame(_start, _n)}%`
    hEnd.style.left   = `${pctForFrame(_end, _n)}%`
    if (_playhead == null) {
      hPlay.style.display = 'none'
    } else {
      hPlay.style.display = ''
      hPlay.style.left = `${pctForFrame(_playhead, _n)}%`
    }
  }

  function _frameFromEvent(e) {
    const r = el.getBoundingClientRect()
    return frameAtOffset(e.clientX - r.left, r.width, _n)
  }

  function _move(e) {
    if (!_drag) return
    const next = applyDrag(_drag, _frameFromEvent(e), { start: _start, end: _end, playhead: _playhead }, _n)
    const rangeMoved = next.start !== _start || next.end !== _end
    const headMoved  = next.playhead !== _playhead
    _start = next.start; _end = next.end; _playhead = next.playhead
    _render()
    if (rangeMoved) onRangeChange?.({ start: _start, end: _end })
    if (headMoved)  onPlayhead?.(_playhead)
  }

  el.addEventListener('pointerdown', (e) => {
    if (!_enabled || _n < 2) return
    e.preventDefault()
    _drag = pickHandle(_frameFromEvent(e), { start: _start, end: _end, playhead: _playhead })
    _dragFrom = { start: _start, end: _end }
    el.setPointerCapture?.(e.pointerId)
    _move(e)
  })
  el.addEventListener('pointermove', _move)
  const _end_drag = (e) => {
    if (!_drag) return
    _drag = null
    el.releasePointerCapture?.(e.pointerId)
    // Save ONCE, on release. Persisting per move made every pixel of a drag a backend
    // PATCH, and each one re-rendered the keyframe row — the drag kept being interrupted
    // by its own saves.
    if (_dragFrom && (_dragFrom.start !== _start || _dragFrom.end !== _end)) {
      onRangeCommit?.({ start: _start, end: _end })
    }
    _dragFrom = null
  }
  el.addEventListener('pointerup', _end_drag)
  el.addEventListener('pointercancel', _end_drag)
  // Arrow keys nudge the playhead by one frame: scrubbing a 12 000-frame trajectory moves
  // dozens of frames per pixel, so dragging alone can never land on a specific one.
  el.tabIndex = 0
  el.addEventListener('keydown', (e) => {
    if (!_enabled || _playhead == null) return
    const d = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0
    if (!d) return
    e.preventDefault(); e.stopPropagation()
    const next = Math.max(0, Math.min(_n - 1, _playhead + d))
    if (next === _playhead) return
    _playhead = next
    _render()
    onPlayhead?.(_playhead)
  })

  return {
    el,
    /** Size the bar to a trajectory. Clamps the existing values into the new span. */
    setFrames(n, markers = []) {
      _n = Math.max(0, n | 0)
      const hi = Math.max(0, _n - 1)
      _start = Math.min(_start, hi)
      _end = _n ? Math.min(Math.max(_end, _start), hi) : 0
      if (_playhead != null) _playhead = Math.min(_playhead, hi)
      ticks.innerHTML = ''
      for (const m of markerPositions(markers, _n)) {
        const t = document.createElement('div')
        t.title = `${m.label}${m.stage_name ? ` (${m.stage_name})` : ''}`
        t.style.cssText =
          `position:absolute;top:0;left:${m.pct}%;width:1px;height:100%;` +
          `transform:translateX(-0.5px);background:${_C.tick}`
        ticks.appendChild(t)
      }
      _render()
    },
    setRange(s, e) {
      const hi = Math.max(0, _n - 1)
      _start = Math.max(0, Math.min(hi, s | 0))
      _end   = Math.max(_start, Math.min(hi, e | 0))
      _render()
    },
    getRange: () => ({ start: _start, end: _end }),
    /** `null` hides the playhead (no preview loaded). */
    setPlayhead(i) {
      _playhead = i == null ? null : Math.max(0, Math.min(Math.max(0, _n - 1), i | 0))
      _render()
    },
    getPlayhead: () => _playhead,
    setEnabled(on) { _enabled = !!on; _render() },
  }
}
