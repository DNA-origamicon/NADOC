import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { icon } from './primitives/icon.js'
import { createEMPlaybackPreparation } from './em_playback_preparation.js'
import { registerEMExport, registerEMClear } from '../scene/em_export.js'
import { createEMFrameCache } from './em_frame_cache.js'
import { createEMFieldOverlay, prepareEMField } from '../scene/em_field.js'
import { loadEMSettings, opticalSettings, displaySettings } from './em_settings.js'

/** Extract only loaded optical frames; never drive/scrub the molecular scene. */
export function trajectoryEMFrames(data, particles, stationary = false) {
  if (!data?.frames) throw new Error('Load a trajectory before running EM Analysis.')
  const cores = (data.keys ?? []).map((key, index) => ({ key,index })).filter(({key}) => key[0] === '__gold__')
  if (!cores.length && !stationary) throw new Error('This trajectory has no gold-core positions. Load a trajectory that includes its nanoparticles.')
  if (cores.length && (cores.length !== particles.length || new Set(cores.map(c => c.key[1])).size !== particles.length || cores.some(c => !Number.isInteger(c.key[1]) || c.key[1] < 0 || c.key[1] >= particles.length))) throw new Error('Trajectory gold cores do not match the displayed nanoparticles.')
  const entries = []
  data.frames.forEach((frame, i) => {
    if (!frame?.length) return
    const stride = data.keys.length ? frame.length/data.keys.length : 0
    if (cores.length && ![6,9,12].includes(stride)) throw new Error('Unsupported nanoparticle trajectory layout.')
    const mapped = particles.map((particle, index) => {
      const core = cores.find(c => c.key[1] === index)
      const center_nm = core ? Array.from(frame.slice(core.index*stride, core.index*stride+3)) : [...particle.center_nm]
      if (!center_nm.every(Number.isFinite)) throw new Error('Trajectory contains invalid gold-core positions.')
      return { ...particle, center_nm }
    })
    entries.push({ frame_index:(data.frameStart ?? 0)+i*(data.frameStep ?? 1), particles:mapped })
  })
  if (!entries.length) throw new Error('No trajectory frames are loaded.')
  return entries
}

/** Visit sparse/paged trajectories without retaining molecular pages or moving the scene. */
export async function collectTrajectoryEMFrames(data, particles, stationary, live = () => true) {
  const frames = []
  for (let i = 0; i < data.frames.length; i++) {
    if (!live()) throw new Error('EM preparation cancelled.')
    const frame = data.frames[i] ?? await data.readFrame?.(i)
    if (!live()) throw new Error('EM preparation cancelled.')
    if (!frame?.length) throw new Error(`Trajectory frame ${i + 1} could not be loaded.`)
    frames.push(...trajectoryEMFrames({...data, frames:[frame],
      frameStart:(data.frameStart ?? 0) + i*(data.frameStep ?? 1)}, particles, stationary))
  }
  return frames
}

