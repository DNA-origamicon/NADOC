import { presentSmoothTransition } from './vr_smooth_pacing.js'
import { docHeaders } from '../shared/doc_id.js'
import { parseOxdnaTrajectoryBin } from './oxdna_trajectory_bin.js'

export function trajectorySelection(first, last, interval, available) {
  if (![first, last, interval, available].every(Number.isSafeInteger) || first < 1 || last > available || first > last || interval < 1) return null
  return { first, last, interval, count: Math.floor((last - first) / interval) + 1 }
}

/** Two coordinate pages, one network request and one render in flight.
 * Small selections prepare one resident page before Ready; large ones stream.
 * Source IDs are one-based; API indices are zero-based and sampled globally.
 * Neither opening a job nor selecting Trajectory downloads coordinates.
 */
export function createVRSimulationTrajectory({ api, controller, ensureFull, prepareFrame = async () => {}, companion = () => null, changed = () => {}, delivery = () => ({}), request = fetch, clock = () => performance.now() }) {
  let seekSequence = 0, generation = 0, abort = null, timer = null, context = '', engine = '', job = '', scope = 'job', ctrl = null, overlays = null
  let pages = new Map(), pending = null, renderedPage = null, metadataPending = false
  let state = empty(), lastStep = 0, pageSize = 8, resident = false, smoothChosen = false, playback = 0
  function empty() { return { available: 0, first: 1, last: 0, interval: 1, count: 0, index: 0, phase: 'idle', playing: false, smooth: false, loop: false, progress: -1, message: 'Select Load to prepare frames', source: 1 } }
  function pause() { ++playback; state.playing = false; clearTimeout(timer); timer = null; ctrl?.setPlaying?.(false); ctrl?.pauseTrajectory?.() }
  function cancel(notify = true) { ++generation; ++seekSequence; abort?.abort(); abort = null; pending = null; metadataPending = false; pause(); overlays?.setEnabled(false); overlays?.clear?.(); pages.clear(); renderedPage = null; pageSize = 8; resident = false; state.phase = 'idle'; state.progress = -1; state.message = 'Load cancelled'; ctrl?.cancelPendingLoad?.(); if (notify) changed() }
  async function select(nextEngine, nextJob, nextScope = 'job') {
    const key = `${nextEngine}:${nextJob}:${nextScope}`
    if (context === key && state.phase !== 'error') return
    cancel(); context = key; engine = nextEngine; job = nextJob; scope = nextScope; ctrl = controller(engine); overlays = companion(engine)
    state = empty(); smoothChosen = false; state.phase = 'metadata'; state.message = 'Reading trajectory frame count'; metadataPending = true
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
    const start = Math.floor(index / pageSize) * pageSize
    if (pages.has(start)) return pages.get(start)
    if (pending) { await pending; if (expectedGeneration !== generation) return null; if (pages.has(start)) return pages.get(start) }
    const current = generation, selection = { ...state }, first = selection.first - 1 + start * selection.interval
    const end = Math.min(start + pageSize - 1, selection.count - 1), last = selection.first - 1 + end * selection.interval
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
      payload.frame_start = first; payload.frame_step = selection.interval; payload.scope = scope
      const page = { start, payload }; pages.set(start, page)
      while (pages.size > 2) pages.delete(pages.keys().next().value)
      return page
    })()
    pending = promise
    try { return await promise } finally { progressStopped = true; clearTimeout(progressTimer); if (pending === promise) pending = null }
  }
  async function seek(index, { initial = false, forceCompanions = false } = {}) {
    if (!initial && !['ready', 'buffering'].includes(state.phase)) return false
    const seekId = ++seekSequence, current = generation, i = Math.max(0, Math.min(state.count - 1, Math.round(index)))
    const trace=stage=>globalThis.__nadocVRPlaybackTrace?.({stage,epoch_ms:performance.timeOrigin+performance.now(),index:i,source:state.first+i*state.interval})
    trace('seek_start')
    state.phase = initial ? 'loading' : 'buffering'
    try {
      if (engine === 'snupi') {
        const source = state.first - 1 + i * state.interval
        const result = initial ? await ctrl.showTrajectory(job, null, { autoplay: false, frame: source }) : await ctrl.seekFullTrajectoryFrame(source)
        if (current !== generation || seekId !== seekSequence) return false
        if (!result?.ok) throw new Error(result?.reason || 'Could not prepare trajectory')
        state.message = 'Preparing selected representation'; state.progress = -1; changed()
        await prepareFrame()
        if (current !== generation || seekId !== seekSequence) return false
        state.index = i; state.source = source + 1; state.phase = 'ready'; state.progress = 1; state.message = 'Ready'; renderedPage = true; changed(true); return true
      }
      let page = await pageFor(i, current)
      if (!page || current !== generation || seekId !== seekSequence) return false
      if (initial) {
        const result = await ctrl.loadFullTrajectoryPage(job, page.payload)
        if (!result?.ok) throw new Error(result?.reason || 'Could not prepare trajectory')
      }
      if (current !== generation || seekId !== seekSequence) return false
      const preparing = initial || page !== renderedPage || forceCompanions
      if (preparing) { state.message = 'Preparing exact trajectory frames'; changed() }
      const capacity = await ctrl.prepareFullTrajectoryFrames?.(page.payload) ?? 0
      if (current !== generation || seekId !== seekSequence) return false
      // Price the complete selection using actual coordinate payloads. Surfaces
      // and controllers without bounded atomic preparation retain small pages.
      const coarseBytes = page.payload.frames.reduce((n, f) => n + f.byteLength, 0)
      if (initial && state.count <= 200 && capacity >= state.count &&
          coarseBytes / page.payload.frames.length * state.count <= 32 * 1024 * 1024) {
        resident = true
        if (!smoothChosen && Number.isFinite(capacity)) state.smooth = true
        if (state.count > pageSize) {
          pageSize = state.count; pages.clear()
          page = await pageFor(i, current)
          if (!page || current !== generation || seekId !== seekSequence) return false
          state.message = 'Preparing all selected atom frames'; changed()
          await ctrl.prepareFullTrajectoryFrames(page.payload)
          if (current !== generation || seekId !== seekSequence) return false
        }
      }
      if (overlays && preparing) {
        state.message = 'Preparing ions and periodic cell'; state.progress = -1; changed()
        const frames = page.payload.frames.map((_, n) => state.first - 1 + (page.start + n) * state.interval)
        await overlays.setJob(job, { stride: 1, nFrames: state.available, frameIndices: frames, frameIdx: frames[i - page.start], deferDraw: true })
        if (current !== generation || seekId !== seekSequence) return false
        overlays.setEnabled(true, 'traj')
        const ready = await overlays.prepareAll({ onProgress: p => { if (current === generation) { state.progress = p.total > 0 ? p.done / p.total : -1; changed() } } })
        if (current !== generation || seekId !== seekSequence) return false
        if (!ready) throw new Error('Could not load ions or periodic cell; retry Load')
      }
      if (preparing) { state.message = 'Preparing selected representation'; state.progress = -1; changed() }
      trace('apply_start')
      if (!await ctrl.showFullTrajectoryFrame(page.payload, i - page.start)) throw new Error('Could not display the selected frame')
      if (current !== generation || seekId !== seekSequence) return false
      trace('apply_end')
      overlays?.showFrame(state.first - 1 + i * state.interval)
      trace('companions_end')
      renderedPage = page; state.index = i; state.source = state.first + i * state.interval; state.phase = 'ready'; state.progress = 1
      state.message = resident ? `${state.count} selected frames prepared` : `${state.count} selected frames · 16 maximum buffered`; changed(true)
      // Decode the next page while the current one is playing. One request and
      // two pages remain the hard bounds; a seek still owns error reporting.
      if (state.playing && i - page.start >= 3 && page.start + pageSize < state.count && !pending) void pageFor(page.start + pageSize, current).catch(() => {})
      return true
    } catch (error) { if (current === generation && error.name !== 'AbortError') { pause(); state.phase = 'error'; state.message = error.message; changed() } return false }
  }
  async function load() {
    if (!trajectorySelection(state.first, state.last, state.interval, state.available) || metadataPending) return false
    cancel(); const current = generation; state.phase = 'loading'; state.message = 'Preparing representation'; changed()
    try { await ensureFull() }
    catch (error) { if (current === generation) { state.phase = 'error'; state.message = error.message; changed() } return false }
    if (current !== generation) return false
    return seek(0, { initial: true })
  }
  async function step(run) {
    if (run !== playback || !state.playing) return
    if (state.count < 2 || (state.index >= state.count - 1 && !state.loop)) { pause(); changed(); return }
    lastStep = clock()
    const next = (state.index + 1) % state.count, current = generation
    if (state.smooth && engine !== 'snupi' && next !== 0 && next % pageSize !== 0 && renderedPage) {
      const from = state.index - renderedPage.start, to = next - renderedPage.start
      try {
        await presentSmoothTransition({
          prepare: () => ctrl.ensureInterpolationFrames?.(from, to),
          active: () => current === generation && run === playback && state.playing && state.smooth,
          delivery, wait: milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)),
          show: fraction => {
            ctrl.showInterpolatedFrame?.(from, to, fraction)
            overlays?.showInterpolatedFrame(state.first - 1 + state.index * state.interval, state.first - 1 + next * state.interval, fraction)
            globalThis.__nadocVRPlaybackTrace?.({stage:'interpolation_applied',epoch_ms:performance.timeOrigin+performance.now(),from:state.index,to:next,fraction})
            changed(true)
          },
        })
      } catch (error) {
        if (current === generation && run === playback) { pause(); state.phase = 'error'; state.message = error.message; changed() }
        return
      }
    } else if (state.smooth && engine !== 'snupi') {
      // Page boundaries and loop wraps remain exact; hold the same nominal pace.
      await new Promise(resolve => setTimeout(resolve, 250))
    }
    if (current === generation && run === playback && state.playing) await seek(next)
    if (current === generation && run === playback && state.playing) timer = setTimeout(() => step(run), Math.max(0, 1000 / 12 - (clock() - lastStep)))
  }
  function toggle() { if (!state.playing && state.phase === 'ready' && state.index === state.count - 1 && state.count > 1) { const current = generation; void seek(0).then(ok => { if (ok && current === generation) toggle() }); return } if (state.playing) pause(); else if (state.phase === 'ready' && state.count > 1) { state.playing = true; ctrl?.setPlaying?.(true); const run = ++playback; timer = setTimeout(() => step(run), 0) } changed() }
  return { select, configure, load, cancel, pause, toggle, seek, refreshCompanions() { pause(); return seek(state.index, { forceCompanions: true }) }, smooth() { smoothChosen = true; state.smooth = !state.smooth; changed() }, loop() { state.loop = !state.loop; changed() }, snapshot: () => ({ ...state }),
    reset() { cancel(); context = ''; state = empty() }, dispose() { cancel() },
    get active() { return !!renderedPage }, get busy() { return !!pending || metadataPending } }
}
