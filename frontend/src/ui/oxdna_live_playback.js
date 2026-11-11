import { cubicCoordinates } from '../scene/trajectory_interpolation.js'
import { requestTrajectoryFrame, cancelTrajectoryFrame } from './trajectory_render_clock.js'

const VECTOR_FIELDS = ['backbone_position', 'base_position', 'cm_position']
const SCALAR_FIELDS = ['nx', 'ny', 'nz', 'tx', 'ty', 'tz']
const STRIDE = 15

// Pack each immutable received snapshot once. Fixed slots avoid allocating a
// separate [particle, property, component] tuple for every coordinate, and the
// render loop writes directly to reusable records instead of traversing tuples.
function packFrame(positions, cache) {
  if (cache.has(positions)) return cache.get(positions)
  const values = new Float64Array(positions.length * STRIDE), masks = new Uint16Array(positions.length)
  for (let i = 0; i < positions.length; i++) {
    const p = positions[i], offset = i * STRIDE
    for (let j = 0; j < VECTOR_FIELDS.length; j++) {
      const v = p[VECTOR_FIELDS[j]]
      if (v === undefined) continue
      if (!Array.isArray(v) || v.length !== 3 || !v.every(Number.isFinite)) return null
      masks[i] |= 1 << j
      values.set(v, offset + j * 3)
    }
    for (let j = 0; j < SCALAR_FIELDS.length; j++) {
      const v = p[SCALAR_FIELDS[j]]
      if (v === undefined) continue
      if (!Number.isFinite(v)) return null
      masks[i] |= 1 << (j + 3)
      values[offset + 9 + j] = v
    }
  }
  const packed = { positions, values, masks }
  cache.set(positions, packed)
  return packed
}
function compatible(a, b) {
  if (!a || !b || a.positions.length !== b.positions.length) return false
  for (let i = 0; i < a.positions.length; i++) {
    const x = a.positions[i], y = b.positions[i]
    if (a.masks[i] !== b.masks[i] || x.helix_id !== y.helix_id || x.bp_index !== y.bp_index
      || x.direction !== y.direction || (x.copy ?? 0) !== (y.copy ?? 0)) return false
  }
  return true
}

/** Saved-trajectory Catmull–Rom, refusing tangents across particle/layout changes. */
export function liveFrameBlend(from, to, before = null, after = null, cache = new WeakMap()) {
  const a = packFrame(from, cache), b = packFrame(to, cache)
  if (!compatible(a, b)) return null
  const prev = before && packFrame(before, cache), next = after && packFrame(after, cache)
  const beforeValues = compatible(a, prev) ? prev.values : null
  const afterValues = compatible(a, next) ? next.values : null
  const buffer = new Float32Array(a.values.length)
  const out = to.map(p => {
    const row = { ...p }
    for (const key of VECTOR_FIELDS) if (p[key]) row[key] = [...p[key]]
    return row
  })
  return t => {
    cubicCoordinates(beforeValues, a.values, b.values, afterValues, t, buffer)
    for (let i = 0; i < out.length; i++) {
      const p = out[i], offset = i * STRIDE, mask = b.masks[i]
      for (let j = 0; j < VECTOR_FIELDS.length; j++) if (mask & (1 << j)) {
        const v = p[VECTOR_FIELDS[j]], base = offset + j * 3
        v[0] = buffer[base]; v[1] = buffer[base + 1]; v[2] = buffer[base + 2]
      }
      for (let j = 0; j < SCALAR_FIELDS.length; j++) if (mask & (1 << (j + 3))) p[SCALAR_FIELDS[j]] = buffer[offset + 9 + j]
    }
    return out
  }
}

/** Bounded jitter buffer: four queued frames before starting/refilling, then
 * consume in order with one lookahead reserved for Catmull–Rom. Keep the next
 * knot on overflow, coalescing excess frames rather than growing latency forever. */
