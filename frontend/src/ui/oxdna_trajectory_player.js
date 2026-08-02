/**
 * oxDNA trajectory player — play/pause + scrub-slider controller for the
 * composite trajectory (relaxation + all production runs).
 *
 * Owns ONLY the playback UI behaviour (play loop, slider sync, stage markers,
 * frame counter).  The frame DATA + applying a frame to the model live in
 * oxdna_display.js; this module calls back via `onSeek(frameIndex)`.
 *
 * Factory: initOxdnaTrajectoryPlayer({ playBtn, slider, markersEl, label, onSeek,
 *   onBeforePlay, onPlayStateChange, fps })
 *
 * `onBeforePlay` (optional, async) runs BEFORE the play loop starts and is awaited —
 * the heavy (atomistic/surface) path uses it to pre-build every coarse playback frame
 * (each is a slow all-atom rebuild) so playback is then smooth instead of stalling one
 * frame at a time. While it runs the button shows a spinner; clicking again cancels.
 * `onPlayStateChange(playing)` fires when the loop actually starts / stops.
 *
 * `setPreparing({done, total} | null)` — tell the player that frames are being prepared in
 * the BACKGROUND, before any click. The button then shows a spinner instead of ▶ and
 * refuses the click.
 *
 * That last one is a deliberate honesty fix. A heavy trajectory cannot play until every
 * coarse cell is in memory (at 8 fps the loop cannot stop for a ~2 s fetch per frame), but
 * the button showed a ready ▶ throughout — so the user pressed it expecting instant
 * playback and got a multi-second hourglass instead. Scrubbing works fine during that
 * window, which makes the button look broken rather than busy: scrubbing needs only the
 * one cell you stop on, and the background prebuild has usually already fetched it.
 * Measured on a 200-frame job: 32 of 200 cells present 3 s after switching to atomistic,
 * all 200 present ~25 s later, after which play starts in ~1.2 s. Show the wait up front.
 */

import { initFrameSteppers } from './frame_steppers.js'

/**
 * Pure: place stage-transition markers along the slider track.
 * Returns [{frame, label, kind, pct}] with pct ∈ [0,100] (frame / (n-1)).
 */
export function markerPositions(markers, nFrames) {
  if (!Array.isArray(markers) || !nFrames || nFrames < 2) return []
  return markers.map((m) => ({
    ...m,
    pct: Math.max(0, Math.min(100, (m.frame / (nFrames - 1)) * 100)),
  }))
}

/**
 * Pure: which composite-trajectory stage a frame index falls in.  `stages` is the
 * `[{name, kind, n_frames, field}]` list from the /trajectory payload (each stage's
 * frames are contiguous, in order).  Returns the stage object, or null if `stages`
 * is empty.  Past-the-end indices clamp to the last stage.
 */
export function stageAtFrame(stages, frameIndex) {
  if (!Array.isArray(stages) || stages.length === 0) return null
  let start = 0
  for (const s of stages) {
    const n = Math.max(0, s.n_frames | 0)
    if (frameIndex < start + n) return s
    start += n
  }
  return stages[stages.length - 1]
}

/**
 * Pure: the E-field descriptor ({dir, field_pN}) active at a composite-trajectory
 * frame, or null when that frame's stage ran no field (relaxation / plain run).
 */
export function fieldAtFrame(stages, frameIndex) {
  return stageAtFrame(stages, frameIndex)?.field ?? null
}

const _MARKER_COLOR ={ production: '#3fb950', equil: '#4a9eff', md_relax: '#e0a800', mc: '#8a8a8a' }