export function initEMSimulation({ scene, api, store, displays, captureSimulation, openSettings,
  addFrameCallback, removeFrameCallback, overlayFactory = createEMFieldOverlay }) {
  const controls = []
  let overlay = null
  let settings = loadEMSettings(), active = null, last = '', generation = 0, abort = null
  let pendingCancel = Promise.resolve(), pendingKey = '', pendingAt = 0
  let resultParticles = null
  const sameParticles = (a,b) => a?.length === b?.length && a.every((p,i) => p.id === b[i].id && p.diameter_nm === b[i].diameter_nm && p.center_nm.every((v,j) => Math.abs(v-b[i].center_nm[j]) < 1e-5))
  let batch = null, result = null, shown = '', busy = false, lastTick = 0, disposed = false, dialog = null
  const status = text => { for (const c of controls) c.status.textContent = c === active ? text : '' }
  const redraw = () => { if (result && active?.toggle.checked) (overlay ??= overlayFactory(scene)).show(result, displaySettings(settings)) }
  const unregisterClear = registerEMClear(scene,()=>{for(const c of controls)c.toggle.checked=false;active=null;reset()})
  const unregisterExport = registerEMExport(scene, async () => {
    if (!active?.toggle.checked) return
    const token = generation, current = batch
    const display = displays[active.engine](), data = display?.emTrajectory?.()
    if (current) {
      if (!display?.isActive?.() || current.context !== context(display) || current.key !== data?.key)
        throw new Error('The exported trajectory differs from the EM analysis. Analyze this trajectory range before exporting.')
      const indices = data.transition && data.transition.t > 0 && data.transition.t < 1
        ? [data.transition.from,data.transition.to] : [data.currentIndex]
      if (!indices.every(i=>current.ready.includes(i))) {
        const progress = await request('GET', `/em-analysis/trajectories/${current.id}`)
        if (token !== generation) throw new Error('EM changed during export.')
        current.ready = progress.frames
      }
      if (!indices.every(i=>current.ready.includes(i)) || !await current.cache.ensure(current.ready,indices))
        throw new Error('EM is not ready for this frame. Complete trajectory EM analysis before exporting.')
      if (token !== generation || batch !== current) throw new Error('EM changed during export.')
      showCachedFrame()
      if (active.frameStatus.textContent && !active.frameStatus.textContent.startsWith('EM visual interpolation'))
        throw new Error(active.frameStatus.textContent)
    } else {
      if (!result || busy || !sameParticles(captureSimulation(),resultParticles))
        throw new Error('Calculate EM for the displayed state before exporting, or turn off EM visualization.')
      redraw()
    }
  })
  async function request(method, path, payload, signal) {
    let error
    const data = await api._request(method, path, payload, { signal, suppressBusy:true, protectedRetry:false,
      timeoutMs:190000, onError:(_, detail) => { error = api.errorDetailToMessage?.(detail) || (typeof detail === 'string' ? detail : detail?.message) } })
    if (!data) throw new Error(error || 'EM request failed.')
    return data
  }
  function clearBatch() {
    const previous = batch; batch = null; shown = ''
    previous?.releasePlayback?.()
    previous?.cache.dispose()
    previous?.restorePlayback?.()
    for (const c of controls) { c.progress.hidden = true; c.frameStatus.textContent = '' }
    if (previous?.id) pendingCancel = request('DELETE', `/em-analysis/trajectories/${previous.id}`).catch(() => {})
  }
  function reset() {
    generation++; abort?.abort(); abort = null; busy = false; last = ''; result = null; pendingKey = ''
    overlay?.clear(); clearBatch()
  }
  async function snapshot(particles, key) {
    const token = ++generation; abort?.abort(); abort = new AbortController(); busy = true
    result = null; overlay?.clear(); status('Calculating EM for the displayed state…')
    try {
      await pendingCancel
      if (token !== generation) return
      const next = await request('POST', '/em-analysis/solve', { particles, ...opticalSettings(settings) }, abort.signal)
      if (token !== generation || disposed) return
      if (context(displays[active.engine]()) + JSON.stringify(captureSimulation()) !== key) return
      result = next; resultParticles = particles; last = key; redraw(); status('EM applied to the displayed state.')
    } catch (error) { if (token === generation) { last = key; status(error.message) } }
    finally { if (token === generation) busy = false }
  }
  function context(display) {
    const state = store.getState()
    return JSON.stringify([state.currentDesign?.id, state.currentAssembly?.id, display?.activeJobId?.(), display?.mode?.(), display?.alignment?.()])
  }
  function showCachedFrame() {
    if (!batch || !active?.toggle.checked) return
    const display = displays[active.engine](), data = display?.emTrajectory?.()
    if (!display?.isActive?.() || batch.context !== context(display) || batch.key !== data?.key) {
      reset(); return
    }
    const blend = data.transition
    batch.cache.protect(blend ? [blend.from,blend.to] : [data.currentIndex])
    if (blend && blend.t > 0 && blend.t < 1) {
      const a = batch.byIndex.get(blend.from), b = batch.byIndex.get(blend.to)
      const first = batch.cache.get(blend.from), second = batch.cache.get(blend.to)
      let matches = false
      try {
        const expected = a && trajectoryEMFrames({...data,frames:[blend.frame]}, a.particles, active.engine === 'md')[0].particles
        matches = expected && sameParticles(captureSimulation(),expected)
      } catch { /* obsolete or unavailable molecular pose */ }
      result = null
      if (!a || !b || !first || !second || !matches) {
        overlay?.clear(); shown = ''
        active.frameStatus.textContent = 'Buffering EM transition…'
        return
      }
      active.frameStatus.textContent = 'EM visual interpolation between calculated frames.'
      shown = `${batch.id}:${blend.from}:${blend.to}:${blend.t}`
      ;(overlay ??= overlayFactory(scene)).showTransition(first,second,blend.t,displaySettings(settings))
      return
    }
    const expected = batch.byIndex.get(data.currentIndex)?.particles
    let matches = false
    try { matches = expected && sameParticles(captureSimulation(), expected) } catch { /* unloaded */ }
    batch.cache.demand(batch.ready, data.currentIndex, {playing:data.playing})
    const next = batch.cache.get(data.currentIndex)
    active.frameStatus.textContent = !expected ? 'This frame was not included in the analysis.'
      : !batch.ready.includes(data.currentIndex) ? 'EM has not finished analyzing this frame.'
      : !matches ? 'Waiting for the displayed nanoparticle pose to match this frame.'
      : !next ? 'Buffering EM for this frame…' : ''
    if (!matches || !next) { if (shown) overlay?.clear(); result = null; shown = ''; return }
    const identity = `${batch.id}:${data.currentIndex}`
    if (shown !== identity) { result = next; resultParticles = expected; shown = identity; redraw() }
  }
  function updateProgress(progress) {
    const c = active, data = displays[c.engine]()?.emTrajectory?.()
    const ready = new Set(progress.frames)
    const count = data?.frames.length || 1
    const segments = []
    for (let i = 0; i < count; i++) {
      if (ready.has((data.frameStart ?? 0)+i*(data.frameStep ?? 1))) {
        segments.push(`#e3b341 ${i/count*100}% ${(i+1)/count*100}%`)
      } else segments.push(`transparent ${i/count*100}% ${(i+1)/count*100}%`)
    }
    const percent = Math.round(100*progress.completed/Math.max(1,progress.total))
    c.progress.hidden = false
    c.progress.style.backgroundImage = `linear-gradient(to right, ${segments.join(',')})`
    c.progress.setAttribute('aria-valuenow', percent)
    c.progress.title = `EM analysis: ${percent}% (${progress.completed}/${progress.total} loaded frames)`
    status(`EM analysis: ${progress.completed}/${progress.total} loaded frames · ${percent}%${progress.error ? ' · '+progress.error : ''}`)
  }
  async function tick() {
    if (disposed) return
    showCachedFrame()
    if (result && active) {
      try { if (!sameParticles(captureSimulation(), resultParticles)) { result = null; shown = ''; overlay?.clear() } }
      catch { result = null; overlay?.clear() }
    }
    if (performance.now()-lastTick < 400) return
    lastTick = performance.now()
    for (const c of controls) c.trajectory.hidden = !displays[c.engine]()?.emTrajectory?.()?.frames?.some(f => f?.length)
    if (!active?.toggle.checked) return
    const display = displays[active.engine]()
    if (!display?.isActive?.()) { if (last || batch || busy) reset(); status('Select a simulation visualization to apply EM.'); return }
    let particles
    try { particles = captureSimulation() } catch (error) { if (busy || result || batch) reset(); status(error.message); overlay?.clear(); return }
    const data = display.emTrajectory?.()
    const key = context(display) + JSON.stringify(particles)
    if (batch) {
      if (batch.context !== context(display) || batch.key !== data?.key) { reset(); status('Visualization changed. Run EM Analysis for the loaded trajectory.'); return }
      if (busy) return
      const token = generation; busy = true
      try {
        if (!batch.complete) {
          const progress = await request('GET', `/em-analysis/trajectories/${batch.id}`)
          if (token !== generation || !batch) return
          batch.ready = progress.frames; batch.complete = progress.status === 'complete'
          updateProgress(progress)
          if (['failed','cancelled'].includes(progress.status)) batch.complete = true
        }
        showCachedFrame()
        const currentBatch = batch
        if (!currentBatch.prefetching) {
          currentBatch.prefetching = true
          void currentBatch.cache.prefetch(currentBatch.ready, displays[active.engine]()?.emTrajectory?.()?.currentIndex)
            .catch(error => { if (token === generation) status(error.message) })
            .finally(() => { currentBatch.prefetching = false })
        }
      } catch (error) { if (token === generation) status(error.message) }
      finally { if (token === generation) busy = false }
      return
    }
    if (data) { if (busy && abort) { generation++; abort.abort(); abort = null; busy = false } overlay?.clear(); result = null; status('Use EM Analysis to calculate all loaded trajectory frames. Smooth playback crossfades calculated fields between saved frames.'); return }
    if (key !== pendingKey) { pendingKey = key; pendingAt = performance.now(); generation++; abort?.abort(); busy = false; result = null; overlay?.clear(); return }
    if (performance.now()-pendingAt < 350) return
    if (key !== last && !busy) { last = key; void snapshot(particles, key) }
    else if (key !== last && busy) { generation++; abort?.abort(); busy = false; result = null; overlay?.clear() }
  }
  function activate(c, on) {
    reset()
    for (const other of controls) other.toggle.checked = other === c && on
    active = on ? c : null
    status(''); lastTick = 0; void tick()
  }
  function confirmTrajectory(c) {
    dialog?.close()
    const display = displays[c.engine](), data = display?.emTrajectory?.()
    let frames, particles
    try { particles = captureSimulation(); trajectoryEMFrames(data, particles, c.engine === 'md') }
    catch (error) { active = c; status(error.message); return }
    const capturedContext = context(display), optical = opticalSettings(settings)
    const body = document.createElement('div')
    const messages = [
      `EM analysis will run on all ${data.frames.length} selected trajectory frames using the current EM settings.`,
      'CPU/GPU selection respects other running simulations. This may take several minutes.',
    ]
    if (c.engine === 'md' && !data.keys.some(k => k[0] === '__gold__')) messages.push('NAMD fixed spheres retain their displayed positions in each frame.')
    for (const message of messages) {
      const paragraph = document.createElement('p'); paragraph.textContent = message; body.append(paragraph)
    }
    const no = createButton({label:'Cancel', onClick:()=>dialog?.close()})
    const yes = createButton({label:'Continue', variant:'primary'})
    yes.onclick = async () => {
      dialog.close(); dialog = null
      if (capturedContext !== context(displays[c.engine]()) || data.key !== displays[c.engine]()?.emTrajectory?.()?.key) { active = c; status('Trajectory changed. Open EM Analysis again.'); return }
      activate(c, true); const token = generation; busy = true
      status(`Preparing EM analysis for ${data.frames.length} trajectory frames…`)
      try {
        await pendingCancel
        frames = await collectTrajectoryEMFrames(data, particles, c.engine === 'md', () => token === generation && !disposed)
        if (token !== generation) return
        const job = await request('POST', '/em-analysis/trajectories', { frames:frames.map(f => ({ frame_index:f.frame_index, input:{ particles:f.particles, ...optical } })) })
        if (token !== generation || disposed) { await request('DELETE', `/em-analysis/trajectories/${job.id}`); return }
        batch = { id:job.id, frames, byIndex:new Map(frames.map(f=>[f.frame_index,f])), key:data.key, context:capturedContext, ready:[], complete:false }
        batch.cache = createEMFrameCache({
          onError: error => { if (token === generation) status(error.message) },
          onReady: () => { if (token === generation) showCachedFrame() },
          load: (index, ordinal, signal) => request('GET', `/em-analysis/trajectories/${job.id}/frames/${ordinal}`, undefined, signal),
          prepare: volume => { if (volume.intensity) prepareEMField(volume, displaySettings(settings)) },
        })
        const currentBatch = batch
        display.setEMPlaybackPreparation?.(createEMPlaybackPreparation({batch:currentBatch,
          live:() => token === generation && batch === currentBatch && !disposed
            && display.emTrajectory?.()?.key === data.key && context(display) === capturedContext,
          onError:error => status(error.message)}))
        batch.releasePlayback = () => display.setEMPlaybackPreparation?.(null)
        const smooth = document.getElementById(`${c.engine}-jobs-traj-interpolate`)
        if (smooth) {
          const checked = smooth.checked, disabled = smooth.disabled, title = smooth.title
          smooth.checked = true; smooth.disabled = false
          smooth.title = 'EM smooth playback: 0.5 seconds per saved frame; visual crossfade between calculated fields.'
          smooth.dispatchEvent(new Event('change'))
          batch.restorePlayback = () => { smooth.checked = checked; smooth.disabled = disabled; smooth.title = title; smooth.dispatchEvent(new Event('change')) }
        }
      } catch (error) { if (token === generation) status(error.message) }
      finally { if (token === generation) busy = false }
    }
    dialog = createModal({title:'EM trajectory analysis', size:'sm', body, actions:[no,yes]})
    dialog.root.setAttribute('aria-label','EM trajectory analysis')
    dialog.open()
    no.focus()
  }
  for (const engine of ['oxdna','md']) {
    const mount = document.getElementById(`${engine}-jobs-viz-body`)
    if (!mount) continue
    const row = document.createElement('div'); row.className = 'em-simulation-controls'
    row.innerHTML = `<label><input type="checkbox" data-em-toggle> EM visualization</label><button type="button" data-em-settings class="btn btn--sm btn--icon" aria-label="EM analysis options" title="Setting"></button><button type="button" data-em-trajectory class="btn btn--sm" title="this will perform EM analysis based on what is in the current settings (see gear)" hidden>EM Analysis</button><p data-em-status role="status"></p><p data-em-frame-status role="status"></p>`
    row.querySelector('[data-em-settings]').append(icon('settings', {size:14}))
    mount.append(row)
    const progress = document.createElement('div'); progress.className = 'em-trajectory-progress'; progress.hidden = true
    progress.setAttribute('role','progressbar'); progress.setAttribute('aria-label','Trajectory EM analysis')
    progress.setAttribute('aria-valuemin','0'); progress.setAttribute('aria-valuemax','100')
    document.getElementById(`${engine}-jobs-traj-slider`)?.parentElement.append(progress)
    const c = { engine, row, progress, frameStatus:row.querySelector('[data-em-frame-status]'), toggle:row.querySelector('[data-em-toggle]'), trajectory:row.querySelector('[data-em-trajectory]'), status:row.querySelector('[data-em-status]') }
    c.toggle.onchange = () => activate(c, c.toggle.checked)
    row.querySelector('[data-em-settings]').onclick = openSettings
    c.trajectory.onclick = () => confirmTrajectory(c)
    controls.push(c)
  }
  function changed(event) {
    const opticalChanged = JSON.stringify(opticalSettings(settings)) !== JSON.stringify(opticalSettings(event.detail))
    settings = event.detail
    if (opticalChanged) { reset(); lastTick = 0; void tick() } else redraw()
  }
  const recolor=()=>{shown='';if(batch)showCachedFrame();else redraw()}
  window.addEventListener('nadoc:em-colors', recolor)
  window.addEventListener('nadoc:em-settings', changed); addFrameCallback?.(tick)
  return { tick, dispose() { unregisterClear(); unregisterExport(); disposed = true; reset(); dialog?.close(); overlay?.dispose();
    removeFrameCallback?.(tick); window.removeEventListener('nadoc:em-colors',recolor); window.removeEventListener('nadoc:em-settings', changed); controls.forEach(c => { c.row.remove(); c.progress.remove() }) } }
}
