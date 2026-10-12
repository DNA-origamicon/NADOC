import { docHeaders } from '../shared/doc_id.js'
import { parseOxdnaTrajectoryBin } from './oxdna_trajectory_bin.js'

export function trajectorySelection(first, last, interval, available) {
  if (![first, last, interval, available].every(Number.isSafeInteger) || first < 1 || last > available || first > last || interval < 1) return null
  return { first, last, interval, count: Math.floor((last - first) / interval) + 1 }
}

/** Full-only playback, two coordinate pages, one network request and one render in flight.
 * Source IDs are one-based; API indices are zero-based and sampled globally.
 * Neither opening a job nor selecting Trajectory downloads coordinates.
 */
export function createVRSimulationTrajectory({ api, controller, ensureFull, companion = () => null, changed = () => {}, request = fetch, clock = () => performance.now() }) {
  let seekSequence = 0, generation = 0, abort = null, timer = null, context = '', engine = '', job = '', scope = 'job', ctrl = null, overlays = null
  let pages = new Map(), pending = null, renderedPage = null, metadataPending = false
  let state = empty(), lastStep = 0
  function empty() { return { available: 0, first: 1, last: 0, interval: 1, count: 0, index: 0, phase: 'idle', playing: false, smooth: false, progress: -1, message: 'Select Load to prepare frames', source: 1 } }
  function pause() { state.playing = false; clearTimeout(timer); timer = null; ctrl?.setPlaying?.(false); ctrl?.pauseTrajectory?.() }
  function cancel(notify = true) { ++generation; ++seekSequence; abort?.abort(); abort = null; pending = null; metadataPending = false; pause(); overlays?.setEnabled(false); overlays?.clear?.(); pages.clear(); renderedPage = null; state.phase = 'idle'; state.progress = -1; state.message = 'Load cancelled'; ctrl?.cancelPendingLoad?.(); if (notify) changed() }
  async function select(nextEngine, nextJob, nextScope = 'job') {
    const key = `${nextEngine}:${nextJob}:${nextScope}`
    if (context === key && state.phase !== 'error') return
    cancel(); context = key; engine = nextEngine; job = nextJob; scope = nextScope; ctrl = controller(engine); overlays = companion(engine)
    state = empty(); state.phase = 'metadata'; state.message = 'Reading trajectory frame count'; metadataPending = true
    const current = generation
    try {
      const meta = engine === 'namd' ? await api.getMdTrajectoryMeta(job, { stride: 1 })
        : engine === 'oxdna' ? await api.getOxdnaTrajectoryMeta(job, scope)
        : engine === 'lammps' ? await api.getLammpsTrajectoryMeta(job)
        : await api.getSnupiTrajectoryMeta(job)
      if (current !== generation) return
      state.available = Number(meta?.total_raw ?? meta?.n_frames ?? meta?.frames) || 0
      state.last = state.available; state.interval = Math.max(1, Math.ceil(state.available / 200))
      state.count = trajectorySelection(state.first, state.last, state.interval, state.available)?.count || 0
      state.phase = state.available ? 'idle' : 'error'; state.message = state.available ? 'Set range and interval, then Load' : 'No trajectory frames available'
    } catch (error) { if (current === generation) { state.phase = 'error'; state.message = error.message } }
    finally { if (current === generation) { metadataPending = false; changed() } }
  }
  function configure(values) {
    if (metadataPending) return false
    const next = trajectorySelection(values.first ?? state.first, values.last ?? state.last, values.interval ?? state.interval, state.available)
    if (!next) return false
    cancel(false); Object.assign(state, next, { index: 0, source: next.first, message: 'Range changed; press Load' }); changed(); return true
  }
  async function pageFor(index, expectedGeneration) {
    const start = Math.floor(index / 8) * 8
    if (pages.has(start)) return pages.get(start)
    if (pending) { await pending; if (expectedGeneration !== generation) return null; if (pages.has(start)) return pages.get(start) }
    const current = generation, selection = { ...state }, first = selection.first - 1 + start * selection.interval
    const end = Math.min(start + 7, selection.count - 1), last = selection.first - 1 + end * selection.interval
    abort = new AbortController()
    state.message = `Reading frames ${first + 1}–${last + 1}`; state.progress = -1; changed()
    let progressTimer, progressStopped = false
    const progressApi = engine === 'namd' ? api.getMdTrajectoryProgress : engine === 'oxdna' ? api.getOxdnaTrajectoryProgress : null
    const reportProgress = async () => {
      try {
        const p = await progressApi?.(job)
        if (current === generation && !progressStopped && p?.phase) {
          state.progress = p.total > 0 ? Math.min(.99, p.done / p.total) : -1
          state.message = `${p.phase} · frames ${first + 1}–${last + 1}${p.total > 0 ? ` · ${Math.round(state.progress * 100)}%` : ''}`
          changed()
        }
      } catch { /* Coordinate request owns errors; keep its loading indicator. */ }
      if (current === generation && !progressStopped) progressTimer = setTimeout(reportProgress, 500)
    }
    if (progressApi) progressTimer = setTimeout(reportProgress, 500)
    const promise = (async () => {
      const prefix = engine === 'namd' ? 'md' : engine
      const url = `/api/${prefix}/jobs/${encodeURIComponent(job)}/trajectory-bin?stride=1&scope=${scope}&align=true&frame_start=${first}&frame_end=${last}&frame_step=${selection.interval}`
      const response = await request(url, { headers: docHeaders(), signal: abort.signal })
      progressStopped = true; clearTimeout(progressTimer)
      if (!response.ok) throw new Error(`Trajectory load failed (${response.status})`)
      const total = Number(response.headers?.get('X-NADOC-Uncompressed-Length') || response.headers?.get('Content-Length'))
      let buffer
      if (response.body?.getReader && total > 0 && total < 512 * 1024 * 1024) {
        const chunks = [], reader = response.body.getReader(); let loaded = 0
        for (;;) { const { done, value } = await reader.read(); if (done) break; chunks.push(value); loaded += value.byteLength
          if (current !== generation) { await reader.cancel(); return null }
          state.progress = Math.min(.99, loaded / total); state.message = `Downloading frames · ${Math.round(state.progress * 100)}%`; changed()
        }
        const data = new Uint8Array(loaded); let at = 0; for (const chunk of chunks) { data.set(chunk, at); at += chunk.length } buffer = data.buffer
      } else buffer = await response.arrayBuffer()
      if (current !== generation) return null
      const payload = parseOxdnaTrajectoryBin(buffer)
      if (!payload || payload.frames.length !== end - start + 1) throw new Error('Incomplete trajectory page')
      const page = { start, payload }; pages.set(start, page)
      while (pages.size > 2) pages.delete(pages.keys().next().value)
      return page
    })()
    pending = promise
    try { return await promise } finally { progressStopped = true; clearTimeout(progressTimer); if (pending === promise) pending = null }
  }
  async function seek(index, { initial = false } = {}) {
    if (!initial && !['ready', 'buffering'].includes(state.phase)) return false
    const seekId = ++seekSequence, current = generation, i = Math.max(0, Math.min(state.count - 1, Math.round(index)))
    state.phase = initial ? 'loading' : 'buffering'
    try {
      if (engine === 'snupi') {
        const source = state.first - 1 + i * state.interval
        const result = initial ? await ctrl.showTrajectory(job, null, { autoplay: false, frame: source }) : await ctrl.seekFullTrajectoryFrame(source)
        if (current !== generation || seekId !== seekSequence) return false
        if (!result?.ok) throw new Error(result?.reason || 'Could not prepare Full trajectory')
        state.index = i; state.source = source + 1; state.phase = 'ready'; state.progress = 1; state.message = 'Ready'; renderedPage = true; changed(true); return true
      }
      const page = await pageFor(i, current)
      if (!page || current !== generation || seekId !== seekSequence) return false
      if (initial) {
        const result = await ctrl.loadFullTrajectoryPage(job, page.payload)
        if (!result?.ok) throw new Error(result?.reason || 'Could not prepare Full trajectory')
      }
      if (current !== generation || seekId !== seekSequence) return false
      if (overlays) {
        state.message = 'Preparing ions and periodic cell'; state.progress = -1; changed()
        const frames = page.payload.frames.map((_, n) => state.first - 1 + (page.start + n) * state.interval)
        await overlays.setJob(job, { stride: 1, nFrames: state.available, frameIndices: frames, frameIdx: frames[i - page.start], deferDraw: true })
        if (current !== generation || seekId !== seekSequence) return false
        overlays.setEnabled(true, 'traj')
        const ready = await overlays.prepareAll({ onProgress: p => { if (current === generation) { state.progress = p.total > 0 ? p.done / p.total : -1; changed() } } })
        if (current !== generation || seekId !== seekSequence) return false
        if (!ready) throw new Error('Could not load ions or periodic cell; retry Load')
      }
      if (!ctrl.showFullTrajectoryFrame(page.payload, i - page.start)) throw new Error('Switch to Full representation to continue')
      overlays?.showFrame(state.first - 1 + i * state.interval)
      renderedPage = page; state.index = i; state.source = state.first + i * state.interval; state.phase = 'ready'; state.progress = 1
      state.message = `${state.count} selected frames · 16 maximum buffered`; changed(true)
      // Decode the next page while the current one is playing. One request and
      // two pages remain the hard bounds; a seek still owns error reporting.
      if (state.playing && i - page.start >= 3 && page.start + 8 < state.count && !pending) void pageFor(page.start + 8, current).catch(() => {})
      return true
    } catch (error) { if (current === generation && error.name !== 'AbortError') { pause(); state.phase = 'error'; state.message = error.message; changed() } return false }
  }
  async function load() {
    if (!trajectorySelection(state.first, state.last, state.interval, state.available) || metadataPending) return false
    cancel(); const current = generation; state.phase = 'loading'; state.message = 'Preparing Full representation'; changed()
    try { await ensureFull() }
    catch (error) { if (current === generation) { state.phase = 'error'; state.message = error.message; changed() } return false }
    if (current !== generation) return false
    return seek(0, { initial: true })
  }
  async function step() {
    if (!state.playing) return
    if (state.index >= state.count - 1) { pause(); changed(); return }
    lastStep = clock()
    const next = state.index + 1, current = generation
    if (state.smooth && engine !== 'snupi' && next % 8 !== 0 && renderedPage) {
      const from = state.index - renderedPage.start, to = next - renderedPage.start
      await ctrl.ensureInterpolationFrames?.(from, to)
      if (current !== generation || !state.playing) return
      for (let sample = 1; sample <= 3; sample++) {
        await new Promise(resolve => setTimeout(resolve, 1000 / 48))
        if (current !== generation || !state.playing) return
        ctrl.showInterpolatedFrame?.(from, to, sample / 4); overlays?.showInterpolatedFrame(state.first - 1 + state.index * state.interval, state.first - 1 + next * state.interval, sample / 4); changed(true)
      }
    }
    if (current === generation && state.playing) await seek(next)
    if (state.playing) timer = setTimeout(step, Math.max(0, 1000 / 12 - (clock() - lastStep)))
  }
  function toggle() { if (!state.playing && state.phase === 'ready' && state.index === state.count - 1 && state.count > 1) { const current = generation; void seek(0).then(ok => { if (ok && current === generation) toggle() }); return } if (state.playing) pause(); else if (state.phase === 'ready' && state.count > 1) { state.playing = true; timer = setTimeout(step, 0) } changed() }
  return { select, configure, load, cancel, pause, toggle, seek, refreshCompanions() { pause(); return seek(state.index) }, smooth() { state.smooth = !state.smooth; changed() }, snapshot: () => ({ ...state }),
    reset() { cancel(); context = ''; state = empty() }, dispose() { cancel() },
    get active() { return !!renderedPage }, get busy() { return !!pending || metadataPending } }
}