export function initOxdnaTrajectoryPlayer({
  playBtn, slider, markersEl, label, onSeek, prevBtn = null, nextBtn = null,
  onBeforePlay = null, onPlayStateChange = null, fps = 8,
} = {}) {
  let _n = 0          // frame count
  let _i = 0          // current frame
  let _markers = []
  let _timer = null
  let _preparing = false   // awaiting onBeforePlay (pre-building heavy frames)
  let _prepToken = 0       // bumped to cancel an in-flight prepare (user clicked again)
  let _bgPrep = null       // {done,total} while frames are prepared in the BACKGROUND

  // ◂ / ▸ — step exactly one frame. Scrubbing a 200-frame slider moves several frames
  // per pixel, so these are the only way to land on a specific one.
  const _steppers = initFrameSteppers({
    prevBtn, nextBtn, count: () => _n, current: () => _i,
    onStep: (i) => { pause(); seek(i) },
  })

  function _setLabel() {
    if (label) label.textContent = _n ? `Frame ${_i + 1} / ${_n}` : ''
  }

  /**
   * The play button has FOUR states and they must all be set in one place — the previous
   * scattered `playBtn.textContent = …` assignments are how it ended up advertising ▶
   * while the frames it needs were still downloading.
   *
   *   playing            ⏸
   *   preparing (either) spinner + disabled  — cannot play yet, and says so
   *   idle               ▶
   */
  function _renderPlayBtn() {
    if (!playBtn) return
    const busy = _preparing || !!_bgPrep
    playBtn.disabled = busy && !_timer
    if (_timer) {
      playBtn.replaceChildren('⏸')
      playBtn.title = 'Pause'
      playBtn.style.cursor = 'pointer'
      return
    }
    if (busy) {
      const s = document.createElement('span')
      s.className = 'nadoc-spinner'
      s.style.width = s.style.height = '11px'
      s.setAttribute('aria-hidden', 'true')
      playBtn.replaceChildren(s)
      const p = _bgPrep && _bgPrep.total
        ? ` (${_bgPrep.done}/${_bgPrep.total} frames)`
        : ''
      playBtn.title = `Preparing all-atom frames${p} — playback needs the whole trajectory in memory`
      playBtn.style.cursor = 'progress'
      return
    }
    playBtn.replaceChildren('▶')
    playBtn.title = 'Play / pause'
    playBtn.style.cursor = 'pointer'
  }

  /**
   * Frames are being prepared in the background (not by a click). Pass `{done, total}` to
   * show the spinner, `null` when everything the player needs is in memory.
   * No-op for CG, where the caller never has anything to prepare.
   */
  function setPreparing(progress) {
    _bgPrep = progress && progress.total ? { done: progress.done | 0, total: progress.total | 0 } : null
    _renderPlayBtn()
  }

  function _renderMarkers() {
    if (!markersEl) return
    markersEl.innerHTML = ''
    for (const m of markerPositions(_markers, _n)) {
      const tick = document.createElement('div')
      tick.title = `${m.label}${m.stage_name ? ` (${m.stage_name})` : ''}`
      tick.style.cssText =
        `position:absolute;top:0;left:${m.pct}%;width:2px;height:100%;` +
        `transform:translateX(-1px);background:${_MARKER_COLOR[m.kind] || '#cdd9e5'};` +
        `pointer-events:auto;cursor:help`
      markersEl.appendChild(tick)
    }
  }

  function seek(i, fire = true) {
    if (_n <= 0) return
    _i = Math.max(0, Math.min(_n - 1, i | 0))
    if (slider) slider.value = String(_i)
    _setLabel()
    _steppers.refresh()
    if (fire) onSeek?.(_i)
  }

  function _tick() {
    seek(_i + 1 >= _n ? 0 : _i + 1)   // loop continuously
  }

  async function play() {
    // A background prepare is still running — the frames simply are not there yet. The
    // button is already a disabled spinner, so this is only reachable programmatically.
    if (_n < 2 || _timer || _preparing || _bgPrep) return
    if (onBeforePlay) {                                // heavy reps: pre-build frames first
      _preparing = true
      const myToken = ++_prepToken
      _renderPlayBtn()
      let go = true
      try { go = (await onBeforePlay()) !== false }
      catch { go = false }
      _preparing = false
      if (!go || _timer || myToken !== _prepToken) {   // cancelled / superseded while preparing
        _renderPlayBtn()
        return
      }
    }
    _timer = setInterval(_tick, Math.max(1, Math.round(1000 / fps)))
    _renderPlayBtn()
    onPlayStateChange?.(true)
  }
  function pause() {
    _prepToken++   // cancel any in-flight prepare so it won't start the loop on resolve
    const wasActive = !!_timer || _preparing
    _preparing = false
    if (_timer) { clearInterval(_timer); _timer = null }
    _renderPlayBtn()
    if (wasActive) onPlayStateChange?.(false)
  }
  function toggle() { (_timer || _preparing) ? pause() : play() }

  /** Load a new trajectory: set frame count + markers, reset to frame 0, paused. */
  function setTrajectory(nFrames, markers) {
    pause()
    _n = Math.max(0, nFrames | 0)
    _markers = markers || []
    _i = 0
    if (slider) { slider.max = String(Math.max(0, _n - 1)); slider.value = '0'; slider.disabled = _n < 2 }
    _renderMarkers()
    _setLabel()
    _steppers.refresh()
  }

  /** Clear everything (toggle off / job switch). */
  function stop() {
    pause()
    _n = 0; _i = 0; _markers = []
    // A job switch invalidates any prepare that was running for the OLD job; leaving the
    // spinner up would disable the button for a trajectory that has nothing pending.
    _bgPrep = null
    if (slider) { slider.value = '0'; slider.disabled = true }
    if (markersEl) markersEl.innerHTML = ''
    _setLabel()
    _steppers.refresh()
    _renderPlayBtn()
  }

  playBtn?.addEventListener('click', toggle)
  slider?.addEventListener('input', () => { pause(); seek(parseInt(slider.value, 10) || 0) })

  return {
    setTrajectory, play, pause, toggle, seek, stop, setPreparing,
    isPlaying: () => !!_timer,
    isPreparing: () => _preparing || !!_bgPrep,
    current: () => _i,
    count: () => _n,
  }
}
