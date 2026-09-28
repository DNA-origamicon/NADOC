/** Bounded, backpressured playback: one requested frame and one GPU frame. */
import { decodeCandoView } from '../scene/cando_large_view.js'
import { initFrameSteppers } from './frame_steppers.js'

export function initSnupiTrajectoryPlayer({ api, view, onPrepare, onStop }) {
  let epoch = 0, abort = null, timer = null, playing = false, busy = false
  let job = null, index = 0, count = 0, wired = false, steppers = null, error = null
  const el = id => typeof document === 'undefined' ? null : document.getElementById(`snupi-traj-${id}`)
  function status() {
    if (el('frame')) el('frame').textContent = error || `${index + 1}/${count}${busy ? ' · loading' : ''}`
    if (el('scrubber')) { el('scrubber').max = String(count - 1); el('scrubber').value = String(index) }
    if (el('play')) el('play').textContent = playing ? '⏸' : '▶'
    steppers?.refresh()
  }
  function pause() { playing = false; clearTimeout(timer); timer = null; status() }
  function schedule() {
    clearTimeout(timer)
    if (playing && !busy && count > 1) timer = setTimeout(() => { seek((index + 1) % count) }, 1000 / 12)
  }
  async function seek(frame, onProgress) {
    const request = ++epoch
    abort?.abort(); abort = new AbortController()
    busy = true; error = null; status()
    try {
      const buffer = await api.getSnupiTrajectoryFrameBin(job, frame, { signal: abort.signal,
        onProgress: p => { if (request === epoch) onProgress?.({ phase: 'trajectory-frame', ...p }) } })
      if (request !== epoch) return { ok: false }
      const next = decodeCandoView(buffer)
      if (!Number.isInteger(next.meta.frames) || next.meta.frames < 1 || next.meta.frame !== frame) throw new Error('Invalid trajectory frame')
      if (typeof requestAnimationFrame === 'function') await new Promise(requestAnimationFrame)
      if (request !== epoch) return { ok: false }
      if (!count) { onPrepare?.(); view.update(next) } else view.updatePositions(next)
      index = frame; count = next.meta.frames
      return { ok: true, frames: count }
    } catch (e) {
      if (request !== epoch || e?.name === 'AbortError') return { ok: false }
      pause(); error = `Frame failed: ${e?.message || 'unavailable'}`
      return { ok: false, reason: error }
    } finally {
      if (request === epoch) { busy = false; status(); schedule() }
    }
  }
  function play() { if (playing) return; playing = true; status(); schedule() }
  function wire() {
    if (wired) return
    wired = true
    el('play')?.addEventListener('click', () => playing ? pause() : play())
    el('scrubber')?.addEventListener('input', e => { const frame = Number(e.target.value) || 0; pause(); seek(frame) })
    steppers = initFrameSteppers({ prevBtn: el('prev'), nextBtn: el('next'), wrap: true,
      count: () => count, current: () => index, onStep: i => { pause(); seek(i) } })
  }
  function stop() {
    ++epoch; abort?.abort(); abort = null; pause(); busy = false
    job = null; count = 0; error = null
    if (el('controls')) el('controls').style.display = 'none'
    view?.clear(); onStop?.()
  }
  async function show(jobId, onProgress) {
    stop(); job = jobId; wire()
    const result = await seek(0, onProgress)
    if (result.ok) { if (el('controls')) el('controls').style.display = 'flex'; play() }
    return result
  }
  return { show, stop, pause, play, seek, cancelPending: () => { ++epoch; abort?.abort(); busy = false; pause() }, info: () => count ? { frame: index + 1, total: count } : null }
}
