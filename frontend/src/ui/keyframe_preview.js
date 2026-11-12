/** One paused-player timeline shared by keyframe selection, scrubbing and transport. */
export function initKeyframePreview({ player, getAnimation, getPlayOptions = () => ({}), stopPreview, onError, window: win = window }) {
  let state = { id: null, status: 'idle', time: 0, range: null }, generation = 0, motion = 0
  let raf = null, pending = null, starting = false, savedDisablePoses = null
  const listeners = new Set()
  const notify = () => { for (const fn of listeners) fn(state) }
  function halt() { motion++; if (raf !== null) win.cancelAnimationFrame(raf); raf = null }
  function cancel() {
    generation++; halt(); pending = null
    if (savedDisablePoses !== null) player.setDisablePoses?.(savedDisablePoses)
    savedDisablePoses = null
    state = { id: null, status: 'idle', time: 0, range: null }; notify()
  }
  async function ensure(id) {
    if (state.id === id && pending) return pending
    if (state.id === id && state.range) return true
    cancel()
    const source = getAnimation(), index = source?.keyframes?.findIndex(k => k.id === id) ?? -1
    if (index < 0) return false
    const kf = source.keyframes[index]
    stopPreview?.()
    const token = generation
    state = { id, status: 'loading', time: 0, range: null }; notify()
    savedDisablePoses = player.getDisablePoses?.() ?? false
    player.setDisablePoses?.(false)
    const animation = { ...source, loop: false, keyframes: source.keyframes.slice(0, index + 1).map(k => ({ ...k, hold_duration_s: Math.max(.001, k.hold_duration_s ?? 0) })) }
    starting = true
    let work
    try { work = player.play(animation, { ...getPlayOptions(), holdKeyframeText: true }) }
    finally { starting = false }
    pending = Promise.resolve(work).then(() => {
      if (token !== generation) return false
      player.pause()
      const range = player.getKeyframeRange(id)
      if (!range) throw new Error('Keyframe is unavailable after preparation')
      state = { id, status: 'paused', time: range.start,
        range: { ...range, holdStart: Math.max(range.start, range.end - Math.max(.001, kf.hold_duration_s ?? 0)) } }
      pending = null; notify(); return true
    }).catch(error => { if (token !== generation) return false; throw error })
    return pending
  }
  async function apply(time) {
    const owner = generation, token = motion
    state = { ...state, time }; player.seekTo(time)
    try {
      const ready = await player.settleFrame()
      if (owner !== generation || token !== motion) return false
      if (ready === false) throw new Error('Selected trajectory frame is not ready')
      notify(); return true
    } catch (error) { if (owner !== generation || token !== motion) return false; throw error }
  }
  async function guarded(work) {
    try { return await work() }
    catch (error) { cancel(); player.stop(); onError?.(error) }
  }
  function pause() { halt(); if (state.range) { state = { ...state, status: 'paused' }; notify() } }
  async function play(id) {
    return guarded(async () => {
      if (!await ensure(id)) return
      halt()
      const token = motion, owner = generation
      const { start, end } = state.range
      if (state.time >= end || state.time <= start) await apply(Math.min(end, start + 1e-7))
      if (owner !== generation || token !== motion) return
      state = { ...state, status: 'playing' }; notify()
      let previous = win.performance.now()
      const tick = async now => {
        if (token !== motion || owner !== generation) return
        try { await apply(Math.min(end, state.time + Math.max(0, now - previous) / 1000)) }
        catch (error) { if (token === motion && owner === generation) { cancel(); player.stop(); onError?.(error) }; return }
        if (token !== motion || owner !== generation) return
        previous = win.performance.now()
        if (state.time < end) raf = win.requestAnimationFrame(tick)
        else { raf = null; state = { ...state, status: 'paused' }; notify() }
      }
      raf = win.requestAnimationFrame(tick)
    })
  }
  async function seek(id, fraction, holdOnly = true) {
    return guarded(async () => {
      pause()
      if (!await ensure(id)) return
      halt()
      const { start, holdStart, end } = state.range, from = holdOnly ? holdStart : start
      await apply(Math.min(end, Math.max(start + 1e-7, from + (end - from) * Math.max(0, Math.min(1, fraction)))))
    })
  }
  function toggle(id) {
    if (state.id === id && state.status === 'playing') { pause(); return Promise.resolve() }
    if (state.id === id && state.status === 'loading') { cancel(); player.stop(); return Promise.resolve() }
    return play(id)
  }
  function invalidate(id) { if (state.id === id) { cancel(); player.stop() } }
  return { play, pause, toggle, seek, cancel, invalidate,
    stop(id) { if (state.status === 'loading') { invalidate(id); return Promise.resolve() }; return seek(id, 0) },
    show: (id, playing) => playing ? play(id) : seek(id, 1),
    getState: () => state,
    subscribe(fn) { listeners.add(fn); fn(state); return () => listeners.delete(fn) },
    onPlayerEvent(event) {
      if (state.id && event.type === 'baking_progress') { state = { ...state, progress: event }; notify() }
      if ((!starting && ['stopped', 'baking'].includes(event.type)) || ['baking_cancelled', 'baking_error'].includes(event.type)) cancel()
    },
    dispose() { cancel(); listeners.clear() },
  }
}
