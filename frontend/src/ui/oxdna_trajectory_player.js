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
 * frame at a time. While it runs the button shows a ⏳ spinner; clicking again cancels.
 * `onPlayStateChange(playing)` fires when the loop actually starts / stops.
 */

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

const _MARKER_COLOR = { production: '#3fb950', equil: '#4a9eff', md_relax: '#e0a800', mc: '#8a8a8a' }

export function initOxdnaTrajectoryPlayer({
  playBtn, slider, markersEl, label, onSeek,
  onBeforePlay = null, onPlayStateChange = null, fps = 8,
} = {}) {
  let _n = 0          // frame count
  let _i = 0          // current frame
  let _markers = []
  let _timer = null
  let _preparing = false   // awaiting onBeforePlay (pre-building heavy frames)
  let _prepToken = 0       // bumped to cancel an in-flight prepare (user clicked again)

  function _setLabel() {
    if (label) label.textContent = _n ? `Frame ${_i + 1} / ${_n}` : ''
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
    if (fire) onSeek?.(_i)
  }

  function _tick() {
    seek(_i + 1 >= _n ? 0 : _i + 1)   // loop continuously
  }

  async function play() {
    if (_n < 2 || _timer || _preparing) return
    if (onBeforePlay) {                                // heavy reps: pre-build frames first
      _preparing = true
      const myToken = ++_prepToken
      if (playBtn) playBtn.textContent = '⏳'
      let go = true
      try { go = (await onBeforePlay()) !== false }
      catch { go = false }
      _preparing = false
      if (!go || _timer || myToken !== _prepToken) {   // cancelled / superseded while preparing
        if (playBtn && !_timer) playBtn.textContent = '▶'
        return
      }
    }
    _timer = setInterval(_tick, Math.max(1, Math.round(1000 / fps)))
    if (playBtn) playBtn.textContent = '⏸'
    onPlayStateChange?.(true)
  }
  function pause() {
    _prepToken++   // cancel any in-flight prepare so it won't start the loop on resolve
    const wasActive = !!_timer || _preparing
    _preparing = false
    if (_timer) { clearInterval(_timer); _timer = null }
    if (playBtn) playBtn.textContent = '▶'
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
  }

  /** Clear everything (toggle off / job switch). */
  function stop() {
    pause()
    _n = 0; _i = 0; _markers = []
    if (slider) { slider.value = '0'; slider.disabled = true }
    if (markersEl) markersEl.innerHTML = ''
    _setLabel()
  }

  playBtn?.addEventListener('click', toggle)
  slider?.addEventListener('input', () => { pause(); seek(parseInt(slider.value, 10) || 0) })

  return {
    setTrajectory, play, pause, toggle, seek, stop,
    isPlaying: () => !!_timer,
    current: () => _i,
    count: () => _n,
  }
}