export function initLivePlayback({ draw, interval = 500, bufferFrames = 4, maxBufferedFrames = 8,
  request = requestTrajectoryFrame, cancel = cancelTrajectoryFrame,
  now = () => performance.now() }) {
  const target = Math.max(2, Math.floor(bufferFrames)), capacity = Math.max(target, maxBufferedFrames)
  let smooth = false, previous = null, current = null, latest = null, segment = null
  let pending = [], raf = null, lastArrival = null, lastSequence = null, waiting = true
  let cadence = interval, lastTick = null, ahead = null, packed = new WeakMap()
  const stats = { underruns: 0, coalescedFrames: 0, duplicates: 0, arrivalMs: 0,
    prepareMs: 0, maxPrepareMs: 0, drawMs: 0, maxDrawMs: 0, maxRenderGapMs: 0 }
  function paint(positions) {
    const started = now(); draw(positions)
    stats.drawMs = now() - started; stats.maxDrawMs = Math.max(stats.maxDrawMs, stats.drawMs)
  }
  function blend(from, to, before, after) {
    const started = now(), result = liveFrameBlend(from, to, before, after, packed)
    stats.prepareMs = now() - started; stats.maxPrepareMs = Math.max(stats.maxPrepareMs, stats.prepareMs)
    return result
  }
  function prepareAhead() {
    if (!segment || pending.length < 2) return
    const to = pending[0].positions, after = pending[1].positions
    if (ahead?.from === segment.positions && ahead.to === to && ahead.after === after) return
    ahead = { from: segment.positions, to, after, blend: blend(segment.positions, to, current, after) }
  }
  function cancelDraw() {
    if (raf !== null) cancel(raf)
    raf = null; segment = null; pending = []; previous = null; ahead = null
    waiting = true; lastTick = null; packed = new WeakMap()
  }
  function begin(time) {
    if (segment || pending.length < (waiting ? target : 2)) return
    waiting = false
    const item = pending.shift(), after = pending[0].positions
    const interpolate = ahead?.from === current && ahead.to === item.positions && ahead.after === after
      ? ahead.blend : blend(current, item.positions, previous, after)
    ahead = null
    if (!interpolate) { previous = null; current = item.positions; paint(current); waiting = true; return }
    segment = { ...item, blend: interpolate, start: time }
    raf = request(tick)
  }
  function tick(time) {
    raf = null
    if (!segment) return
    if (lastTick !== null) stats.maxRenderGapMs = Math.max(stats.maxRenderGapMs, time - lastTick)
    lastTick = time
    const t = Math.max(0, Math.min(1, (time - segment.start) / segment.duration))
    if (t < 1) { paint(segment.blend(t)); raf = request(tick); return }
    const nextStart = segment.start + segment.duration
    previous = current; current = segment.positions; segment = null
    if (pending.length < 2) { waiting = true; stats.underruns++; lastTick = null }
    // Carry ordinary render jitter across deadlines; never burst-catch-up after suspension.
    begin(pending.length >= 2 && time < nextStart + pending[0].duration ? nextStart : time)
    // One scene deformation per renderer tick, including at segment boundaries.
    paint(segment && time > segment.start ? segment.blend((time - segment.start) / segment.duration) : current)
  }
  return {
    push(positions, sequence) {
      if (sequence != null && sequence === lastSequence) { stats.duplicates++; return }
      lastSequence = sequence
      const time = now()
      if (lastArrival !== null) {
        stats.arrivalMs = time - lastArrival
        // Low-pass the producer cadence instead of replaying each network hiccup
        // as a sudden speed change in the next spline segment.
        cadence += .1 * (Math.max(interval, Math.min(2000, stats.arrivalMs)) - cadence)
      }
      lastArrival = time; latest = positions
      if (!smooth || !current) { previous = null; current = positions; paint(current); return }
      const item = { positions, duration: cadence }
      if (pending.length < capacity) pending.push(item)
      else {
        // Preserve the next knot (and the prepared next segment when possible).
        pending.splice(Math.min(2, capacity - 1), 1); pending.push(item); stats.coalescedFrames++
      }
      begin(time)
      // Prepare the next curve on receipt, outside the renderer's frame callback.
      prepareAhead()
    },
    diagnostics: () => ({ ...stats, buffered: pending.length, bufferTarget: target,
      buffering: smooth && waiting, smooth, cadenceMs: cadence }),
    setSmooth(value) {
      smooth = !!value
      cancelDraw()
      if (latest) { current = latest; paint(current) }
    },
    reset() {
      cancelDraw(); current = latest = null; lastArrival = lastSequence = null; cadence = interval
      for (const key of Object.keys(stats)) stats[key] = 0
    },
  }
}

/** Nonmodal control anchored inside the 3D canvas, visible only during Live. */
export function initLivePlaybackPopup({ onSmooth }) {
  const host = document.getElementById('canvas-area')
  const popup = document.createElement('div')
  popup.id = 'oxdna-live-playback'
  popup.hidden = true
  popup.style.cssText = 'position:absolute;top:12px;left:12px;z-index:30;padding:10px 12px;background:var(--bg-panel, #161b22);color:var(--text-primary, #e6edf3);border:1px solid #444;border-radius:6px;box-shadow:0 3px 12px #0006;font-size:12px;'
  popup.innerHTML = '<strong>Live oxDNA</strong><label style="display:flex;gap:6px;align-items:center;margin-top:8px;cursor:pointer"><input id="oxdna-live-smooth" type="checkbox" title="Smooth motion using neighboring frames; buffers four incoming frames to absorb delays"> Smooth</label><div class="live-buffer-status" style="margin-top:6px"></div><details style="margin-top:6px"><summary>Timing</summary><pre class="live-timing" style="font-size:11px;margin-bottom:0"></pre></details>'
  popup.querySelector('input').addEventListener('change', e => onSmooth(e.target.checked))
  for (const event of ['pointerdown', 'click', 'dblclick', 'wheel']) popup.addEventListener(event, e => e.stopPropagation())
  host?.append(popup)
  return {
    show: value => { popup.hidden = !value },
    update(d) {
      popup.querySelector('.live-buffer-status').textContent = !d.smooth ? '' : d.buffering
        ? `Buffering ${d.buffered}/${d.bufferTarget} frames…` : `Smooth · ${d.buffered} frames queued`
      const ms = value => Number.isFinite(value) ? `${Math.round(value)} ms` : '—'
      popup.querySelector('.live-timing').textContent = [
        `Frame arrival: ${ms(d.arrivalMs)}  Request: ${ms(d.requestMs)} (max ${ms(d.maxRequestMs)})`,
        `Simulation: ${ms(d.backend?.step_ms)} (max ${ms(d.backendMax?.step_ms)})`,
        `Capture: ${ms(d.backend?.capture_ms)} (max ${ms(d.backendMax?.capture_ms)})`,
        `Source age: ${ms(d.backend?.age_ms)}`,
        `Curve setup: ${ms(d.prepareMs)} (max ${ms(d.maxPrepareMs)})`,
        `Scene update: ${ms(d.drawMs)} (max ${ms(d.maxDrawMs)})`,
        `Longest render gap: ${ms(d.maxRenderGapMs)}`,
        `Buffer stalls: ${d.underruns}  Repeated snapshots: ${d.duplicates}`,
        `Coalesced frames: ${d.coalescedFrames}`,
      ].join('\n')
    },
  }
}
