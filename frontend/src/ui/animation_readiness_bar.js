import { animationReadinessSegments, readinessKey } from '../scene/animation_readiness.js'

/** Duration-aligned cached-frame map beside the bottom scrubber. No modal or focus changes. */
export function initAnimationReadinessBar({ scrub }) {
  if (!scrub) return { setAnimation() {}, refreshAnimation() {}, update() {}, setTime() {}, destroy() {} }
  const root = document.createElement('div')
  root.dataset.role = 'animation-readiness'
  root.style.cssText = 'margin:4px 0 2px;font-size:var(--text-xs);color:#8b949e'
  const caption = document.createElement('div')
  caption.textContent = 'Trajectory preview ready · blue = loading · green = prepared'
  caption.style.cssText = 'font-size:10px;margin-bottom:3px'
  const track = document.createElement('div')
  track.style.cssText = 'display:flex;position:relative;height:20px;background:#161b22;border:1px solid #484f58;border-radius:3px;overflow:hidden'
  track.setAttribute('aria-label', 'Trajectory readiness by keyframe')
  const cursor = document.createElement('span')
  cursor.style.cssText = 'position:absolute;top:0;bottom:0;width:2px;background:#fff;pointer-events:none;z-index:3'
  root.append(caption, track); scrub.before(root)
  let animation = null, progress = new Map(), currentTime = 0, nodes = [], duration = 0, generation = 0

  function paint() {
    const state = animationReadinessSegments(animation, progress)
    duration = state.duration
    state.segments.forEach((segment, index) => {
      const { el, fill, text } = nodes[index]
      el.style.flex = `${segment.duration} 0 0px`
      el.style.display = segment.duration > 0 ? '' : 'none'
      const percent = Math.round(segment.fraction * 100)
      const working = ['load', 'download', 'decode', 'frames'].includes(segment.phase)
      const loading = ['load', 'download', 'decode'].includes(segment.phase)
      const loadPercent = segment.workFraction == null ? null : Math.floor(segment.workFraction * 100)
      const displayedPercent = loading && loadPercent != null ? loadPercent : percent
      const stage = ({ queued: 'queued', load: 'reading trajectory', download: 'downloading', decode: 'decoding', frames: 'preparing frames', ready: 'ready', cancelled: 'cancelled', error: 'preparation failed', none: 'no trajectory to load' })[segment.phase] || 'queued'
      const work = working && segment.workFraction != null ? ` (${Math.round(segment.workFraction * 100)}% of this step)` : ''
      const label = segment.tracked
        ? `${segment.label}: ${loading && loadPercent != null ? `${loadPercent}% loading · ` : ''}${percent}% preview frames prepared · ${stage}${work}${segment.capped ? ' · detail limited by memory' : ''}`
        : `${segment.label}: no trajectory to load; model states prepare on Play`
      el.title = label
      el.setAttribute('aria-label', label)
      if (segment.tracked) el.setAttribute('aria-valuenow', String(displayedPercent))
      else el.removeAttribute('aria-valuenow')
      text.textContent = `${index + 1} · ${segment.tracked ? `${displayedPercent}%${loading ? ' loading' : ''}${segment.capped ? '*' : ''}` : '—'}`
      const stops = ['#161b22 0%']
      let last = 0
      for (const [a, b] of segment.intervals) {
        stops.push(`#161b22 ${a * 100}%`, `#238636 ${a * 100}%`, `#238636 ${b * 100}%`)
        last = b
        stops.push(`#161b22 ${last * 100}%`)
      }
      stops.push('#161b22 100%')
      fill.style.background = loading && loadPercent != null
        ? `linear-gradient(to right, #1f6feb 0%, #1f6feb ${loadPercent}%, #161b22 ${loadPercent}%, #161b22 100%)`
        : `linear-gradient(to right, ${stops.join(',')})`
      el.style.borderBottom = segment.phase === 'error' ? '2px solid #f85149' : working ? '2px solid #58a6ff' : '2px solid transparent'
      el.dataset.phase = segment.phase
      el.dataset.readyPercent = String(percent)
      el.dataset.loadingPercent = loading && loadPercent != null ? String(loadPercent) : ''
    })
    paintCursor()
  }
  function paintCursor() {
    cursor.style.left = `${duration ? Math.max(0, Math.min(100, currentTime / duration * 100)) : 0}%`
  }
  function setAnimation(next) {
    const currentGeneration = ++generation
    animation = next; progress = new Map(); nodes = []
    track.replaceChildren()
    root.hidden = !(next?.keyframes || []).some(kf => kf.trajectory_job_id || kf.is_trajectory)
    for (const kf of next?.keyframes || []) {
      const el = document.createElement('div'), fill = document.createElement('span'), text = document.createElement('span')
      el.dataset.keyframeId = kf.id
      el.setAttribute('role', 'progressbar'); el.setAttribute('aria-valuemin', '0'); el.setAttribute('aria-valuemax', '100')
      el.tabIndex = 0
      el.style.cssText = 'position:relative;min-width:0;border-right:1px solid #8b949e;box-sizing:border-box;overflow:hidden;text-align:center;color:#fff'
      fill.style.cssText = 'position:absolute;inset:0'
      text.style.cssText = 'position:relative;z-index:1;font-size:10px;white-space:nowrap;line-height:17px;text-shadow:0 1px 2px #000'
      el.append(fill, text); track.append(el); nodes.push({ el, fill, text })
    }
    track.append(cursor); paint()
    return event => { if (generation === currentGeneration) update(event) }
  }
  function update(event) {
    if (!event?.jobId) return
    const key = readinessKey(event.jobId, event)
    const old = progress.get(key) || {}
    progress.set(key, event.phase === 'metadata'
      ? { ...old, trajectoryFrames: event.trajectoryFrames }
      : { ...old, ...event })
    paint()
  }
  return { setAnimation, refreshAnimation(next) { animation = next; paint() }, update, setTime(time) { currentTime = time; paintCursor() }, destroy() { root.remove() } }
}
