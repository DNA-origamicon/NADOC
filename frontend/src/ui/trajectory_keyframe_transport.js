/** Expanded and collapsed controls are views of the same keyframe playback. */
export function attachTrajectoryTransport({ row, keyframe, headerButton, timeline, preview }) {
  const { bar, element, transport, refresh, getFrameCount } = timeline
  const doc = row.ownerDocument, id = keyframe.id
  row.classList.add('has-trajectory-transport')
  headerButton.classList.add('trajectory-header-play')
  headerButton.dataset.role = 'trajectory-header-play'
  const button = (role, label, glyph, action) => {
    const el = doc.createElement('button')
    el.type = 'button'; el.className = 'btn btn--sm'; el.dataset.role = role
    el.title = label; el.setAttribute('aria-label', label); el.textContent = glyph
    el.addEventListener('click', () => { void action() }); transport.append(el); return el
  }
  const first = button('trajectory-first', 'First trajectory frame', '⏮', () => preview.seek(id, 0))
  const play = button('trajectory-play', 'Play trajectory', '▶', () => preview.toggle(id))
  const stop = button('trajectory-stop', 'Stop trajectory', '■', () => preview.stop(id))
  const last = button('trajectory-last', 'Last trajectory frame', '⏭', () => preview.seek(id, 1))
  const paint = state => {
    const active = state.id === id, playing = active && state.status === 'playing', loading = active && state.status === 'loading'
    for (const el of [play, headerButton]) {
      el.textContent = loading ? '…' : playing ? '⏸' : '▶'
      el.title = loading ? 'Cancel trajectory preparation' : playing ? 'Pause trajectory' : 'Play trajectory'
      el.setAttribute('aria-label', el.title)
      el.setAttribute('aria-pressed', String(playing))
      el.disabled = !keyframe.trajectory_job_id
    }
    first.disabled = last.disabled = loading || !keyframe.trajectory_job_id
    stop.disabled = !active
    if (active && state.range && getFrameCount()) {
      const { start, end } = bar.getRange(), { holdStart, end: finish } = state.range
      const progress = Math.max(0, Math.min(1, (state.time - holdStart) / (finish - holdStart || 1)))
      bar.setPlayhead(Math.round(start + (end - start) * progress))
    } else if (!active) bar.setPlayhead(null)
    refresh(state)
  }
  timeline.paint = () => paint(preview.getState())
  row.firstElementChild.after(element)
  return preview.subscribe(paint)
}

export function createTrajectoryTimeline({ keyframe, bar, rangeInputs, rangeLabel, downloadStatus, downloadBar, cancelPreparation, getFrameCount, refreshLabel }) {
  const element = bar.el.ownerDocument.createElement('div')
  element.dataset.role = 'trajectory-timeline'
  const transport = element.ownerDocument.createElement('div')
  transport.className = 'trajectory-transport'
  bar.el.dataset.role = 'trajectory-scrubber'
  element.append(bar.el, transport, rangeInputs, rangeLabel)
  return { element, transport, bar, getFrameCount,
    refresh(state) {
      const active = state.id === keyframe.id, loading = active && state.status === 'loading'
      downloadBar.hidden = cancelPreparation.hidden = !loading
      const progress = state.progress
      if (loading && progress?.total > 0) downloadBar.value = progress.done / progress.total
      else if (loading) downloadBar.removeAttribute('value')
      downloadStatus.textContent = loading ? progress?.label || 'Preparing trajectory frames…'
        : active ? (state.status === 'playing' ? 'Playing selected frames' : 'Preview paused') : 'Choose frames, then play or scrub'
      refreshLabel()
    },
  }
}
